"""Build a Word document from a JSON specification.

The model supplies content and structure; this script supplies everything
else. Styling comes from `templates/house.docx` when present, otherwise from
python-docx's default template. The model never controls styling.

Patch mode: when the specification has `source_path` and `patches`, the named
paragraphs of an existing document are replaced and the result is written to
a new file. The original is never modified.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import docx
from builder_common import (
    BuildReport,
    SpecificationError,
    label_as_ai_assisted,
    run_builder,
)

TEMPLATE_PATH = Path(__file__).parent / "templates" / "house.docx"
TABLE_STYLE = "Table Grid"
PLACEHOLDER_MARKERS = ("lorem ipsum", "[placeholder", "tbc", "xxx", "todo")


def _open_template() -> Any:
    if TEMPLATE_PATH.is_file():
        document = docx.Document(str(TEMPLATE_PATH))
        # A template carries sample content; the build starts from its styles only.
        for element in list(document.element.body):
            if element.tag.endswith(("}p", "}tbl")):
                document.element.body.remove(element)
        return document
    return docx.Document()


def _add_table(document: Any, block: dict[str, Any], block_number: int) -> None:
    headers = block.get("headers") or []
    rows = block.get("rows") or []
    if not headers:
        raise SpecificationError(f"block {block_number}: a table needs headers")
    for row_number, row in enumerate(rows, start=1):
        if len(row) != len(headers):
            raise SpecificationError(
                f"block {block_number}: row {row_number} has {len(row)} cells "
                f"but there are {len(headers)} headers. Make them match"
            )
    table = document.add_table(rows=1, cols=len(headers))
    table.style = TABLE_STYLE
    for cell, header in zip(table.rows[0].cells, headers, strict=True):
        cell.text = header
        cell.paragraphs[0].runs[0].bold = True
    for row in rows:
        for cell, cell_text in zip(table.add_row().cells, row, strict=True):
            cell.text = cell_text


def _add_block(document: Any, block: dict[str, Any], block_number: int) -> None:
    block_type = block["type"]
    if block_type == "heading":
        _require(block, "text", block_number)
        document.add_heading(block["text"], level=block.get("level", 1))
    elif block_type == "paragraph":
        _require(block, "text", block_number)
        document.add_paragraph(block["text"])
    elif block_type in ("bullet_list", "numbered_list"):
        _require(block, "items", block_number)
        style = "List Bullet" if block_type == "bullet_list" else "List Number"
        for list_item in block["items"]:
            document.add_paragraph(list_item, style=style)
    elif block_type == "table":
        _add_table(document, block, block_number)


def _require(block: dict[str, Any], key: str, block_number: int) -> None:
    if not block.get(key):
        raise SpecificationError(
            f"block {block_number}: a {block['type']} block needs '{key}'"
        )


def _apply_patches(specification: dict[str, Any]) -> Any:
    document = docx.Document(specification["source_path"])
    paragraphs = document.paragraphs
    for patch in specification["patches"]:
        index = patch["paragraph"]
        if not 0 <= index < len(paragraphs):
            raise SpecificationError(
                f"patch targets paragraph {index} but the document has "
                f"{len(paragraphs)} paragraphs (0 to {len(paragraphs) - 1})"
            )
        target = paragraphs[index]
        # Writing through the first run keeps the paragraph's formatting.
        if target.runs:
            target.runs[0].text = patch["text"]
            for extra_run in target.runs[1:]:
                extra_run.text = ""
        else:
            target.add_run(patch["text"])
    return document


def _check(
    output_path: Path, specification: dict[str, Any], report: BuildReport
) -> None:
    """Deterministic checks: the file reopens and holds what was specified."""
    reopened = docx.Document(str(output_path))
    paragraph_texts = [paragraph.text for paragraph in reopened.paragraphs]
    non_empty_text = " ".join(paragraph_texts).lower()
    expected_headings = [
        block["text"]
        for block in specification.get("blocks", [])
        if block["type"] == "heading"
    ]
    for heading in expected_headings:
        if heading not in paragraph_texts:
            report.fail(f"heading '{heading}' is missing from the built file")
    expected_table_count = sum(
        1 for block in specification.get("blocks", []) if block["type"] == "table"
    )
    if "blocks" in specification and len(reopened.tables) != expected_table_count:
        report.fail(
            f"expected {expected_table_count} tables, found {len(reopened.tables)}"
        )
    for marker in PLACEHOLDER_MARKERS:
        if marker in non_empty_text.split() or (
            " " in marker and marker in non_empty_text
        ):
            report.fail(f"placeholder text '{marker}' found. Replace it with content")
    report.summary = (
        f"{len([text for text in paragraph_texts if text.strip()])} paragraphs, "
        f"{len(expected_headings)} headings, {len(reopened.tables)} tables"
    )


def build(specification: dict[str, Any], output_path: Path) -> BuildReport:
    """Build or patch the document, then check it."""
    report = BuildReport(output_path)
    if specification.get("patches"):
        document = _apply_patches(specification)
    else:
        document = _open_template()
        document.add_heading(specification["title"], level=0)
        if specification.get("subtitle"):
            document.add_paragraph(specification["subtitle"], style="Subtitle")
        for block_number, block in enumerate(specification["blocks"], start=1):
            _add_block(document, block, block_number)
        document.core_properties.title = specification["title"]
    label_as_ai_assisted(document.core_properties, specification.get("model_id", ""))
    document.save(str(output_path))
    _check(output_path, specification, report)
    return report


if __name__ == "__main__":
    run_builder(build)
