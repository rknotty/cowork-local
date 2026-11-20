"""Append-only, hash-chained audit log (plan section 13, control 1).

One JSON line per model call and per tool call. Each record carries the hash
of the previous record, so editing or removing any line breaks every hash
after it and `verify_chain` reports where.

The log stores hashes of inputs and results, not the content itself: it is
evidence of what happened, not a second copy of the user's documents.
"""

from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from orchestrator.errors import AuditChainError

GENESIS_HASH = "0" * 64
AUDIT_FILE_NAME = "audit.jsonl"


def hash_content(content: object) -> str:
    """Return the SHA-256 of a JSON-serialisable object, stable across runs."""
    canonical = json.dumps(content, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class AuditRecord:
    """One audited event. `kind` is "model_call" or "tool_call"."""

    kind: str
    session_id: str
    model_id: str = ""
    role: str = ""
    input_hash: str = ""
    result_hash: str = ""
    tool_name: str = ""
    tool_arguments: dict[str, object] = field(default_factory=dict)
    tier: int | None = None
    approval_decision: str = ""
    outcome: str = "ok"
    error_code: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    duration_ms: int = 0


class AuditLog:
    """Writes audit records to `data/audit/audit.jsonl` and verifies the chain."""

    def __init__(self, audit_directory: Path) -> None:
        audit_directory.mkdir(parents=True, exist_ok=True)
        self._path = audit_directory / AUDIT_FILE_NAME
        # One generation runs at a time, but tool calls and the API can both
        # write, and a torn write would break the chain.
        self._lock = threading.Lock()
        self._last_hash = self._read_last_hash()

    @property
    def path(self) -> Path:
        """Location of the audit file."""
        return self._path

    def append(self, record: AuditRecord) -> str:
        """Append a record and return its hash."""
        with self._lock:
            entry: dict[str, object] = {
                "timestamp": datetime.now(UTC).isoformat(),
                **asdict(record),
                "previous_hash": self._last_hash,
            }
            entry_hash = hash_content(entry)
            entry["record_hash"] = entry_hash
            with self._path.open("a", encoding="utf-8") as audit_file:
                audit_file.write(json.dumps(entry, default=str) + "\n")
            self._last_hash = entry_hash
            return entry_hash

    def verify_chain(self) -> int:
        """Check every record against its predecessor.

        Returns:
            The number of records verified.

        Raises:
            AuditChainError: If any record was altered, removed or reordered.
        """
        expected_previous_hash = GENESIS_HASH
        record_count = 0
        if not self._path.exists():
            return 0
        with self._path.open(encoding="utf-8") as audit_file:
            for line_number, line in enumerate(audit_file, start=1):
                entry = json.loads(line)
                stored_hash = entry.pop("record_hash", "")
                if entry.get("previous_hash") != expected_previous_hash:
                    raise AuditChainError(
                        "previous_hash mismatch", line_number=line_number
                    )
                if hash_content(entry) != stored_hash:
                    raise AuditChainError(
                        "record_hash mismatch", line_number=line_number
                    )
                expected_previous_hash = stored_hash
                record_count += 1
        return record_count

    def _read_last_hash(self) -> str:
        if not self._path.exists():
            return GENESIS_HASH
        last_line = ""
        with self._path.open(encoding="utf-8") as audit_file:
            for line in audit_file:
                if line.strip():
                    last_line = line
        if not last_line:
            return GENESIS_HASH
        return str(json.loads(last_line)["record_hash"])
