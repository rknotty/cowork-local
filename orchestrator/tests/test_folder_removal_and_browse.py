"""Removing a folder removes its content; the folder dialog endpoint."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from orchestrator import api as api_module
from orchestrator.api import create_app
from orchestrator.bootstrap import Application
from orchestrator.knowledge.coordinator import IndexingCoordinator
from orchestrator.knowledge.index import KnowledgeIndex
from orchestrator.tests.conftest import ScriptedGateway


async def _embed(texts: list[str]) -> list[list[float]]:
    return (await ScriptedGateway().embed(texts)).vectors


def _make_folder(root: Path, name: str, file_count: int) -> Path:
    folder = root / name
    folder.mkdir()
    for number in range(file_count):
        (folder / f"note-{number}.md").write_text(f"# Note {number}\n\nAbout {name}.")
    return folder


async def test_retaining_folders_deletes_everything_else(tmp_path: Path) -> None:
    index = KnowledgeIndex(tmp_path / "k.sqlite", _embed)
    kept = _make_folder(tmp_path, "kept", 2)
    dropped = _make_folder(tmp_path, "kept-not", 3)
    await index.index_folder(kept)
    await index.index_folder(dropped)

    removed = index.retain_only_folders([str(kept.resolve())])

    assert removed == 3
    assert index.graph()["file_count"] == 2
    hits = await index.search("kept-not")
    assert all(str(kept.resolve()) in hit.file_path for hit in hits)
    index.close()


async def test_disconnect_cancels_a_run_in_progress_before_purging(
    tmp_path: Path,
) -> None:
    release_embedding = asyncio.Event()

    async def slow_embed(texts: list[str]) -> list[list[float]]:
        await release_embedding.wait()
        return await _embed(texts)

    index = KnowledgeIndex(tmp_path / "k.sqlite", slow_embed)
    folder = _make_folder(tmp_path, "busy", 5)
    coordinator = IndexingCoordinator(index)
    coordinator.start(folder.resolve())
    await asyncio.sleep(0.05)

    await coordinator.disconnect_others([])
    release_embedding.set()
    await asyncio.sleep(0.05)

    assert index.graph()["file_count"] == 0
    assert coordinator.status([]) == []
    index.close()


def test_removing_a_folder_empties_the_index_map(
    application: Application, tmp_path: Path
) -> None:
    folder = _make_folder(tmp_path, "documents", 2)

    with TestClient(create_app(application)) as client:
        client.put("/api/folders", json={"folders": [str(folder)]})
        for _ in range(100):
            if client.get("/api/knowledge/graph").json()["file_count"] == 2:
                break
        client.put("/api/folders", json={"folders": []})
        after_removal = client.get("/api/knowledge/graph").json()

    assert after_removal["file_count"] == 0
    assert after_removal["nodes"] == []


def test_startup_clears_content_of_folders_no_longer_connected(
    application: Application, tmp_path: Path
) -> None:
    folder = _make_folder(tmp_path, "stale", 2)
    asyncio.run(application.services.knowledge.index_folder(folder))
    assert application.services.knowledge.graph()["file_count"] == 2

    with TestClient(create_app(application)) as client:
        graph = client.get("/api/knowledge/graph").json()

    assert graph["file_count"] == 0


def test_browse_returns_the_folder_chosen_in_the_dialog(
    application: Application, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[Any] = []

    def fake_dialog(start_folder: str | None) -> str:
        calls.append(start_folder)
        return "C:\\Users\\example\\Documents\\Policies"

    monkeypatch.setattr(api_module, "choose_folder_with_dialog", fake_dialog)

    with TestClient(create_app(application)) as client:
        response = client.post(
            "/api/folders/browse", json={"start_folder": "C:\\Users"}
        )

    assert response.json() == {"folder": "C:\\Users\\example\\Documents\\Policies"}
    assert calls == ["C:\\Users"]


def test_browse_reports_a_cancelled_dialog_as_no_folder(
    application: Application, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(api_module, "choose_folder_with_dialog", lambda start: None)

    with TestClient(create_app(application)) as client:
        response = client.post("/api/folders/browse", json={})

    assert response.json() == {"folder": None}


def test_browse_refuses_a_plain_text_request_a_website_could_send(
    application: Application, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[Any] = []
    monkeypatch.setattr(
        api_module, "choose_folder_with_dialog", lambda start: calls.append(start)
    )

    with TestClient(create_app(application)) as client:
        response = client.post(
            "/api/folders/browse", content="{}", headers={"Content-Type": "text/plain"}
        )

    assert response.status_code == 422
    assert calls == []
