"""Sandbox: a dedicated WSL 2 distribution for executing code (plan section 9).

Model-generated code runs here and nowhere else. The distribution has Windows
drive automount and interop disabled, so code inside cannot see or launch
anything on the host; the orchestrator copies inputs in and outputs out
through the `\\\\wsl.localhost` share.

The builder scripts in `tools/` are a different trust class: they are this
repository's own deterministic code and take a JSON specification, not code.
They run in the sandbox when it exists. `sandbox.are_host_builders_allowed`
in config/tools.yaml permits running them on the host when it does not;
generated code never gets that fallback.
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import subprocess
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from orchestrator.errors import (
    SandboxTimeoutError,
    SandboxUnavailableError,
    ToolExecutionError,
)
from orchestrator.settings import SandboxSettings

logger = logging.getLogger(__name__)

WSL_EXECUTABLE = "wsl.exe"
SANDBOX_JOBS_PATH = "/home/{user}/jobs"
SANDBOX_TOOLS_PATH = "/home/{user}/tools"
SANDBOX_PYTHON = "/home/{user}/venv/bin/python"
OUTPUT_TAIL_CHARACTERS = 4000
STATE_READY = "ready"
STATE_UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class SandboxRun:
    """Outcome of one process run."""

    exit_code: int
    stdout: str
    stderr: str
    is_sandboxed: bool


class Sandbox:
    """Runs builders and generated code under the configured limits."""

    def __init__(
        self,
        sandbox_settings: SandboxSettings,
        builders_directory: Path,
        are_host_builders_allowed: bool,
    ) -> None:
        self._settings = sandbox_settings
        self._builders_directory = builders_directory
        self._are_host_builders_allowed = are_host_builders_allowed
        self._is_available: bool | None = None

    def state(self) -> str:
        """`ready` when the sandbox distribution exists, else `unavailable`."""
        return STATE_READY if self.is_available() else STATE_UNAVAILABLE

    def is_available(self) -> bool:
        """True when the dedicated WSL distribution is registered."""
        if self._is_available is None:
            self._is_available = self._detect_distribution()
        return self._is_available

    async def run_builder(
        self, script_name: str, specification: dict[str, Any], output_path: Path
    ) -> dict[str, Any]:
        """Run a builder script with a JSON specification.

        Args:
            script_name: A file in `tools/`, such as `build_docx.py`.
            specification: The validated tool arguments.
            output_path: Canonical host path the built file is written to.

        Returns:
            The builder's JSON report (checks passed, failures, outputs).

        Raises:
            SandboxUnavailableError: No sandbox and host builders not allowed.
            SandboxTimeoutError: The builder exceeded the wall-clock limit.
            ToolExecutionError: The builder crashed or printed no report.
        """
        if self.is_available():
            run = await asyncio.to_thread(
                self._run_builder_in_sandbox, script_name, specification, output_path
            )
        elif self._are_host_builders_allowed:
            run = await asyncio.to_thread(
                self._run_builder_on_host, script_name, specification, output_path
            )
        else:
            raise SandboxUnavailableError(
                "sandbox distribution not installed; run scripts/setup-sandbox.ps1"
            )
        try:
            report = json.loads(run.stdout.strip().splitlines()[-1])
        except (IndexError, json.JSONDecodeError) as exc:
            logger.error(
                "Builder produced no report",
                extra={
                    "builder_script": script_name,
                    "exit_code": run.exit_code,
                    "stderr_tail": run.stderr[-OUTPUT_TAIL_CHARACTERS:],
                },
            )
            raise ToolExecutionError("the document builder failed to run") from exc
        if not isinstance(report, dict):
            raise ToolExecutionError("the document builder returned a bad report")
        report["is_sandboxed"] = run.is_sandboxed
        return report

    async def run_python(self, source_code: str, workspace: Path) -> SandboxRun:
        """Run model-generated Python inside the sandbox. Never on the host.

        Files written to the job folder's `out/` are copied to the workspace.

        Raises:
            SandboxUnavailableError: The sandbox distribution is not installed.
            SandboxTimeoutError: The code exceeded the wall-clock limit.
        """
        if not self.is_available():
            raise SandboxUnavailableError(
                "generated code only runs in the sandbox, which is not installed"
            )
        return await asyncio.to_thread(
            self._run_python_in_sandbox, source_code, workspace
        )

    def _detect_distribution(self) -> bool:
        try:
            completed = subprocess.run(  # noqa: S603 - fixed executable, no shell
                [WSL_EXECUTABLE, "--list", "--quiet"],
                capture_output=True,
                timeout=15,
                check=False,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False
        # wsl.exe writes UTF-16 when its output is redirected.
        listed = completed.stdout.decode("utf-16-le", errors="ignore")
        return (
            completed.returncode == 0 and self._settings.distribution in listed.split()
        )

    def _share_path(self, sandbox_path: str) -> Path:
        windows_suffix = sandbox_path.lstrip("/").replace("/", "\\")
        return Path(
            f"\\\\wsl.localhost\\{self._settings.distribution}\\{windows_suffix}"
        )

    def _run_in_distribution(self, command: list[str]) -> SandboxRun:
        timeout_seconds = self._settings.wall_clock_timeout_seconds
        try:
            completed = subprocess.run(  # noqa: S603 - fixed executable, no shell
                [
                    WSL_EXECUTABLE,
                    "--distribution",
                    self._settings.distribution,
                    "--user",
                    self._settings.user,
                    "--",
                    # `timeout` inside the distribution kills the process tree
                    # even if the outer wsl.exe is slow to notice.
                    "timeout",
                    "--kill-after=5",
                    str(timeout_seconds),
                    *command,
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_seconds + 15,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise SandboxTimeoutError("sandboxed process exceeded its limit") from exc
        if completed.returncode == 124:
            raise SandboxTimeoutError("sandboxed process exceeded its limit")
        return SandboxRun(
            completed.returncode, completed.stdout, completed.stderr, True
        )

    def _create_job(self) -> tuple[str, Path]:
        job_path = (
            f"{SANDBOX_JOBS_PATH.format(user=self._settings.user)}/{uuid.uuid4().hex}"
        )
        self._run_in_distribution(["mkdir", "-p", f"{job_path}/out"])
        return job_path, self._share_path(job_path)

    def _run_builder_in_sandbox(
        self, script_name: str, specification: dict[str, object], output_path: Path
    ) -> SandboxRun:
        user = self._settings.user
        job_path, job_share = self._create_job()
        try:
            (job_share / "spec.json").write_text(
                json.dumps(specification), encoding="utf-8"
            )
            source_path = specification.get("source_path")
            if isinstance(source_path, str):
                shutil.copy2(source_path, job_share / Path(source_path).name)
            run = self._run_in_distribution(
                [
                    SANDBOX_PYTHON.format(user=user),
                    f"{SANDBOX_TOOLS_PATH.format(user=user)}/{script_name}",
                    f"{job_path}/spec.json",
                    f"{job_path}/out/{output_path.name}",
                ]
            )
            for produced_file in (job_share / "out").iterdir():
                shutil.copy2(produced_file, output_path.parent / produced_file.name)
            return run
        finally:
            self._run_in_distribution(["rm", "-rf", job_path])

    def _run_builder_on_host(
        self, script_name: str, specification: dict[str, object], output_path: Path
    ) -> SandboxRun:
        specification_path = output_path.parent / f".{output_path.stem}.spec.json"
        specification_path.write_text(json.dumps(specification), encoding="utf-8")
        try:
            completed = subprocess.run(  # noqa: S603 - repo script, no shell
                [
                    sys.executable,
                    str(self._builders_directory / script_name),
                    str(specification_path),
                    str(output_path),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self._settings.wall_clock_timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise SandboxTimeoutError("builder exceeded its limit") from exc
        finally:
            specification_path.unlink(missing_ok=True)
        return SandboxRun(
            completed.returncode, completed.stdout, completed.stderr, False
        )

    def _run_python_in_sandbox(self, source_code: str, workspace: Path) -> SandboxRun:
        job_path, job_share = self._create_job()
        try:
            (job_share / "main.py").write_text(source_code, encoding="utf-8")
            run = self._run_in_distribution(
                [
                    "sh",
                    "-c",
                    f"cd {job_path}/out && "
                    f"{SANDBOX_PYTHON.format(user=self._settings.user)} ../main.py",
                ]
            )
            for produced_file in (job_share / "out").iterdir():
                if produced_file.is_file():
                    shutil.copy2(produced_file, workspace / produced_file.name)
            return run
        finally:
            self._run_in_distribution(["rm", "-rf", job_path])
