"""Document tools (plan section 11).

Design rule: the model writes a specification, our code writes the file.
Each builder tool takes a constrained JSON document, runs a deterministic
builder and returns the builder's check failures so the model can correct
the specification.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from orchestrator.errors import (
    OrchestratorError,
    SandboxUnavailableError,
    ToolExecutionError,
)
from orchestrator.toolkit.context import ToolContext
from orchestrator.toolkit.file_tools import announce_artefact
from orchestrator.toolkit.registry import (
    ToolDefinition,
    ToolOutput,
    ToolRegistry,
    ToolTier,
    object_schema,
)

logger = logging.getLogger(__name__)

RENDER_SCRIPT = "render.py"
MAX_STRUCTURE_ENTRIES = 120
MAX_ENTRY_CHARACTERS = 160
BUILDERS = {
    "build_docx": ("build_docx.py", ".docx"),
    "build_pptx": ("build_pptx.py", ".pptx"),
    "build_xlsx": ("build_xlsx.py", ".xlsx"),
}
BUILDER_DESCRIPTIONS = {
    "build_docx": (
        "Create a Word document from a title and a list of blocks (heading, "
        "paragraph, bullet_list, numbered_list, table). Styling is applied "
        "for you; supply content only."
    ),
    "build_pptx": (
        "Create a PowerPoint deck from a list of slides, each naming a layout "
        "(title, section, bullets, two_column, quote, table, big_number, "
        "closing). Keep bullets short; overflowing text is reported back."
    ),
    "build_xlsx": (
        "Create an Excel workbook from sheets with headers and rows. "
        "Write a formula as a string starting with =, such as =SUM(B2:B9)."
    ),
}
BUILDER_KEYWORDS = {
    "build_docx": ("word", "document", "docx", "report", "letter", "memo"),
    "build_pptx": ("powerpoint", "slides", "deck", "presentation", "pptx"),
    "build_xlsx": ("excel", "spreadsheet", "workbook", "xlsx", "table", "budget"),
}


def _resolve_output(context: ToolContext, requested_path: str, suffix: str) -> Path:
    canonical_path = context.allowlist.resolve_allowed(requested_path)
    if canonical_path.suffix.lower() != suffix:
        raise ToolExecutionError(f"path must end in {suffix}")
    canonical_path.parent.mkdir(parents=True, exist_ok=True)
    return canonical_path


async def _render_preview(context: ToolContext, built_path: Path) -> Path | None:
    """Render a PDF preview in the sandbox. None when there is no sandbox."""
    sandbox = context.services.sandbox
    if not sandbox.is_available():
        return None
    preview_path = built_path.with_suffix(".preview.pdf")
    try:
        report = await sandbox.run_builder(
            RENDER_SCRIPT, {"source_path": str(built_path)}, preview_path
        )
    except OrchestratorError as error:
        # The document itself was built; a missing preview must not fail it.
        logger.warning("Preview render failed", extra={"error_code": error.error_code})
        return None
    return preview_path if report.get("is_valid") else None


def _format_report(report: dict[str, Any], requested_path: str) -> str:
    failures = report.get("failures") or []
    if failures:
        failure_lines = "\n".join(f"- {failure}" for failure in failures)
        return (
            f"Built {requested_path} but it failed these checks. Correct the "
            f"specification and call the tool again:\n{failure_lines}"
        )
    host_note = (
        ""
        if report.get("is_sandboxed")
        else " No preview render: the sandbox is not installed."
    )
    return f"Built {requested_path} ({report.get('summary')}). All checks passed.{host_note}"


def _make_builder_handler(tool_name: str) -> Any:
    script_name, suffix = BUILDERS[tool_name]

    async def run_builder(
        context: ToolContext, arguments: dict[str, Any]
    ) -> ToolOutput:
        output_path = _resolve_output(context, arguments["path"], suffix)
        specification = {**arguments, "model_id": context.model_id}
        report = await context.services.sandbox.run_builder(
            script_name, specification, output_path
        )
        if output_path.is_file():
            preview_path = await _render_preview(context, output_path)
            announce_artefact(context, output_path, preview_path)
        return ToolOutput(_format_report(report, arguments["path"]))

    return run_builder


async def build_pdf(context: ToolContext, arguments: dict[str, Any]) -> ToolOutput:
    """Convert an existing Word document to PDF in the sandbox."""
    source_path = context.allowlist.resolve_allowed(arguments["source_path"])
    if source_path.suffix.lower() != ".docx" or not source_path.is_file():
        raise ToolExecutionError("source_path must be an existing .docx file")
    output_path = _resolve_output(context, arguments["path"], ".pdf")
    if not context.services.sandbox.is_available():
        raise SandboxUnavailableError(
            "PDF conversion needs LibreOffice in the sandbox, which is not installed"
        )
    report = await context.services.sandbox.run_builder(
        RENDER_SCRIPT, {"source_path": str(source_path)}, output_path
    )
    if output_path.is_file():
        announce_artefact(context, output_path, output_path)
    return ToolOutput(_format_report(report, arguments["path"]))


def _preview(text: str) -> str:
    """Shorten an entry for the structure listing, and say so when it does.

    read_document is for finding addresses to patch, not for reading content.
    Truncating silently once made a 76,000-character transcript look read
    when the model had seen 160 characters of it.
    """
    if len(text) <= MAX_ENTRY_CHARACTERS:
        return text
    omitted = len(text) - MAX_ENTRY_CHARACTERS
    return (
        f"{text[:MAX_ENTRY_CHARACTERS]} [... {omitted:,} more characters not shown. "
        "To use the content, call extract_from_document]"
    )


def _describe_docx(path: Path) -> list[str]:
    import docx

    return [
        f"paragraph {index} [{paragraph.style.name if paragraph.style else ''}]: "
        f"{_preview(paragraph.text)}"
        for index, paragraph in enumerate(docx.Document(str(path)).paragraphs)
        if paragraph.text.strip()
    ]


def _describe_pptx(path: Path) -> list[str]:
    from pptx import Presentation

    lines = []
    for slide_number, slide in enumerate(Presentation(str(path)).slides, start=1):
        text_shapes = [shape for shape in slide.shapes if shape.has_text_frame]
        for shape_index, shape in enumerate(text_shapes):
            text = shape.text_frame.text.replace("\n", " / ")
            lines.append(f"slide {slide_number} shape {shape_index}: {_preview(text)}")
    return lines


def _describe_xlsx(path: Path) -> list[str]:
    from openpyxl import load_workbook

    workbook = load_workbook(str(path), read_only=True)
    lines = []
    try:
        for worksheet in workbook.worksheets:
            lines.append(f"sheet '{worksheet.title}':")
            for row in worksheet.iter_rows():
                cells = [
                    f"{cell.coordinate}={str(cell.value)[:40]}"
                    for cell in row
                    if cell.value is not None
                ]
                if cells:
                    lines.append("  " + ", ".join(cells))
    finally:
        workbook.close()
    return lines


_DESCRIBERS = {
    ".docx": _describe_docx,
    ".pptx": _describe_pptx,
    ".xlsx": _describe_xlsx,
}


async def read_document(context: ToolContext, arguments: dict[str, Any]) -> ToolOutput:
    """Return an Office file's structure with the addresses patches use."""
    canonical_path = context.allowlist.resolve_allowed(arguments["path"])
    describer = _DESCRIBERS.get(canonical_path.suffix.lower())
    if describer is None or not canonical_path.is_file():
        raise ToolExecutionError("path must be an existing .docx, .pptx or .xlsx file")
    lines = describer(canonical_path)
    shown_lines = lines[:MAX_STRUCTURE_ENTRIES]
    if len(lines) > MAX_STRUCTURE_ENTRIES:
        shown_lines.append(f"[... {len(lines) - MAX_STRUCTURE_ENTRIES} more entries]")
    return ToolOutput("\n".join(shown_lines) or "(no text content)")


