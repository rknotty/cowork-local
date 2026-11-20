---
name: word-document
description: Write a Word document with the build_docx tool. Use when the user asks for a report, memo, letter, briefing or any .docx file.
allowed-tools: build_docx build_pdf extract_from_document
---

# Word document

Follow these steps in order.

1. `build_docx` and `build_pdf` are already available. You do not need `find_tool`.
2. If the user named a source file, call `extract_from_document` with it and an instruction for the facts you need. Use only facts from it or from the user's message.
3. If the purpose or the reader is unclear, call `ask_user` once. Otherwise continue.
4. Plan the headings first: 3 to 7 level-1 headings. Write them down before any paragraphs.
5. Call `build_docx` once with `path`, `title` and `blocks`. Use these block types:
   - `heading`: `text` and `level` (1 to 3).
   - `paragraph`: `text`. Keep each under 120 words.
   - `bullet_list` or `numbered_list`: `items`.
   - `table`: `headers` and `rows`. Every row has one cell per header.
6. If the tool reports failed checks, fix the specification and call `build_docx` again. Do this at most twice.
7. If the user wants a PDF, call `build_pdf` with the .docx as `source_path`.
8. Tell the user the file name and its headings.

## Checklist before calling build_docx

- [ ] `path` ends in `.docx`.
- [ ] Every heading in your plan appears as a `heading` block.
- [ ] No placeholder text such as TBC, XXX or lorem ipsum.
- [ ] British English spelling.
- [ ] Table rows match the header count.

## What the checks test

The file opens, every heading is present, the table count matches and there is no placeholder text.
