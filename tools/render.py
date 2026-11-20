"""Render an Office file to PDF with LibreOffice in headless mode.

Runs only inside the sandbox, where LibreOffice is installed. The interface
previews the PDF; `build_pdf` uses the same conversion as its output.

Contract matches the builders: `python render.py <spec.json> <output.pdf>`
with `{"source_path": "<file inside the job folder>"}`.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

from builder_common import BuildReport, SpecificationError, run_builder

LIBREOFFICE_EXECUTABLE = "soffice"
CONVERSION_TIMEOUT_SECONDS = 90


def build(specification: dict[str, Any], output_path: Path) -> BuildReport:
    """Convert the source document to PDF beside the requested output path."""
    report = BuildReport(output_path)
    if shutil.which(LIBREOFFICE_EXECUTABLE) is None:
        raise SpecificationError("LibreOffice is not installed in this environment")
    # Inside the sandbox the orchestrator copies the source into the job folder.
    source_path = output_path.parent.parent / Path(specification["source_path"]).name
    if not source_path.is_file():
        source_path = Path(specification["source_path"])
    completed = subprocess.run(  # noqa: S603 - fixed executable, no shell
        [
            LIBREOFFICE_EXECUTABLE,
            "--headless",
            "--convert-to",
            "pdf",
            "--outdir",
            str(output_path.parent),
            str(source_path),
        ],
        capture_output=True,
        text=True,
        timeout=CONVERSION_TIMEOUT_SECONDS,
        check=False,
    )
    converted_path = output_path.parent / f"{source_path.stem}.pdf"
    if completed.returncode != 0 or not converted_path.is_file():
        report.fail("LibreOffice could not convert the document to PDF")
        return report
    if converted_path != output_path:
        converted_path.replace(output_path)
    report.summary = f"rendered {source_path.name} to PDF"
    return report


if __name__ == "__main__":
    run_builder(build)
