---
name: slide-deck
description: Build a PowerPoint deck with the build_pptx tool. Use when the user asks for slides, a deck or a presentation, including turning notes or a document into slides.
allowed-tools: build_pptx extract_from_document
---

# Slide deck

Follow these steps in order.

1. `build_pptx` is already available. You do not need `find_tool`.
2. If the user named a source file, call `extract_from_document` with it and the instruction "List the main points, figures and decisions". Do not invent facts that are not in it.
3. Decide the slide count. If the user gave a number, use exactly that number. Otherwise use 5 to 8.
4. Plan one message per slide before you call the tool. Each slide makes one point.
5. Call `build_pptx` once with every slide. Choose a layout for each slide:
   - `title`: first slide. Needs `title`, optional `subtitle`.
   - `section`: a divider. Needs `title`.
   - `bullets`: the default. Needs `title` and `bullets`.
   - `two_column`: a comparison. Needs `left_bullets` and `right_bullets`.
   - `quote`: one quotation. Needs `quote`, optional `attribution`.
   - `table`: small tables only. Needs `headers` and `rows`.
   - `big_number`: one statistic. Needs `number`, optional `caption`.
   - `closing`: last slide. Needs `title`, optional `bullets`.
6. If the tool reports failed checks, fix the specification and call `build_pptx` again. Do this at most twice.
7. Tell the user the file name and the slide count. Mention any check that still fails.

## Checklist before calling build_pptx

- [ ] First slide uses `title`. Last slide uses `closing`.
- [ ] Slide count matches what the user asked for.
- [ ] No slide has more than 5 bullets.
- [ ] No bullet is longer than 12 words.
- [ ] Every title is under 8 words.
- [ ] Table rows have the same number of cells as there are headers.
- [ ] `path` ends in `.pptx`.

## What the checks test

The file opens, the slide count matches, no slide is empty, and no text overflows its box.