async def patch_document(context: ToolContext, arguments: dict[str, Any]) -> ToolOutput:
    """Change named elements of an Office file, writing a new file beside it."""
    source_path = context.allowlist.resolve_allowed(arguments["source_path"])
    suffix = source_path.suffix.lower()
    tool_name = next(
        (
            name
            for name, (_, builder_suffix) in BUILDERS.items()
            if builder_suffix == suffix
        ),
        None,
    )
    if tool_name is None or not source_path.is_file():
        raise ToolExecutionError(
            "source_path must be an existing .docx, .pptx or .xlsx file"
        )
    output_path = _resolve_output(context, arguments["path"], suffix)
    if output_path == source_path:
        raise ToolExecutionError(
            "path must differ from source_path: the original is never overwritten"
        )
    specification = {
        "source_path": str(source_path),
        "patches": arguments["patches"],
        "model_id": context.model_id,
    }
    report = await context.services.sandbox.run_builder(
        BUILDERS[tool_name][0], specification, output_path
    )
    if output_path.is_file():
        announce_artefact(
            context, output_path, await _render_preview(context, output_path)
        )
    return ToolOutput(_format_report(report, arguments["path"]))


async def run_python(context: ToolContext, arguments: dict[str, Any]) -> ToolOutput:
    """Run generated Python in the sandbox. The free-form escape hatch."""
    run = await context.services.sandbox.run_python(
        arguments["code"], context.allowlist.workspace
    )
    return ToolOutput(
        f"exit code {run.exit_code}\nstdout:\n{run.stdout}\nstderr:\n{run.stderr}"
    )


