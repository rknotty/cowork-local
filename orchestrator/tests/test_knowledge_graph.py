"""The index map: graph of files, and the access event from searches."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from fastapi.testclient import TestClient

from orchestrator.api import create_app
from orchestrator.bootstrap import Application
from orchestrator.events import AgentEvent, EventType
from orchestrator.knowledge.index import build_file_graph
from orchestrator.toolkit.context import ToolContext


def _vector(*values: float) -> bytes:
    return np.asarray(values, dtype=np.float32).tobytes()


def test_graph_links_similar_files_and_places_them_next_to_each_other() -> None:
    rows = [
        ("leave.md", _vector(1, 0, 0)),
        ("travel.md", _vector(0, 1, 0)),
        ("holiday.md", _vector(0.9, 0.1, 0)),
        ("rail.md", _vector(0.1, 0.9, 0)),
        ("rail.md", _vector(0, 1, 0.1)),
    ]

    graph = build_file_graph(rows, neighbour_count=1)

    order = [node["name"] for node in graph["nodes"]]
    assert abs(order.index("leave.md") - order.index("holiday.md")) == 1
    assert abs(order.index("travel.md") - order.index("rail.md")) == 1
    pairs = {(edge["source"], edge["target"]) for edge in graph["edges"]}
    assert ("holiday.md", "leave.md") in pairs
    assert ("rail.md", "travel.md") in pairs
    assert graph["file_count"] == 4
    assert graph["chunk_count"] == 5


def test_graph_drops_links_between_unrelated_files() -> None:
    rows = [("a.md", _vector(1, 0)), ("b.md", _vector(-1, 0))]

    graph = build_file_graph(rows)

    assert graph["edges"] == []


def test_empty_index_gives_an_empty_graph() -> None:
    assert build_file_graph([]) == {
        "nodes": [],
        "edges": [],
        "file_count": 0,
        "chunk_count": 0,
    }


async def test_search_announces_which_files_it_drew_from(
    application: Application,
    tool_context: ToolContext,
    emitted_events: list[AgentEvent],
) -> None:
    workspace = tool_context.allowlist.workspace
    (workspace / "leave.md").write_text("# Leave\n\nStaff get 27 days of annual leave.")
    (workspace / "travel.md").write_text("# Travel\n\nBook rail early.")
    await application.services.knowledge.index_folder(workspace)

    await application.router.execute(
        tool_context,
        "c1",
        "search_knowledge",
        json.dumps({"query": "annual leave days"}),
    )

    access = [
        event for event in emitted_events if event.type == EventType.KNOWLEDGE_ACCESS
    ]
    assert len(access) == 1
    assert access[0].payload["query"] == "annual leave days"
    files = access[0].payload["files"]
    assert files[0]["file_path"].endswith("leave.md")
    assert all(entry["passage_count"] >= 1 for entry in files)


def test_graph_endpoint_reflects_the_index(
    application: Application, tmp_path: Path
) -> None:
    folder = tmp_path / "documents"
    folder.mkdir()
    (folder / "a.md").write_text("# A\n\nAlpha content.")
    (folder / "b.md").write_text("# B\n\nBeta content.")

    with TestClient(create_app(application)) as client:
        before = client.get("/api/knowledge/graph").json()
        client.put("/api/folders", json={"folders": [str(folder)]})
        after = before
        for _ in range(100):
            after = client.get("/api/knowledge/graph").json()
            if after["file_count"] == 2:
                break

    assert before["file_count"] == 0
    assert after["file_count"] == 2
    assert {node["name"] for node in after["nodes"]} == {"a.md", "b.md"}
