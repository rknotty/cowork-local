"""Heading-aware chunking (plan section 12, knowledge step 2).

Split on headings, target 400 to 600 tokens with a 50-token overlap, and keep
the heading path with each chunk so a retrieved passage can be cited.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from orchestrator.context_budget import CHARACTERS_PER_TOKEN, estimate_tokens

TARGET_CHUNK_TOKENS = 500
MAX_CHUNK_TOKENS = 600
OVERLAP_TOKENS = 50
_HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")


@dataclass(frozen=True)
class Chunk:
    """A passage of one document."""

    heading_path: str
    text: str


def _split_sections(markdown_text: str) -> list[tuple[str, str]]:
    """Split into (heading path, body) sections."""
    sections: list[tuple[str, str]] = []
    heading_stack: list[tuple[int, str]] = []
    body_lines: list[str] = []

    def close_section() -> None:
        body = "\n".join(body_lines).strip()
        if body:
            path = " > ".join(title for _, title in heading_stack)
            sections.append((path, body))
        body_lines.clear()

    for line in markdown_text.splitlines():
        heading_match = _HEADING_PATTERN.match(line)
        if heading_match is None:
            body_lines.append(line)
            continue
        close_section()
        level = len(heading_match.group(1))
        while heading_stack and heading_stack[-1][0] >= level:
            heading_stack.pop()
        heading_stack.append((level, heading_match.group(2)))
    close_section()
    return sections


def split_text_windows(
    text: str, window_characters: int, overlap_characters: int
) -> list[str]:
    """Split text into overlapping windows, preferring sentence boundaries.

    Every character of the input appears in at least one window: nothing is
    dropped, however long a single paragraph is. Transcripts exported from
    meeting tools are often one paragraph of tens of thousands of characters.

    Args:
        text: The text to split.
        window_characters: Maximum length of each window.
        overlap_characters: How much each window repeats of the one before,
            so a sentence cut at a boundary is seen whole in one of them.
    """
    if len(text) <= window_characters:
        return [text]
    windows: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + window_characters, len(text))
        if end < len(text):
            end = _nearest_break_before(text, start, end)
        windows.append(text[start:end])
        if end >= len(text):
            break
        start = max(end - overlap_characters, start + 1)
    return windows


def _nearest_break_before(text: str, start: int, end: int) -> int:
    """Move a cut back to the end of a sentence or line, if one is close."""
    earliest_acceptable = start + (end - start) // 2
    for separator in ("\n", ". ", "? ", "! "):
        position = text.rfind(separator, earliest_acceptable, end)
        if position != -1:
            return position + len(separator)
    return end


def _split_long_section(body: str) -> list[str]:
    """Split a section on paragraph boundaries with an overlap between parts."""
    max_characters = MAX_CHUNK_TOKENS * CHARACTERS_PER_TOKEN
    overlap_characters = OVERLAP_TOKENS * CHARACTERS_PER_TOKEN
    paragraphs = [
        window
        for part in re.split(r"\n\s*\n", body)
        if part.strip()
        for window in split_text_windows(
            part.strip(), max_characters, overlap_characters
        )
    ]
    parts: list[str] = []
    current_paragraphs: list[str] = []
    current_tokens = 0
    for paragraph in paragraphs:
        paragraph_tokens = estimate_tokens(paragraph)
        if (
            current_paragraphs
            and current_tokens + paragraph_tokens > TARGET_CHUNK_TOKENS
        ):
            parts.append("\n\n".join(current_paragraphs))
            overlap_text = parts[-1][-OVERLAP_TOKENS * CHARACTERS_PER_TOKEN :]
            current_paragraphs = [overlap_text]
            current_tokens = OVERLAP_TOKENS
        current_paragraphs.append(paragraph)
        current_tokens += paragraph_tokens
    if current_paragraphs:
        parts.append("\n\n".join(current_paragraphs))
    return parts


def chunk_markdown(markdown_text: str) -> list[Chunk]:
    """Chunk a markdown document, keeping each chunk's heading path."""
    chunks: list[Chunk] = []
    for heading_path, body in _split_sections(markdown_text):
        if estimate_tokens(body) <= MAX_CHUNK_TOKENS:
            chunks.append(Chunk(heading_path, body))
            continue
        chunks.extend(Chunk(heading_path, part) for part in _split_long_section(body))
    return chunks
