"""Build a PowerPoint deck from a JSON specification.

Eight named layouts, each drawn by this script at fixed positions. The model
chooses a layout and supplies text; it never controls geometry or styling,
which is what keeps a small model's output from overflowing the slide.

Patch mode: with `source_path` and `patches`, the title or body text of
numbered slides in an existing deck is replaced and written to a new file.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from builder_common import (
    BuildReport,
    SpecificationError,
    label_as_ai_assisted,
    run_builder,
)
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.util import Inches, Pt

SLIDE_WIDTH_INCHES = 13.333
SLIDE_HEIGHT_INCHES = 7.5
MARGIN_INCHES = 0.7
CONTENT_WIDTH_INCHES = SLIDE_WIDTH_INCHES - 2 * MARGIN_INCHES
BLANK_LAYOUT_INDEX = 6

# Neutral house palette. Replace these, or supply a branded template, to
# restyle every deck without touching a prompt.
INK = RGBColor(0x1F, 0x29, 0x37)
MUTED = RGBColor(0x5B, 0x67, 0x78)
ACCENT = RGBColor(0x0F, 0x76, 0x6E)
PAPER = RGBColor(0xFF, 0xFF, 0xFF)

TITLE_POINTS = 32
BODY_POINTS = 20
# Average glyph width as a fraction of the point size, for the overflow
# estimate. Conservative for a proportional sans-serif.
GLYPH_WIDTH_RATIO = 0.55
LINE_HEIGHT_RATIO = 1.35
POINTS_PER_INCH = 72


class SlideCanvas:
    """Drawing helpers for one slide, with an overflow estimate per text box."""

    def __init__(self, slide: Any, slide_number: int, report: BuildReport) -> None:
        self._slide = slide
        self._slide_number = slide_number
        self._report = report

    def add_text(
        self,
        lines: list[str],
        left: float,
        top: float,
        width: float,
        height: float,
        points: int = BODY_POINTS,
        colour: RGBColor = INK,
        is_bold: bool = False,
        bullet: str = "",
    ) -> None:
        """Add a text box and record a failure if the text cannot fit it."""
        text_box = self._slide.shapes.add_textbox(
            Inches(left), Inches(top), Inches(width), Inches(height)
        )
        frame = text_box.text_frame
        frame.word_wrap = True
        for index, line in enumerate(lines):
            paragraph = frame.paragraphs[0] if index == 0 else frame.add_paragraph()
            run = paragraph.add_run()
            run.text = f"{bullet}{line}"
            run.font.size = Pt(points)
            run.font.bold = is_bold
            run.font.color.rgb = colour
            paragraph.space_after = Pt(points * 0.4)
        self._check_fit(lines, width, height, points)

    def _check_fit(
        self, lines: list[str], width: float, height: float, points: int
    ) -> None:
        characters_per_line = max(
            1, int(width * POINTS_PER_INCH / (points * GLYPH_WIDTH_RATIO))
        )
        wrapped_line_count = sum(
            max(1, -(-len(line) // characters_per_line)) for line in lines
        )
        needed_inches = (
            wrapped_line_count * points * LINE_HEIGHT_RATIO
            # Spacing sits between paragraphs, not after the last one.
            + (len(lines) - 1) * points * 0.4
        ) / POINTS_PER_INCH
        if needed_inches > height:
            self._report.fail(
                f"slide {self._slide_number}: text overflows its box (needs about "
                f"{needed_inches:.1f} in, has {height:.1f} in). Shorten the text "
                "or split it across two slides"
            )

    def add_title(self, title: str) -> None:
        """The standard slide title with its accent rule."""
        self.add_text(
            [title],
            MARGIN_INCHES,
            0.5,
            CONTENT_WIDTH_INCHES,
            1.1,
            points=TITLE_POINTS,
            is_bold=True,
        )
        rule = self._slide.shapes.add_shape(
            1, Inches(MARGIN_INCHES), Inches(1.55), Inches(1.2), Inches(0.06)
        )
        rule.fill.solid()
        rule.fill.fore_color.rgb = ACCENT
        rule.line.fill.background()

    def add_table(self, headers: list[str], rows: list[list[str]]) -> None:
        """A simple table under the title."""
        for row_number, row in enumerate(rows, start=1):
            if len(row) != len(headers):
                raise SpecificationError(
                    f"slide {self._slide_number}: table row {row_number} has "
                    f"{len(row)} cells but there are {len(headers)} headers"
                )
        shape = self._slide.shapes.add_table(
            len(rows) + 1,
            len(headers),
            Inches(MARGIN_INCHES),
            Inches(1.9),
            Inches(CONTENT_WIDTH_INCHES),
            Inches(0.5 * (len(rows) + 1)),
        )
        for column, header in enumerate(headers):
            shape.table.cell(0, column).text = header
        for row_index, row in enumerate(rows, start=1):
            for column, cell_text in enumerate(row):
                shape.table.cell(row_index, column).text = cell_text


def _need(slide_spec: dict[str, Any], key: str, slide_number: int) -> Any:
    if not slide_spec.get(key):
        raise SpecificationError(
            f"slide {slide_number}: layout '{slide_spec['layout']}' needs '{key}'"
        )
    return slide_spec[key]


def _draw_title(canvas: SlideCanvas, spec: dict[str, Any], number: int) -> None:
    canvas.add_text(
        [spec["title"]],
        MARGIN_INCHES,
        2.4,
        CONTENT_WIDTH_INCHES,
        1.8,
        points=44,
        is_bold=True,
    )
    if spec.get("subtitle"):
        canvas.add_text(
            [spec["subtitle"]],
            MARGIN_INCHES,
            4.3,
            CONTENT_WIDTH_INCHES,
            1.0,
            points=22,
            colour=MUTED,
        )


def _draw_section(canvas: SlideCanvas, spec: dict[str, Any], number: int) -> None:
    canvas.add_text(
        [spec["title"]],
        MARGIN_INCHES,
        3.0,
        CONTENT_WIDTH_INCHES,
        1.4,
        points=38,
        is_bold=True,
        colour=ACCENT,
    )
    if spec.get("subtitle"):
        canvas.add_text(
            [spec["subtitle"]],
            MARGIN_INCHES,
            4.4,
            CONTENT_WIDTH_INCHES,
            0.9,
            colour=MUTED,
        )


def _draw_bullets(canvas: SlideCanvas, spec: dict[str, Any], number: int) -> None:
    canvas.add_title(spec["title"])
    canvas.add_text(
        _need(spec, "bullets", number),
        MARGIN_INCHES,
        1.9,
        CONTENT_WIDTH_INCHES,
        4.9,
        bullet="• ",
    )


def _draw_two_column(canvas: SlideCanvas, spec: dict[str, Any], number: int) -> None:
    canvas.add_title(spec["title"])
    column_width = (CONTENT_WIDTH_INCHES - 0.5) / 2
    canvas.add_text(
        _need(spec, "left_bullets", number),
        MARGIN_INCHES,
        1.9,
        column_width,
        4.9,
        points=18,
        bullet="• ",
    )
    canvas.add_text(
        _need(spec, "right_bullets", number),
        MARGIN_INCHES + column_width + 0.5,
        1.9,
        column_width,
        4.9,
        points=18,
        bullet="• ",
    )


def _draw_quote(canvas: SlideCanvas, spec: dict[str, Any], number: int) -> None:
    canvas.add_title(spec["title"])
    canvas.add_text(
        [f"“{_need(spec, 'quote', number)}”"],
        1.5,
        2.3,
        SLIDE_WIDTH_INCHES - 3.0,
        3.0,
        points=28,
        colour=ACCENT,
    )
    if spec.get("attribution"):
        canvas.add_text(
            [f"— {spec['attribution']}"],
            1.5,
            5.4,
            SLIDE_WIDTH_INCHES - 3.0,
            0.7,
            points=18,
            colour=MUTED,
        )


def _draw_table(canvas: SlideCanvas, spec: dict[str, Any], number: int) -> None:
    canvas.add_title(spec["title"])
    canvas.add_table(_need(spec, "headers", number), _need(spec, "rows", number))


def _draw_big_number(canvas: SlideCanvas, spec: dict[str, Any], number: int) -> None:
    canvas.add_title(spec["title"])
    canvas.add_text(
        [_need(spec, "number", number)],
        MARGIN_INCHES,
        2.2,
        CONTENT_WIDTH_INCHES,
        2.4,
        points=110,
        is_bold=True,
        colour=ACCENT,
    )
    if spec.get("caption"):
        canvas.add_text(
            [spec["caption"]],
            MARGIN_INCHES,
            4.9,
            CONTENT_WIDTH_INCHES,
            1.2,
            points=22,
            colour=MUTED,
        )


def _draw_closing(canvas: SlideCanvas, spec: dict[str, Any], number: int) -> None:
    canvas.add_text(
        [spec["title"]],
        MARGIN_INCHES,
        2.2,
        CONTENT_WIDTH_INCHES,
        1.4,
        points=40,
        is_bold=True,
    )
    if spec.get("bullets"):
        canvas.add_text(
            spec["bullets"], MARGIN_INCHES, 3.7, CONTENT_WIDTH_INCHES, 3.0, bullet="• "
        )


LAYOUT_DRAWERS: dict[str, Callable[[SlideCanvas, dict[str, Any], int], None]] = {
    "title": _draw_title,
    "section": _draw_section,
    "bullets": _draw_bullets,
    "two_column": _draw_two_column,
    "quote": _draw_quote,
    "table": _draw_table,
    "big_number": _draw_big_number,
    "closing": _draw_closing,
}


def _apply_patches(specification: dict[str, Any]) -> Any:
    presentation = Presentation(specification["source_path"])
    slides = list(presentation.slides)
    for patch in specification["patches"]:
        slide_number = patch["slide"]
        if not 1 <= slide_number <= len(slides):
            raise SpecificationError(
                f"patch targets slide {slide_number} but the deck has {len(slides)}"
            )
        text_shapes = [
            shape for shape in slides[slide_number - 1].shapes if shape.has_text_frame
        ]
        shape_index = patch.get("shape", 0)
        if not 0 <= shape_index < len(text_shapes):
            raise SpecificationError(
                f"slide {slide_number} has {len(text_shapes)} text shapes "
                f"(0 to {len(text_shapes) - 1}); shape {shape_index} does not exist"
            )
        paragraphs = text_shapes[shape_index].text_frame.paragraphs
        first_run = (
            paragraphs[0].runs[0] if paragraphs[0].runs else paragraphs[0].add_run()
        )
        first_run.text = patch["text"]
    return presentation


def _check(
    output_path: Path, specification: dict[str, Any], report: BuildReport
) -> None:
    reopened = Presentation(str(output_path))
    slide_count = len(reopened.slides)
    expected_count = len(specification.get("slides", [])) or slide_count
    if slide_count != expected_count:
        report.fail(f"expected {expected_count} slides, built {slide_count}")
    for slide_number, slide in enumerate(reopened.slides, start=1):
        has_text = any(
            shape.has_text_frame and shape.text_frame.text.strip()
            for shape in slide.shapes
        )
        if not has_text:
            report.fail(f"slide {slide_number} is empty. Give it content or remove it")
    report.summary = f"{slide_count} slides"


def build(specification: dict[str, Any], output_path: Path) -> BuildReport:
    """Build or patch the deck, then check it."""
    report = BuildReport(output_path)
    if specification.get("patches"):
        presentation = _apply_patches(specification)
    else:
        presentation = Presentation()
        presentation.slide_width = Inches(SLIDE_WIDTH_INCHES)
        presentation.slide_height = Inches(SLIDE_HEIGHT_INCHES)
        blank_layout = presentation.slide_layouts[BLANK_LAYOUT_INDEX]
        for slide_number, slide_spec in enumerate(specification["slides"], start=1):
            slide = presentation.slides.add_slide(blank_layout)
            canvas = SlideCanvas(slide, slide_number, report)
            LAYOUT_DRAWERS[slide_spec["layout"]](canvas, slide_spec, slide_number)
            if slide_spec.get("notes"):
                slide.notes_slide.notes_text_frame.text = slide_spec["notes"]
        presentation.core_properties.title = specification["slides"][0]["title"]
    label_as_ai_assisted(
        presentation.core_properties, specification.get("model_id", "")
    )
    presentation.save(str(output_path))
    _check(output_path, specification, report)
    return report


if __name__ == "__main__":
    run_builder(build)
