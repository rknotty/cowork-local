"""Convert documents to markdown-like text for indexing (plan section 12).

Word, PowerPoint and Excel are parsed with the same libraries the builders
use, so the knowledge index has no extra dependency to verify on Arm64. PDF
is parsed through MarkItDown when it is installed and skipped, with a logged
warning, when it is not.
"""

from __future__ import annotations

import html
import logging
import re
from collections.abc import Callable
from pathlib import Path

logger = logging.getLogger(__name__)

PLAIN_TEXT_SUFFIXES = {".md", ".txt", ".csv", ".json", ".yaml", ".yml"}
HTML_SUFFIXES = {".html", ".htm"}
_HTML_BLOCK_PATTERN = re.compile(r"(?is)<(script|style)\b.*?</\1>")
_HTML_HEADING_PATTERN = re.compile(r"(?is)<h([1-6])[^>]*>(.*?)</h\1>")
_HTML_TAG_PATTERN = re.compile(r"(?s)<[^>]+>")
WORD_HEADING_STYLE_PREFIX = "Heading "


def _parse_docx(path: Path) -> str:
    import docx

    lines: list[str] = []
    for paragraph in docx.Document(str(path)).paragraphs:
        text = paragraph.text.strip()
        if not text:
            continue
        style_name = paragraph.style.name if paragraph.style is not None else ""
        if style_name == "Title":
            lines.append(f"# {text}")
        elif style_name.startswith(WORD_HEADING_STYLE_PREFIX):
            level_text = style_name.removeprefix(WORD_HEADING_STYLE_PREFIX)
            level = int(level_text) if level_text.isdigit() else 1
            lines.append(f"{'#' * min(level + 1, 6)} {text}")
        else:
            lines.append(text)
    return "\n\n".join(lines)


def _parse_pptx(path: Path) -> str:
    from pptx import Presentation

    sections: list[str] = []
    for slide_number, slide in enumerate(Presentation(str(path)).slides, start=1):
        title_shape = slide.shapes.title
        title = title_shape.text.strip() if title_shape is not None else ""
        body_lines = [
            shape.text_frame.text.strip()
            for shape in slide.shapes
            if shape.has_text_frame
            and shape != title_shape
            and shape.text_frame.text.strip()
        ]
        sections.append(
            f"## Slide {slide_number}: {title}\n\n" + "\n\n".join(body_lines)
        )
    return "\n\n".join(sections)


def _parse_xlsx(path: Path) -> str:
    from openpyxl import load_workbook

    workbook = load_workbook(str(path), read_only=True, data_only=True)
    sections: list[str] = []
    try:
        for worksheet in workbook.worksheets:
            rows = [
                " | ".join("" if cell is None else str(cell) for cell in row)
                for row in worksheet.iter_rows(values_only=True)
                if any(cell is not None for cell in row)
            ]
            sections.append(f"## Sheet: {worksheet.title}\n\n" + "\n".join(rows))
    finally:
        workbook.close()
    return "\n\n".join(sections)


def _parse_html(path: Path) -> str:
    raw_text = path.read_text(encoding="utf-8", errors="replace")
    without_code = _HTML_BLOCK_PATTERN.sub(" ", raw_text)
    with_headings = _HTML_HEADING_PATTERN.sub(
        lambda match: f"\n\n{'#' * int(match.group(1))} {match.group(2)}\n\n",
        without_code,
    )
    return html.unescape(_HTML_TAG_PATTERN.sub(" ", with_headings))


def _parse_pdf(path: Path) -> str:
    try:
        from markitdown import MarkItDown
    except ImportError:
        logger.warning(
            "PDF skipped: MarkItDown is not installed on this device",
            extra={"file_name": path.name},
        )
        return ""
    return str(MarkItDown().convert(str(path)).text_content)


_PARSERS: dict[str, Callable[[Path], str]] = {
    ".docx": _parse_docx,
    ".pptx": _parse_pptx,
    ".xlsx": _parse_xlsx,
    ".pdf": _parse_pdf,
    **{suffix: _parse_html for suffix in HTML_SUFFIXES},
}

SUPPORTED_SUFFIXES = frozenset(_PARSERS) | PLAIN_TEXT_SUFFIXES


def parse_document(path: Path) -> str:
    """Return the document's text as markdown, or "" if it cannot be parsed.

    A file that fails to parse is logged and skipped rather than aborting the
    whole indexing run: one corrupt document should not hide the other 49.
    """
    suffix = path.suffix.lower()
    if suffix in PLAIN_TEXT_SUFFIXES:
        return path.read_text(encoding="utf-8", errors="replace")
    parser = _PARSERS.get(suffix)
    if parser is None:
        return ""
    try:
        return parser(path)
    except Exception:  # noqa: BLE001 - third-party parsers raise many types
        logger.exception("Document failed to parse", extra={"file_name": path.name})
        return ""
