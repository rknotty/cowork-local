"""Phase 1 exit test: every gateway endpoint, with timings (plan section 6).

Usage:
    python -m orchestrator.smoke_test

Prints a streamed answer, a parsed tool call, an embedding vector and a
transcript, each with its duration. Run it twice: once normally and once with
Wi-Fi off, to show none of it needs the network. Exits non-zero if any check
fails.
"""

from __future__ import annotations

import asyncio
import json
import math
import struct
import sys
import tempfile
import time
import wave
from collections.abc import Awaitable, Callable
from pathlib import Path

from orchestrator.bootstrap import build_application
from orchestrator.errors import OrchestratorError
from orchestrator.gateway import ModelGateway
from orchestrator.logging_setup import configure_logging

SAMPLE_RATE_HERTZ = 16_000
TONE_SECONDS = 1.0
TONE_HERTZ = 440.0

MULTIPLY_TOOL: dict[str, object] = {
    "type": "function",
    "function": {
        "name": "multiply_numbers",
        "description": "Multiply two numbers and return the product.",
        "parameters": {
            "type": "object",
            "properties": {
                "first": {"type": "number"},
                "second": {"type": "number"},
            },
            "required": ["first", "second"],
            "additionalProperties": False,
        },
    },
}


def _report(check_name: str, is_passed: bool, detail: str, started_at: float) -> bool:
    status = "PASS" if is_passed else "FAIL"
    duration_ms = int((time.monotonic() - started_at) * 1000)
    sys.stdout.write(f"[{status}] {check_name} ({duration_ms} ms): {detail}\n")
    sys.stdout.flush()
    return is_passed


def _write_test_tone(audio_path: Path) -> None:
    """A one-second sine tone: proves the transcription path, not accuracy."""
    frame_count = int(SAMPLE_RATE_HERTZ * TONE_SECONDS)
    with wave.open(str(audio_path), "wb") as wave_file:
        wave_file.setnchannels(1)
        wave_file.setsampwidth(2)
        wave_file.setframerate(SAMPLE_RATE_HERTZ)
        wave_file.writeframes(
            b"".join(
                struct.pack(
                    "<h",
                    int(
                        8000
                        * math.sin(2 * math.pi * TONE_HERTZ * index / SAMPLE_RATE_HERTZ)
                    ),
                )
                for index in range(frame_count)
            )
        )


async def _check_chat(gateway: ModelGateway) -> bool:
    started_at = time.monotonic()
    fragments: list[str] = []
    result = await gateway.chat(
        "orchestrator",
        [{"role": "user", "content": "In one sentence, what is a spreadsheet?"}],
        on_text_delta=fragments.append,
    )
    return _report(
        "streamed chat",
        bool(result.text) and len(fragments) > 1,
        f"{len(fragments)} fragments, {result.completion_tokens} tokens, "
        f"model {result.model_id}: {result.text[:120]!r}",
        started_at,
    )


async def _check_tool_call(gateway: ModelGateway) -> bool:
    started_at = time.monotonic()
    result = await gateway.chat(
        "orchestrator",
        [{"role": "user", "content": "Use the tool to multiply 7 by 6."}],
        tools=[MULTIPLY_TOOL],
    )
    if not result.tool_calls:
        return _report(
            "tool call", False, f"no tool call; text {result.text[:120]!r}", started_at
        )
    call = result.tool_calls[0]
    try:
        arguments = json.loads(call.arguments_json)
    except json.JSONDecodeError:
        return _report(
            "tool call", False, f"bad JSON {call.arguments_json!r}", started_at
        )
    is_correct = call.name == "multiply_numbers" and {
        float(arguments.get("first", 0)),
        float(arguments.get("second", 0)),
    } == {7.0, 6.0}
    return _report("tool call", is_correct, f"{call.name}({arguments})", started_at)


async def _check_embedding(gateway: ModelGateway) -> bool:
    started_at = time.monotonic()
    result = await gateway.embed(["annual leave policy", "rail travel booking"])
    dimensions = len(result.vectors[0]) if result.vectors else 0
    return _report(
        "embeddings",
        len(result.vectors) == 2 and dimensions > 0,
        f"2 vectors of {dimensions} dimensions, first values {result.vectors[0][:3]}",
        started_at,
    )


async def _check_transcription(gateway: ModelGateway) -> bool:
    started_at = time.monotonic()
    with tempfile.TemporaryDirectory() as temporary_directory:
        audio_path = Path(temporary_directory) / "tone.wav"
        _write_test_tone(audio_path)
        result = await gateway.transcribe(audio_path)
    return _report(
        "transcription",
        True,
        f"call completed, model {result.model_id}, transcript {result.text[:80]!r}",
        started_at,
    )


async def _run_checks() -> bool:
    gateway = build_application().services.gateway
    health = await gateway.health()
    sys.stdout.write(f"Health: {json.dumps(health)}\n")
    checks: list[Callable[[ModelGateway], Awaitable[bool]]] = [
        _check_chat,
        _check_tool_call,
        _check_embedding,
        _check_transcription,
    ]
    results = []
    for check in checks:
        try:
            results.append(await check(gateway))
        except OrchestratorError as error:
            sys.stdout.write(
                f"[FAIL] {check.__name__}: {error.error_code} {error.detail}\n"
            )
            results.append(False)
    return all(results)


def main() -> None:
    """Entry point for `python -m orchestrator.smoke_test`."""
    configure_logging()
    sys.exit(0 if asyncio.run(_run_checks()) else 1)


if __name__ == "__main__":
    main()
