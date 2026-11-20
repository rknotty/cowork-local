"""Build an Excel workbook from a JSON specification.

Sheets, headers, rows and formulas-as-strings. Formulas are written as the
model gave them and are evaluated by Excel on open; this script checks their
shape, not their result.

Patch mode: with `source_path` and `patches`, named cells of an existing
workbook are set and the result is written to a new file.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from builder_common import (
    BuildReport,
    SpecificationError,
    label_as_ai_assisted,
    run_builder,
)
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

HEADER_FILL = PatternFill("solid", fgColor="E5E7EB")
MIN_COLUMN_WIDTH = 10
MAX_COLUMN_WIDTH = 60
_CELL_REFERENCE_PATTERN = re.compile(r"^[A-Z]{1,3}[1-9][0-9]{0,6}$")
_FORBIDDEN_SHEET_CHARACTERS = set("[]:*?/\\")


def _write_sheet(
    workbook: Workbook, sheet_spec: dict[str, Any], is_first: bool
) -> None:
    name = sheet_spec["name"]
    if _FORBIDDEN_SHEET_CHARACTERS.intersection(name):
        raise SpecificationError(
            f"sheet name '{name}' contains a character Excel forbids: [ ] : * ? / \\"
        )
    worksheet = workbook.active if is_first else workbook.create_sheet()
    worksheet.title = name
    headers = sheet_spec["headers"]
    worksheet.append(headers)
    for cell in worksheet[1]:
        cell.font = Font(bold=True)
        cell.fill = HEADER_FILL
    for row_number, row in enumerate(sheet_spec["rows"], start=1):
        if len(row) > len(headers):
            raise SpecificationError(
                f"sheet '{name}': row {row_number} has {len(row)} values but "
                f"there are only {len(headers)} headers"
            )
        worksheet.append(row)
    worksheet.freeze_panes = "A2"
    for column_index, header in enumerate(headers, start=1):
        longest = max(
            [len(str(header))]
            + [
                len(str(row[column_index - 1]))
                for row in sheet_spec["rows"]
                if column_index <= len(row) and row[column_index - 1] is not None
            ]
        )
        worksheet.column_dimensions[get_column_letter(column_index)].width = min(
            MAX_COLUMN_WIDTH, max(MIN_COLUMN_WIDTH, longest + 2)
        )


def _apply_patches(specification: dict[str, Any]) -> Workbook:
    workbook = load_workbook(specification["source_path"])
    for patch in specification["patches"]:
        sheet_name = patch["sheet"]
        if sheet_name not in workbook.sheetnames:
            raise SpecificationError(
                f"no sheet named '{sheet_name}'. Sheets: {workbook.sheetnames}"
            )
        if not _CELL_REFERENCE_PATTERN.match(patch["cell"]):
            raise SpecificationError(f"'{patch['cell']}' is not a cell such as B7")
        workbook[sheet_name][patch["cell"]] = patch["value"]
    return workbook


def _check(
    output_path: Path, specification: dict[str, Any], report: BuildReport
) -> None:
    reopened = load_workbook(str(output_path))
    formula_count = 0
    for sheet_spec in specification.get("sheets", []):
        worksheet = reopened[sheet_spec["name"]]
        expected_rows = len(sheet_spec["rows"]) + 1
        if worksheet.max_row != expected_rows:
            report.fail(
                f"sheet '{sheet_spec['name']}': expected {expected_rows} rows "
                f"including the header, found {worksheet.max_row}"
            )
        for row in worksheet.iter_rows():
            for cell in row:
                if isinstance(cell.value, str) and cell.value.startswith("="):
                    formula_count += 1
                    if cell.value.count("(") != cell.value.count(")"):
                        report.fail(
                            f"sheet '{sheet_spec['name']}' cell {cell.coordinate}: "
                            f"unbalanced brackets in formula {cell.value}"
                        )
    report.summary = f"{len(reopened.sheetnames)} sheets, {formula_count} formulas"


def build(specification: dict[str, Any], output_path: Path) -> BuildReport:
    """Build or patch the workbook, then check it."""
    report = BuildReport(output_path)
    if specification.get("patches"):
        workbook = _apply_patches(specification)
    else:
        sheet_names = [sheet["name"] for sheet in specification["sheets"]]
        if len(set(sheet_names)) != len(sheet_names):
            raise SpecificationError("sheet names must be unique")
        workbook = Workbook()
        for index, sheet_spec in enumerate(specification["sheets"]):
            _write_sheet(workbook, sheet_spec, is_first=index == 0)
    label_as_ai_assisted(workbook.properties, specification.get("model_id", ""))
    workbook.save(str(output_path))
    _check(output_path, specification, report)
    return report


if __name__ == "__main__":
    run_builder(build)
