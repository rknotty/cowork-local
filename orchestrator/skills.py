"""Agent Skills index with progressive disclosure (plan section 10).

A skill is a folder with a `SKILL.md` at its root. The index advertises only
names and descriptions; the body is loaded when the model asks for it and
supporting files are read on demand. That matters more locally than in the
cloud because the context window is smaller.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from orchestrator.context_budget import estimate_tokens
from orchestrator.errors import PathNotAllowedError, SkillNotFoundError

logger = logging.getLogger(__name__)

SKILL_FILE_NAME = "SKILL.md"
MAX_DESCRIPTION_CHARACTERS = 1024
_SKILL_NAME_PATTERN = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
_FRONT_MATTER_PATTERN = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?(.*)\Z", re.DOTALL)


@dataclass(frozen=True)
class Skill:
    """One indexed skill."""

    name: str
    description: str
    folder: Path
    body: str
    # Agent Skills `allowed-tools`: tools made callable when the skill loads,
    # so its steps do not depend on the model discovering them first.
    allowed_tools: tuple[str, ...] = ()


def _parse_allowed_tools(raw_value: object) -> tuple[str, ...]:
    """Accept the spec's space-delimited string, or a YAML list."""
    if isinstance(raw_value, str):
        return tuple(raw_value.split())
    if isinstance(raw_value, list):
        return tuple(str(tool_name) for tool_name in raw_value)
    return ()


def _singular_words(text: str) -> str:
    """Lower-case, hyphens to spaces, trailing plural "s" removed per word.

    Lets "meeting-action skill" find the skill named "meeting-actions".
    """
    words = re.findall(r"[a-z0-9]+", text.lower().replace("-", " "))
    return " ".join(
        word[:-1] if len(word) > 3 and word.endswith("s") else word for word in words
    )


def parse_front_matter(document_text: str) -> tuple[dict[str, object], str]:
    """Split a markdown document into YAML front matter and body.

    Returns:
        The front matter mapping (empty if absent or invalid) and the body.
    """
    match = _FRONT_MATTER_PATTERN.match(document_text)
    if match is None:
        return {}, document_text
    try:
        front_matter = yaml.safe_load(match.group(1))
    except yaml.YAMLError:
        return {}, match.group(2)
    return (front_matter if isinstance(front_matter, dict) else {}), match.group(2)


def _validate_skill(folder: Path) -> Skill | None:
    """Parse one skill folder. Returns None, with a warning, if it is invalid."""
    skill_file = folder / SKILL_FILE_NAME
    front_matter, body = parse_front_matter(skill_file.read_text(encoding="utf-8"))
    name = str(front_matter.get("name", ""))
    description = str(front_matter.get("description", "")).strip()
    rejection_reason = ""
    if not _SKILL_NAME_PATTERN.match(name):
        rejection_reason = "name must be lowercase words joined by hyphens"
    elif name != folder.name:
        rejection_reason = "name must match the folder name"
    elif not description or len(description) > MAX_DESCRIPTION_CHARACTERS:
        rejection_reason = "description must be 1 to 1024 characters"
    if rejection_reason:
        logger.warning(
            "Skill rejected: front matter failed validation",
            extra={"skill_folder": folder.name, "rejection_reason": rejection_reason},
        )
        return None
    return Skill(
        name=name,
        description=description,
        folder=folder,
        body=body.strip(),
        allowed_tools=_parse_allowed_tools(front_matter.get("allowed-tools")),
    )


class SkillIndex:
    """Skills discovered under the skills directory at start-up."""

    def __init__(self, skills_directory: Path) -> None:
        self._skills: dict[str, Skill] = {}
        if not skills_directory.is_dir():
            return
        for folder in sorted(skills_directory.iterdir()):
            if (folder / SKILL_FILE_NAME).is_file():
                skill = _validate_skill(folder)
                if skill is not None:
                    self._skills[skill.name] = skill
        logger.info("Skill index built", extra={"skill_count": len(self._skills)})

    def all_skills(self) -> list[Skill]:
        """Every valid skill, by name."""
        return list(self._skills.values())

    def find_referenced(self, user_text: str) -> list[Skill]:
        """Skills the user asked for by name in a message.

        A skill counts as asked for when the message contains `/skill-name`,
        or names the skill (hyphens and plurals ignored) and uses the word
        "skill". Requiring the word stops a passing mention of, say,
        "spreadsheet" from forcing the spreadsheet skill.
        """
        lowered = user_text.lower()
        normalised = f" {_singular_words(user_text)} "
        mentions_skill_word = " skill " in normalised
        referenced = []
        for skill in self._skills.values():
            is_slash_command = f"/{skill.name}" in lowered
            is_named = f" {_singular_words(skill.name)} " in normalised
            if is_slash_command or (is_named and mentions_skill_word):
                referenced.append(skill)
        return referenced

    def get(self, name: str) -> Skill:
        """Fetch a skill by name.

        Raises:
            SkillNotFoundError: Carrying the valid names.
        """
        skill = self._skills.get(name)
        if skill is None:
            raise SkillNotFoundError(
                f"no skill named '{name}'. Valid skills: {sorted(self._skills)}"
            )
        return skill

    def render_index(self, max_tokens: int) -> str:
        """Names and one-line descriptions, cut off at the token budget."""
        lines: list[str] = []
        used_tokens = 0
        for skill in self._skills.values():
            first_sentence = skill.description.split(". ")[0].rstrip(".")
            line = f"- {skill.name}: {first_sentence}."
            line_tokens = estimate_tokens(line)
            if used_tokens + line_tokens > max_tokens:
                logger.warning(
                    "Skill index exceeds its token budget; later skills omitted",
                    extra={"advertised_count": len(lines)},
                )
                break
            lines.append(line)
            used_tokens += line_tokens
        return "\n".join(lines)

    def read_reference_file(self, name: str, relative_path: str) -> str:
        """Read a supporting file from inside a skill folder.

        Raises:
            SkillNotFoundError: If the skill does not exist.
            PathNotAllowedError: If the path leaves the skill folder.
        """
        skill_folder = self.get(name).folder.resolve()
        canonical_path = (skill_folder / relative_path).resolve()
        if skill_folder not in canonical_path.parents:
            raise PathNotAllowedError(
                "path leaves the skill folder", requested_path=relative_path
            )
        if not canonical_path.is_file():
            raise SkillNotFoundError(f"no file '{relative_path}' in skill '{name}'")
        return canonical_path.read_text(encoding="utf-8", errors="replace")
