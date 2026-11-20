"""Skill index, chunking, the knowledge index and the document builders."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from orchestrator.context_budget import estimate_tokens
from orchestrator.errors import PathNotAllowedError, SkillNotFoundError
from orchestrator.knowledge.chunking import MAX_CHUNK_TOKENS, chunk_markdown
from orchestrator.knowledge.index import KnowledgeIndex, reciprocal_rank_fusion
from orchestrator.settings import REPOSITORY_ROOT
from orchestrator.skills import SkillIndex
from orchestrator.tests.conftest import ScriptedGateway

BUILDERS_DIRECTORY = REPOSITORY_ROOT / "tools"


def _write_skill(skills_directory: Path, folder_name: str, front_matter: str) -> None:
    folder = skills_directory / folder_name
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text(
        f"---\n{front_matter}\n---\n\n1. Do the thing.\n", encoding="utf-8"
    )
    (folder / "reference.md").write_text("reference text", encoding="utf-8")


@pytest.fixture
def skill_index(tmp_path: Path) -> SkillIndex:
    _write_skill(
        tmp_path,
        "meeting-notes",
        "name: meeting-notes\ndescription: Turn notes into actions. Use for minutes.",
    )
    _write_skill(tmp_path, "bad-name", "name: Wrong Name\ndescription: Invalid.")
    _write_skill(tmp_path, "no-description", "name: no-description")
    return SkillIndex(tmp_path)


def test_skill_index_rejects_invalid_front_matter(skill_index: SkillIndex) -> None:
    assert [skill.name for skill in skill_index.all_skills()] == ["meeting-notes"]


def test_skill_index_advertises_first_sentence_only(skill_index: SkillIndex) -> None:
    assert skill_index.render_index(800) == "- meeting-notes: Turn notes into actions."


def test_skill_index_respects_its_token_budget(skill_index: SkillIndex) -> None:
    assert skill_index.render_index(1) == ""


def test_unknown_skill_names_the_valid_ones(skill_index: SkillIndex) -> None:
    with pytest.raises(SkillNotFoundError, match="meeting-notes"):
        skill_index.get("missing")


def test_skill_reference_file_is_confined_to_the_skill_folder(
    skill_index: SkillIndex,
) -> None:
    assert (
        skill_index.read_reference_file("meeting-notes", "reference.md")
        == "reference text"
    )
    with pytest.raises(PathNotAllowedError):
        skill_index.read_reference_file("meeting-notes", "../bad-name/SKILL.md")


def test_chunks_carry_their_heading_path() -> None:
    markdown_text = "# Policy\n\nIntro.\n\n## Leave\n\nTwenty-five days.\n\n## Travel\n\nBook early."

    chunks = chunk_markdown(markdown_text)

    assert [chunk.heading_path for chunk in chunks] == [
        "Policy",
        "Policy > Leave",
        "Policy > Travel",
    ]


def test_long_sections_are_split_under_the_maximum_size() -> None:
    paragraphs = "\n\n".join(
        f"Paragraph {number}. " + "word " * 120 for number in range(12)
    )

    chunks = chunk_markdown(f"# Long\n\n{paragraphs}")

    assert len(chunks) > 1
    assert all(estimate_tokens(chunk.text) <= MAX_CHUNK_TOKENS for chunk in chunks)


def test_reciprocal_rank_fusion_prefers_items_ranked_by_both() -> None:
    fused = reciprocal_rank_fusion([[1, 2, 3], [3, 4, 1]])

    assert [chunk_id for chunk_id, _ in fused][:2] == [1, 3]


@pytest.fixture
async def knowledge_index(tmp_path: Path) -> KnowledgeIndex:
    gateway = ScriptedGateway()

    async def embed(texts: list[str]) -> list[list[float]]:
        return (await gateway.embed(texts)).vectors

    return KnowledgeIndex(tmp_path / "knowledge.sqlite", embed)


async def test_index_finds_the_right_source_and_tracks_changes(
    knowledge_index: KnowledgeIndex, tmp_path: Path
) -> None:
    folder = tmp_path / "documents"
    folder.mkdir()
    (folder / "leave.md").write_text(
        "# Leave\n\nStaff receive 25 days of annual leave."
    )
    (folder / "travel.md").write_text(
        "# Travel\n\nRail tickets must be booked in advance."
    )

    first_report = await knowledge_index.index_folder(folder)
    hits = await knowledge_index.search("how many days of annual leave")
    second_report = await knowledge_index.index_folder(folder)
    (folder / "travel.md").unlink()
    third_report = await knowledge_index.index_folder(folder)

    assert first_report.indexed_file_count == 2
    assert hits[0].file_path.endswith("leave.md")
    assert hits[0].heading_path == "Leave"
    assert second_report.unchanged_file_count == 2
    assert second_report.indexed_file_count == 0
    assert third_report.removed_file_count == 1
    assert knowledge_index.chunk_total() == 1
    knowledge_index.close()


def _run_builder(
    script_name: str, specification: dict[str, Any], output_path: Path
) -> dict[str, Any]:
    specification_path = output_path.with_suffix(".json")
    specification_path.write_text(json.dumps(specification), encoding="utf-8")
    completed = subprocess.run(
        [
            sys.executable,
            str(BUILDERS_DIRECTORY / script_name),
            str(specification_path),
            str(output_path),
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    report: dict[str, Any] = json.loads(completed.stdout.strip().splitlines()[-1])
    return report


def test_build_docx_produces_a_labelled_document_that_passes_checks(
    tmp_path: Path,
) -> None:
    import docx

    output_path = tmp_path / "report.docx"
    report = _run_builder(
        "build_docx.py",
        {
            "path": "report.docx",
            "title": "Quarterly review",
            "model_id": "fake-model:1",
            "blocks": [
                {"type": "heading", "level": 1, "text": "Summary"},
                {"type": "paragraph", "text": "Revenue grew."},
                {"type": "bullet_list", "items": ["One", "Two"]},
                {
                    "type": "table",
                    "headers": ["Area", "Status"],
                    "rows": [["Cloud", "Green"]],
                },
            ],
        },
        output_path,
    )

    assert report["is_valid"] is True
    reopened = docx.Document(str(output_path))
    assert "AI-assisted" in reopened.core_properties.comments
    assert "fake-model:1" in reopened.core_properties.comments


def test_build_docx_reports_a_ragged_table_in_words_the_model_can_act_on(
    tmp_path: Path,
) -> None:
    report = _run_builder(
        "build_docx.py",
        {
            "path": "bad.docx",
            "title": "Bad",
            "blocks": [
                {"type": "table", "headers": ["A", "B"], "rows": [["only one"]]}
            ],
        },
        tmp_path / "bad.docx",
    )

    assert report["is_valid"] is False
    assert "row 1 has 1 cells but there are 2 headers" in report["failures"][0]


def test_build_pptx_builds_every_layout_with_the_expected_slide_count(
    tmp_path: Path,
) -> None:
    from pptx import Presentation

    output_path = tmp_path / "deck.pptx"
    slides = [
        {"layout": "title", "title": "Project update", "subtitle": "November"},
        {"layout": "section", "title": "Progress"},
        {
            "layout": "bullets",
            "title": "Done",
            "bullets": ["Built", "Tested"],
            "notes": "Say this.",
        },
        {
            "layout": "two_column",
            "title": "Compare",
            "left_bullets": ["A"],
            "right_bullets": ["B"],
        },
        {
            "layout": "quote",
            "title": "Feedback",
            "quote": "It works.",
            "attribution": "A user",
        },
        {
            "layout": "table",
            "title": "Status",
            "headers": ["Item", "RAG"],
            "rows": [["API", "Green"]],
        },
        {
            "layout": "big_number",
            "title": "Coverage",
            "number": "87%",
            "caption": "of lines",
        },
        {"layout": "closing", "title": "Next steps", "bullets": ["Review"]},
    ]

    report = _run_builder(
        "build_pptx.py", {"path": "deck.pptx", "slides": slides}, output_path
    )

    assert report["is_valid"] is True, report["failures"]
    assert len(Presentation(str(output_path)).slides) == 8


def test_build_pptx_reports_text_that_overflows_its_box(tmp_path: Path) -> None:
    long_bullets = ["This bullet is far too long for one slide. " * 3] * 6

    report = _run_builder(
        "build_pptx.py",
        {
            "path": "o.pptx",
            "slides": [
                {"layout": "bullets", "title": "Too much", "bullets": long_bullets}
            ],
        },
        tmp_path / "o.pptx",
    )

    assert report["is_valid"] is False
    assert "overflows" in report["failures"][0]


def test_build_xlsx_writes_formulas_and_flags_unbalanced_ones(tmp_path: Path) -> None:
    from openpyxl import load_workbook

    output_path = tmp_path / "budget.xlsx"
    report = _run_builder(
        "build_xlsx.py",
        {
            "path": "budget.xlsx",
            "sheets": [
                {
                    "name": "Budget",
                    "headers": ["Item", "Cost"],
                    "rows": [
                        ["Licences", 1200],
                        ["Support", 800],
                        ["Total", "=SUM(B2:B3)"],
                        ["Bad", "=SUM(B2:B3"],
                    ],
                }
            ],
        },
        output_path,
    )

    assert load_workbook(str(output_path))["Budget"]["B4"].value == "=SUM(B2:B3)"
    assert report["is_valid"] is False
    assert "B5" in report["failures"][0]


def test_patch_mode_writes_a_new_file_and_leaves_the_original(tmp_path: Path) -> None:
    import docx

    original_path = tmp_path / "original.docx"
    _run_builder(
        "build_docx.py",
        {
            "path": "original.docx",
            "title": "Draft",
            "blocks": [{"type": "paragraph", "text": "Old text."}],
        },
        original_path,
    )
    patched_path = tmp_path / "patched.docx"

    report = _run_builder(
        "build_docx.py",
        {
            "source_path": str(original_path),
            "patches": [{"paragraph": 1, "text": "New text."}],
        },
        patched_path,
    )

    assert report["is_valid"] is True
    assert docx.Document(str(original_path)).paragraphs[1].text == "Old text."
    assert docx.Document(str(patched_path)).paragraphs[1].text == "New text."
