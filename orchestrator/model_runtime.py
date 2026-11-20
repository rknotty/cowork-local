"""Foundry Local runtime control: endpoint discovery, model IDs, load, unload.

This is the only module that knows how Foundry Local is managed. It is kept
apart from `gateway.py` (which only speaks the OpenAI-compatible HTTP API) so
the management mechanism can change without touching inference code.

The plan prefers the Foundry Local Python SDK for management. This build uses
the `foundry` CLI's JSON output instead, because the SDK could not be
verified on this device's Arm64 Python during Phase 0. The trade-off is
recorded in docs/adr/0001-runtime-management-via-cli.md.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlparse

from orchestrator.errors import (
    GatewayRequestError,
    GatewayUnavailableError,
    NonLocalEndpointError,
)
from orchestrator.settings import GatewaySettings

logger = logging.getLogger(__name__)

ENDPOINT_OVERRIDE_VARIABLE = "LOCAL_COWORK_FOUNDRY_ENDPOINT"
FOUNDRY_EXECUTABLE = "foundry"


@dataclass(frozen=True)
class ResolvedModel:
    """A catalogue alias pinned to the concrete model it currently points at."""

    alias: str
    model_id: str
    licence: str
    execution_provider: str
    has_tool_calling: bool


class ModelRuntimeProtocol(Protocol):
    """What the gateway needs from the model runtime."""

    def resolve_endpoint(self) -> str:
        """Base URL of the local OpenAI-compatible service, without `/v1`."""
        ...

    def resolve_model(self, alias: str) -> ResolvedModel:
        """Pin an alias to its current model ID and version."""
        ...

    def start_service(self) -> None:
        """Start the local model service if it is not running."""
        ...

    def load_model(self, alias: str) -> None:
        """Load a downloaded model into memory."""
        ...

    def unload_model(self, alias: str) -> None:
        """Release a model's memory."""
        ...

    def transcribe_file(self, alias: str, audio_path: Path) -> tuple[str, str]:
        """Transcribe an audio file. Returns (text, model ID)."""
        ...


def assert_endpoint_is_local(endpoint: str, allowed_hosts: tuple[str, ...]) -> None:
    """Refuse any endpoint that is not on the loopback interface.

    This is the code-level half of the "nothing leaves the device" claim: a
    mistyped or tampered endpoint must fail closed rather than send prompts
    to another host.

    Raises:
        NonLocalEndpointError: If the host is not in the allowed list.
    """
    host = urlparse(endpoint).hostname or ""
    if host not in allowed_hosts:
        raise NonLocalEndpointError("endpoint host is not loopback", host=host)


class FoundryCliRuntime:
    """Manages Foundry Local through `foundry ... -o json`."""

    def __init__(self, gateway_settings: GatewaySettings) -> None:
        self._settings = gateway_settings
        self._catalogue_by_alias: dict[str, ResolvedModel] = {}

    def resolve_endpoint(self) -> str:
        """Read the service URL from the running daemon. Never hardcoded.

        Raises:
            GatewayUnavailableError: If the daemon is not running.
            NonLocalEndpointError: If the reported URL is not loopback.
        """
        endpoint = os.environ.get(ENDPOINT_OVERRIDE_VARIABLE, "")
        if not endpoint:
            status = self._run_json(
                ["server", "status"], self._settings.health_timeout_seconds * 4
            )
            web_urls = status.get("webUrls") or []
            if not status.get("running") or not web_urls:
                raise GatewayUnavailableError("foundry daemon is not running")
            endpoint = str(web_urls[0])
        assert_endpoint_is_local(endpoint, self._settings.allowed_hosts)
        return endpoint.rstrip("/")

    def resolve_model(self, alias: str) -> ResolvedModel:
        """Look the alias up in the catalogue and pin its model ID.

        Raises:
            GatewayRequestError: If the alias is not in the catalogue.
        """
        if not self._catalogue_by_alias:
            catalogue = self._run_json(["model", "list"], 60)
            for entry in catalogue.get("models", []):
                self._catalogue_by_alias[entry["alias"]] = ResolvedModel(
                    alias=entry["alias"],
                    model_id=entry["id"],
                    licence=entry.get("license", ""),
                    execution_provider=entry.get("executionProvider", ""),
                    has_tool_calling=bool(entry.get("supportsToolCalling", False)),
                )
        resolved_model = self._catalogue_by_alias.get(alias)
        if resolved_model is None:
            raise GatewayRequestError("alias not in catalogue", alias=alias)
        return resolved_model

    def start_service(self) -> None:
        """Start the Foundry daemon. Returns once the CLI reports it started.

        The daemon starts with no models loaded and on a new port; callers
        must re-resolve the endpoint and reload models afterwards.

        Raises:
            GatewayUnavailableError: If the CLI is missing or times out.
            GatewayRequestError: If the CLI reports a failure.
        """
        started_at = time.monotonic()
        self._run_text(["server", "start"], self._settings.load_timeout_seconds)
        logger.info(
            "Model service started",
            extra={"duration_ms": int((time.monotonic() - started_at) * 1000)},
        )

    def load_model(self, alias: str) -> None:
        """Load a model. Idempotent: loading a loaded model is a no-op."""
        started_at = time.monotonic()
        self._run_text(["model", "load", alias], self._settings.load_timeout_seconds)
        logger.info(
            "Model loaded",
            extra={
                "model_alias": alias,
                "duration_ms": int((time.monotonic() - started_at) * 1000),
            },
        )

    def unload_model(self, alias: str) -> None:
        """Unload a model. Idempotent."""
        self._run_text(["model", "unload", alias], 60)
        logger.info("Model unloaded", extra={"model_alias": alias})

    def transcribe_file(self, alias: str, audio_path: Path) -> tuple[str, str]:
        """Transcribe with `foundry transcribe --file`, loading the model if needed.

        Raises:
            GatewayRequestError: If the CLI fails or returns no text field.
        """
        transcript = self._run_json(
            ["transcribe", "--model", alias, "--file", str(audio_path)],
            self._settings.request_timeout_seconds,
        )
        if "text" not in transcript:
            raise GatewayRequestError("transcription returned no text", alias=alias)
        return str(transcript["text"]), str(transcript.get("model", alias))

    def _run_text(self, arguments: list[str], timeout_seconds: float) -> str:
        try:
            completed = subprocess.run(  # noqa: S603 - fixed executable, no shell
                [FOUNDRY_EXECUTABLE, *arguments],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_seconds,
                check=False,
            )
        except FileNotFoundError as exc:
            raise GatewayUnavailableError("foundry CLI is not installed") from exc
        except subprocess.TimeoutExpired as exc:
            raise GatewayUnavailableError(
                "foundry CLI timed out", command=" ".join(arguments)
            ) from exc
        if completed.returncode != 0:
            raise GatewayRequestError(
                "foundry CLI failed",
                command=" ".join(arguments),
                exit_code=completed.returncode,
                stderr_tail=completed.stderr[-300:],
            )
        return completed.stdout

    def _run_json(self, arguments: list[str], timeout_seconds: float) -> dict[str, Any]:
        raw_output = self._run_text([*arguments, "-o", "json"], timeout_seconds)
        try:
            parsed = json.loads(raw_output)
        except json.JSONDecodeError as exc:
            raise GatewayRequestError(
                "foundry CLI returned non-JSON output", command=" ".join(arguments)
            ) from exc
        if not isinstance(parsed, dict):
            raise GatewayRequestError(
                "foundry CLI returned unexpected JSON", command=" ".join(arguments)
            )
        return parsed
