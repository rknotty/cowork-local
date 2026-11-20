"""Shared plumbing for the document builders.

Builders are standalone scripts: they run inside the sandbox, where the
orchestrator package is not installed, so nothing here imports from it.

Contract: `python build_x.py <spec.json> <output_path>` writes the file and
prints one JSON report as its last line of stdout:

    {"is_valid": bool, "output_file": str, "failures": [str], "summary": str}

`failures` are written for the model to read and act on: each names what is
wrong and how to correct the specification.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

AI_ASSISTED_LABEL = "AI-assisted: generated on-device by a local model"
EXIT_INVALID_USAGE = 2

BuildFunction = Callable[[dict[str, Any], Path], "BuildReport"]


class SpecificationError(Exception):
    """The specification is structurally valid but cannot be built."""


class BuildReport:
    """Collects check failures and renders the report line."""

    def __init__(self, output_path: Path) -> None:
        self._output_path = output_path
        self.failures: list[str] = []
        self.summary = ""

    def fail(self, message: str) -> None:
        """Record one check failure."""
        self.failures.append(message)

    def render(self) -> str:
        """The JSON report line."""
        return json.dumps(
            {
                "is_valid": not self.failures,
                "output_file": self._output_path.name,
                "failures": self.failures,
                "summary": self.summary,
            }
        )


def label_as_ai_assisted(core_properties: Any, model_id: str) -> None:
    """Mark a document's properties so its origin is discoverable.

    Human oversight control (plan section 13, control 7): a reader should be
    able to tell that a document was drafted by a model.
    """
    core_properties.comments = (
        f"{AI_ASSISTED_LABEL} ({model_id or 'model not recorded'})"
    )
    core_properties.category = "AI-assisted"


def run_builder(build: BuildFunction) -> None:
    """Entry point shared by every builder script."""
    if len(sys.argv) != 3:
        sys.stderr.write("usage: <builder>.py <spec.json> <output_path>\n")
        sys.exit(EXIT_INVALID_USAGE)
    specification = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    output_path = Path(sys.argv[2])
    try:
        report = build(specification, output_path)
    except SpecificationError as error:
        report = BuildReport(output_path)
        report.fail(str(error))
    sys.stdout.write(report.render() + "\n")
