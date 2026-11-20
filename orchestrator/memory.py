"""Memory: a small set of markdown files loaded into sessions (plan section 12).

Plain files so they are human-readable, editable and diffable. Profile and
preferences load into every system prompt; project files load only when the
conversation matches their one-line description.

Memory is written deliberately, through `save_memory`, never automatically:
a small model filing memories in the background files noise.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from orchestrator.errors import SensitiveContentError, ToolExecutionError
from orchestrator.skills import parse_front_matter

ALWAYS_LOADED_NAMES = ("profile", "preferences")
_MEMORY_NAME_PATTERN = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
MINIMUM_MATCHING_TERMS = 2
_STOP_WORDS = frozenset(
    [
        "the",
        "and",
        "for",
        "with",
        "that",
        "this",
        "from",
        "have",
        "about",
        "into",
        "your",
        "their",
        "work",
        "project",
    ]
)

# Hardcoded on purpose (plan section 12, memory step 5): this rule must not be
# switchable from configuration or by the model. Heuristic, so it errs towards
# refusing; the user can still write the file by hand if a refusal is wrong.
_CREDENTIAL_PATTERNS = (
    re.compile(r"(?i)\b(password|passwd|pwd|secret|api[_ -]?key|token)\b\s*[:=]\s*\S+"),
    re.compile(r"(?i)\bbearer\s+[a-z0-9._\-]{16,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?i)\b(AccountKey|SharedAccessKey)\s*=\s*\S+"),
    re.compile(r"\b(sk|pk|ghp|gho|xox[bap])[-_][A-Za-z0-9_\-]{16,}"),
)
_SPECIAL_CATEGORY_PATTERN = re.compile(
    r"(?i)\b(diagnos\w*|medication|medical condition|health condition|"
    r"mental health|disabilit\w+|pregnan\w+|religio\w+|ethnic\w+|"
    r"sexual orientation|trade union|political (opinion|affiliation)|"
    r"biometric|genetic|criminal (record|conviction))\b"
)


@dataclass(frozen=True)
class MemoryFile:
    """One memory file."""

    name: str
    description: str
    content: str


def assert_content_is_storable(content: str) -> None:
    """Refuse credentials and special category personal data.

    Raises:
        SensitiveContentError: Naming the category, never echoing the content.
    """
    if any(pattern.search(content) for pattern in _CREDENTIAL_PATTERNS):
        raise SensitiveContentError("content looks like a credential or secret")
    if _SPECIAL_CATEGORY_PATTERN.search(content):
        raise SensitiveContentError(
            "content looks like health or other special category personal data"
        )


class MemoryStore:
    """Reads and writes the memory folder."""

    def __init__(self, memory_directory: Path) -> None:
        self._directory = memory_directory
        self._directory.mkdir(parents=True, exist_ok=True)

    def list_files(self) -> list[MemoryFile]:
        """Every memory file, by name."""
        memory_files = []
        for path in sorted(self._directory.glob("*.md")):
            front_matter, body = parse_front_matter(path.read_text(encoding="utf-8"))
            memory_files.append(
                MemoryFile(
                    name=path.stem,
                    description=str(front_matter.get("description", "")),
                    content=body.strip(),
                )
            )
        return memory_files

    def save(self, name: str, description: str, content: str) -> None:
        """Create or replace a memory file.

        Raises:
            ToolExecutionError: If the name is not lowercase-hyphenated.
            SensitiveContentError: If the content must not be stored.
        """
        if not _MEMORY_NAME_PATTERN.match(name):
            raise ToolExecutionError(
                "memory name must be lowercase words joined by hyphens"
            )
        assert_content_is_storable(f"{description}\n{content}")
        single_line_description = " ".join(description.split())
        document = (
            f"---\ndescription: {single_line_description!r}\n---\n\n{content.strip()}\n"
        )
        (self._directory / f"{name}.md").write_text(document, encoding="utf-8")

    def delete(self, name: str) -> bool:
        """Delete a memory file. Returns False if it did not exist.

        This is the user's own inspect-and-delete action from the memory page,
        not a tool: the model cannot call it.
        """
        if not _MEMORY_NAME_PATTERN.match(name):
            return False
        path = self._directory / f"{name}.md"
        if not path.is_file():
            return False
        path.unlink()
        return True

    def select_for_prompt(self, conversation_text: str) -> list[MemoryFile]:
        """Profile and preferences always; project files only when relevant."""
        conversation_terms = _significant_terms(conversation_text)
        selected = []
        for memory_file in self.list_files():
            if memory_file.name in ALWAYS_LOADED_NAMES:
                selected.append(memory_file)
                continue
            description_terms = _significant_terms(
                f"{memory_file.name.replace('-', ' ')} {memory_file.description}"
            )
            if len(description_terms & conversation_terms) >= MINIMUM_MATCHING_TERMS:
                selected.append(memory_file)
        return selected


def _significant_terms(text: str) -> set[str]:
    return {
        term
        for term in re.findall(r"[a-z0-9]{4,}", text.lower())
        if term not in _STOP_WORDS
    }
