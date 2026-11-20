---
name: spreadsheet
description: Create an Excel workbook with the build_xlsx tool. Use when the user asks for a spreadsheet, tracker, budget, register or .xlsx file.
allowed-tools: build_xlsx extract_from_document
---

# Spreadsheet

Follow these steps in order.

1. `build_xlsx` is already available. You do not need `find_tool`. If the data is in a long file, call `extract_from_document` to pull out the rows you need.
2. Decide the columns. Put identifiers first, then values, then totals or status.
3. Call `build_xlsx` with `path` and `sheets`. Each sheet has `name`, `headers` and `rows`.
4. Write numbers as numbers, not text: `1200`, not `"1,200"`.
5. Write formulas as strings starting with `=`. Row 1 is the header, so data starts on row 2.
   Example: three data rows in column B are totalled with `=SUM(B2:B4)`.
6. If the tool reports failed checks, fix the specification and call `build_xlsx` again. Do this at most twice.
7. Tell the user the file name, the sheets and which cells hold formulas.

## Checklist before calling build_xlsx

- [ ] `path` ends in `.xlsx`.
- [ ] Sheet names are unique, at most 31 characters, and contain none of `[ ] : * ? / \`.
- [ ] No row has more values than there are headers.
- [ ] Every formula's brackets balance and its cell range points at data rows.
- [ ] Never invent figures. Use only numbers the user or a source file gave you.

## What the checks test

The file opens, each sheet has the expected row count and every formula has balanced brackets.
