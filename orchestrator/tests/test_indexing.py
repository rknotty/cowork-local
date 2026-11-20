"""Background indexing: progress, skipped files, failures and the API."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from orchestrator.api import create_app
from orchestrator.bootstrap import Application
from orchestrator.errors import GatewayUnavailableError
from orchestrator.knowledge import index as index_module
from orchestrator.knowledge.coordinator import IndexingCoordinator
from orchestrator.knowledge.index import (
    ONLINE_ONLY_ATTRIBUTES,
    IndexingProgress,
    KnowledgeIndex,
    is_online_only,
)
from orchestrator.tests.conftest import ScriptedGateway


async def _embed(texts: list[str]) -> list[list[float]]:
    return (await ScriptedGateway().embed(texts)).vectors


@pytest.fixture
def knowledge_index(tmp_path: Path) -> KnowledgeIndex:
    return KnowledgeIndex(tmp_path / "knowledge.sqlite", _embed)


@pytest.fixture
def documents(tmp_path: Path) -> Path:
    folder = tmp_path / "documents"
    folder.mkdir()
    (folder / "leave.md").write_text("# Leave\n\nStaff get 27 days.")
    (folder / "travel.md").write_text("# Travel\n\nBook rail early.")
    (folder / "image.png").write_bytes(b"not indexed")
    return folder


async def test_progress_counts_every_file_and_ends_done(
    knowledge_index: KnowledgeIndex, documents: Path
) -> None:
    progress = await knowledge_index.index_folder(documents)

    assert progress.state == "done"
    assert progress.total_file_count == 2
    assert progress.processed_file_count == 2
    assert progress.indexed_file_count == 2
    assert progress.finished_at


async def test_each_indexed_file_is_logged_with_its_timings(
    knowledge_index: KnowledgeIndex,
    documents: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level("INFO", logger="orchestrator.knowledge.index")

    await knowledge_index.index_folder(documents)

    file_records = [r for r in caplog.records if r.getMessage() == "File indexed"]
    assert len(file_records) == 2
    record = file_records[0].__dict__
    assert record["file_type"] == ".md"
    assert record["chunk_count"] == 1
    assert {"parse_ms", "embed_ms", "duration_ms", "size_bytes"} <= record.keys()
    messages = [r.getMessage() for r in caplog.records]
    assert "Knowledge folder indexing started" in messages


async def test_unreadable_file_is_recorded_and_the_run_continues(
    knowledge_index: KnowledgeIndex, documents: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_hash = index_module._hash_file

    def failing_hash(path: Path) -> str:
        if path.name == "leave.md":
            raise OSError(22, "Invalid argument")
        return real_hash(path)

    monkeypatch.setattr(index_module, "_hash_file", failing_hash)

    progress = await knowledge_index.index_folder(documents)

    assert progress.state == "done"
    assert progress.failed_file_count == 1
    assert progress.failures == ["leave.md: Invalid argument"]
    assert progress.indexed_file_count == 1


async def test_online_only_placeholders_are_skipped_without_being_opened(
    knowledge_index: KnowledgeIndex, documents: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    opened: list[str] = []
    real_hash = index_module._hash_file

    def recording_hash(path: Path) -> str:
        opened.append(path.name)
        return real_hash(path)

    monkeypatch.setattr(index_module, "_hash_file", recording_hash)
    placeholder_inode = (documents / "travel.md").stat().st_ino
    monkeypatch.setattr(
        index_module,
        "is_online_only",
        lambda stat_result: stat_result.st_ino == placeholder_inode,
    )

    progress = await knowledge_index.index_folder(documents)

    assert progress.skipped_online_only_count == 1
    assert opened == ["leave.md"]


@pytest.mark.parametrize(
    ("attributes", "expected"), [(0, False), (ONLINE_ONLY_ATTRIBUTES, True)]
)
def test_online_only_detection_reads_file_attributes(
    attributes: int, expected: bool
) -> None:
    class FakeStat:
        st_file_attributes = attributes

    assert is_online_only(FakeStat()) is expected  # type: ignore[arg-type]


async def test_removal_does_not_touch_a_sibling_folder_sharing_a_prefix(
    knowledge_index: KnowledgeIndex, tmp_path: Path
) -> None:
    files_folder = tmp_path / "Files"
    sibling_folder = tmp_path / "Files 2"
    for folder in (files_folder, sibling_folder):
        folder.mkdir()
        (folder / "note.md").write_text(f"# Note\n\nIn {folder.name}.")
    await knowledge_index.index_folder(sibling_folder)

    progress = await knowledge_index.index_folder(files_folder)

    assert progress.removed_file_count == 0
    assert knowledge_index.chunk_total() == 2


async def _wait_for_finish(
    coordinator: IndexingCoordinator, folder: str
) -> dict[str, Any]:
    for _ in range(200):
        status = coordinator.status([folder])[0]
        if status["state"] in ("done", "failed"):
            return status
        await asyncio.sleep(0.01)
    raise AssertionError("indexing did not finish")


async def test_coordinator_reports_not_indexed_then_done(
    knowledge_index: KnowledgeIndex, documents: Path
) -> None:
    coordinator = IndexingCoordinator(knowledge_index)

    before = coordinator.status([str(documents)])[0]
    coordinator.start(documents)
    after = await _wait_for_finish(coordinator, str(documents))

    assert before == {"folder": str(documents), "state": "not_indexed"}
    assert after["indexed_file_count"] == 2


async def test_coordinator_records_a_failed_run_instead_of_losing_it(
    tmp_path: Path, documents: Path
) -> None:
    async def failing_embed(texts: list[str]) -> list[list[float]]:
        raise GatewayUnavailableError("embedding call failed")

    coordinator = IndexingCoordinator(
        KnowledgeIndex(tmp_path / "k.sqlite", failing_embed)
    )

    coordinator.start(documents)
    status = await _wait_for_finish(coordinator, str(documents))

    assert status["state"] == "failed"
    assert status["error_message"] == "The local model service is not available."


def test_api_starts_indexing_and_reports_status(
    application: Application, documents: Path
) -> None:
    with TestClient(create_app(application)) as client:
        client.put("/api/folders", json={"folders": [str(documents)]})
        statuses: list[dict[str, Any]] = []
        for _ in range(100):
            statuses = client.get("/api/knowledge/status").json()
            if statuses[0]["state"] == "done":
                break

    assert statuses[0]["folder"] == os.path.realpath(documents)
    assert statuses[0]["state"] == "done"
    assert statuses[0]["indexed_file_count"] == 2


def test_progress_failures_list_is_capped() -> None:
    progress = IndexingProgress(folder="x")

    for number in range(50):
        progress.record_failure(f"file{number}.md", "unreadable")

    assert progress.failed_file_count == 50
    assert len(progress.failures) == 20