def register_document_tools(registry: ToolRegistry, builders_directory: Path) -> None:
    """Register the builders, reader, patcher, PDF conversion and run_python."""
    for tool_name, (_, _suffix) in BUILDERS.items():
        schema_path = builders_directory / "schemas" / f"{tool_name}.json"
        registry.register(
            ToolDefinition(
                name=tool_name,
                description=BUILDER_DESCRIPTIONS[tool_name],
                parameters=json.loads(schema_path.read_text(encoding="utf-8")),
                tier=ToolTier.EXECUTE,
                handler=_make_builder_handler(tool_name),
                target_argument="path",
                keywords=BUILDER_KEYWORDS[tool_name],
            )
        )
    path_property = {"type": "string"}
    registry.register(
        ToolDefinition(
            name="build_pdf",
            description=(
                "Convert an existing Word document to PDF. "
                "Build the .docx first with build_docx."
            ),
            parameters=object_schema(
                {"source_path": path_property, "path": path_property},
                ["source_path", "path"],
            ),
            tier=ToolTier.EXECUTE,
            handler=build_pdf,
            target_argument="path",
            keywords=("pdf", "convert", "export"),
        )
    )
    registry.register(
        ToolDefinition(
            name="read_document",
            description=(
                "Read the structure of a Word, PowerPoint or Excel file. "
                "Returns numbered paragraphs, slides or cells you can patch."
            ),
            parameters=object_schema({"path": path_property}, ["path"]),
            tier=ToolTier.READ,
            handler=read_document,
            target_argument="path",
            keywords=("word", "powerpoint", "excel", "docx", "pptx", "xlsx", "open"),
        )
    )
    registry.register(
        ToolDefinition(
            name="patch_document",
            description=(
                "Change named parts of an existing Word, PowerPoint or Excel "
                "file and save the result as a new file. Call read_document "
                "first to get paragraph, slide or cell addresses."
            ),
            parameters=object_schema(
                {
                    "source_path": path_property,
                    "path": path_property,
                    "patches": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 40,
                        "items": {
                            "type": "object",
                            "properties": {
                                "paragraph": {"type": "integer", "minimum": 0},
                                "slide": {"type": "integer", "minimum": 1},
                                "shape": {"type": "integer", "minimum": 0},
                                "sheet": {"type": "string"},
                                "cell": {"type": "string"},
                                "text": {"type": "string"},
                                "value": {
                                    "type": ["string", "number", "boolean", "null"]
                                },
                            },
                            "additionalProperties": False,
                        },
                    },
                },
                ["source_path", "path", "patches"],
            ),
            tier=ToolTier.EXECUTE,
            handler=patch_document,
            target_argument="path",
            keywords=("edit", "change", "update", "modify", "word", "excel", "slides"),
        )
    )
    registry.register(
        ToolDefinition(
            name="run_python",
            description=(
                "Run Python code in the isolated sandbox when no builder tool "
                "fits. Less reliable than the builders; files saved to the "
                "current folder are copied to the workspace."
            ),
            parameters=object_schema(
                {"code": {"type": "string", "minLength": 1}}, ["code"]
            ),
            tier=ToolTier.EXECUTE,
            handler=run_python,
            keywords=("python", "script", "code", "calculate", "chart"),
        )
    )
