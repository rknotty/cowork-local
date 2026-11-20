---
name: meeting-actions
description: Turn meeting notes or a transcript into a short summary with decisions and actions. Use when the user shares meeting notes, minutes or a transcript and wants a summary, actions or follow-up.
allowed-tools: extract_from_document write_file
---

# Meeting actions

Follow these steps in order.

1. Find the notes. If the user named a file, use that path. If they pasted the notes, skip to step 4 and use the pasted text.
2. Call `extract_from_document` with the file path and this instruction: "List every decision, and every action with its owner and due date. List open questions separately." This reads the whole file, however long.
3. Read the findings it returns. They are your only source. Do not read the file again.
4. Write `meeting-summary.md` with `write_file`, using exactly these sections:
   - `## Summary`: at most five sentences.
   - `## Decisions`: a bullet list.
   - `## Actions`: a table with columns Owner, Action, Due.
   - `## Open questions`: a bullet list, or "None".
5. Reply with the file name, the number of decisions and the number of actions.

## Checklist

- [ ] Every action has an owner. If the findings give none, write "Not stated".
- [ ] Every action has a due date. If the findings give none, write "Not stated".
- [ ] No names, dates or figures that are not in the findings.
- [ ] No opinions about the people in the meeting.
- [ ] Leave out anything that looks like health or other sensitive personal information.
