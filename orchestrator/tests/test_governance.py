"""Audit chain, path allowlist and memory content rules."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from orchestrator.audit import AuditLog, AuditRecord
from orchestrator.errors import (
    AuditChainError,
    PathNotAllowedError,
    SensitiveContentError,
    ToolExecutionError,
)
from orchestrator.memory import MemoryStore
from orchestrator.paths import PathAllowlist


def _record(tool_name: str) -> AuditRecord:
    return AuditRecord(kind="tool_call", session_id="s1", tool_name=tool_name)


def test_audit_chain_verifies_when_untouched(tmp_path: Path) -> None:
    audit_log = AuditLog(tmp_path)
    for tool_name in ("read_file", "write_file", "list_dir"):
        audit_log.append(_record(tool_name))

    assert audit_log.verify_chain() == 3


def test_audit_chain_survives_reopening_the_log(tmp_path: Path) -> None:
    AuditLog(tmp_path).append(_record("read_file"))
    reopened_log = AuditLog(tmp_path)
    reopened_log.append(_record("write_file"))

    assert reopened_log.verify_chain() == 2


def test_audit_chain_detects_an_edited_record(tmp_path: Path) -> None:
    audit_log = AuditLog(tmp_path)
    audit_log.append(_record("read_file"))
    audit_log.append(_record("write_file"))
    lines = audit_log.path.read_text(encoding="utf-8").splitlines()
    tampered = json.loads(lines[0])
    tampered["tool_name"] = "remove_file"
    lines[0] = json.dumps(tampered)
    audit_log.path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(AuditChainError):
        audit_log.verify_chain()


def test_audit_chain_detects_a_removed_record(tmp_path: Path) -> None:
    audit_log = AuditLog(tmp_path)
    for tool_name in ("read_file", "write_file", "list_dir"):
        audit_log.append(_record(tool_name))
    lines = audit_log.path.read_text(encoding="utf-8").splitlines()
    audit_log.path.write_text("\n".join([lines[0], lines[2]]) + "\n", encoding="utf-8")

    with pytest.raises(AuditChainError):
        audit_log.verify_chain()


@pytest.fixture
def allowlist(tmp_path: Path) -> PathAllowlist:
    workspace = tmp_path / "workspace"
    connected = tmp_path / "connected"
    workspace.mkdir()
    connected.mkdir()
    return PathAllowlist(workspace, [connected])


def test_allowlist_resolves_relative_paths_inside_workspace(
    allowlist: PathAllowlist,
) -> None:
    resolved = allowlist.resolve_allowed("notes/summary.md")

    assert allowlist.is_inside_workspace(resolved)


def test_allowlist_accepts_connected_folder_but_not_as_workspace(
    allowlist: PathAllowlist, tmp_path: Path
) -> None:
    resolved = allowlist.resolve_allowed(str(tmp_path / "connected" / "a.txt"))

    assert not allowlist.is_inside_workspace(resolved)


@pytest.mark.parametrize("requested_path", ["", ".", "/", "\\", " / "])
def test_allowlist_treats_root_shorthands_as_the_workspace(
    allowlist: PathAllowlist, requested_path: str
) -> None:
    assert allowlist.resolve_allowed(requested_path) == allowlist.workspace


@pytest.mark.parametrize(
    "requested_path",
    [
        "../outside.txt",
        "..\\..\\outside.txt",
        "C:\\Users",
        "C:\\Windows\\win.ini",
        "C:\\",
        "/Windows",
    ],
)
def test_allowlist_refuses_paths_outside_allowed_roots(
    allowlist: PathAllowlist, requested_path: str
) -> None:
    with pytest.raises(PathNotAllowedError):
        allowlist.resolve_allowed(requested_path)


def test_allowlist_refuses_sibling_folder_sharing_a_name_prefix(
    allowlist: PathAllowlist, tmp_path: Path
) -> None:
    sibling = tmp_path / "workspace-other"
    sibling.mkdir()

    with pytest.raises(PathNotAllowedError):
        allowlist.resolve_allowed(str(sibling / "a.txt"))


def test_allowlist_refuses_symlink_that_escapes(
    allowlist: PathAllowlist, tmp_path: Path
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    link = allowlist.workspace / "link"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("creating symlinks needs a privilege this account lacks")

    with pytest.raises(PathNotAllowedError):
        allowlist.resolve_allowed("link/secret.txt")


@pytest.mark.parametrize(
    "content",
    [
        "the admin password: hunter2-example",
        "api_key=abcd1234abcd1234",
        "Authorization: Bearer abcdefghijklmnopqrstuvwxyz",
        "Sam was diagnosed last spring",
        "note her religion for the rota",
    ],
)
def test_memory_refuses_credentials_and_special_category_data(
    tmp_path: Path, content: str
) -> None:
    with pytest.raises(SensitiveContentError):
        MemoryStore(tmp_path).save("note", "a note", content)


def test_memory_saves_and_selects_by_relevance(tmp_path: Path) -> None:
    memory_store = MemoryStore(tmp_path)
    memory_store.save("profile", "who the user is", "Works in pre-sales.")
    memory_store.save(
        "harbour-tender", "Harbour council tender response", "Deadline is in March."
    )

    always_loaded = memory_store.select_for_prompt("what is the weather")
    with_project = memory_store.select_for_prompt("draft the harbour tender summary")

    assert [memory.name for memory in always_loaded] == ["profile"]
    assert {memory.name for memory in with_project} == {"profile", "harbour-tender"}


def test_memory_rejects_names_that_could_escape_the_folder(tmp_path: Path) -> None:
    with pytest.raises(ToolExecutionError):
        MemoryStore(tmp_path).save("../escape", "bad name", "content")


def test_memory_delete_reports_whether_a_file_existed(tmp_path: Path) -> None:
    memory_store = MemoryStore(tmp_path)
    memory_store.save("preferences", "style", "British English.")

    assert memory_store.delete("preferences") is True
    assert memory_store.delete("preferences") is False
