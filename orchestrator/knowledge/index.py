"""The knowledge index: one SQLite file with FTS5 keywords and vectors.

Retrieval runs keyword and vector search together and merges them with
reciprocal rank fusion (plan section 12, knowledge step 5).

Vectors are stored as float32 blobs and searched by brute-force cosine in
NumPy rather than through the sqlite-vec extension. The plan allows this
below about 100,000 chunks, and it removes an Arm64 Windows native extension
from the dependency list.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
import sqlite3
import stat
import threading
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from orchestrator.knowledge.chunking import chunk_markdown
from orchestrator.knowledge.parsing import SUPPORTED_SUFFIXES, parse_document
from orchestrator.paths import TO_DELETE_FOLDER_NAME

logger = logging.getLogger(__name__)

TOP_RESULTS = 6
CANDIDATES_PER_SEARCH = 20
# Standard constant from the reciprocal rank fusion paper; dampens the
# influence of any single ranker's top result.
RRF_CONSTANT = 60
MAX_INDEXED_FILE_BYTES = 20_000_000
IGNORED_FOLDER_NAMES = {TO_DELETE_FOLDER_NAME, ".git", "node_modules", ".venv"}
MAX_REPORTED_FAILURES = 20
PROGRESS_LOG_INTERVAL_FILES = 25
# A file taking longer than this is worth a warning: it is usually a very
# large PDF or spreadsheet, and explains an indexing run that looks stalled.
SLOW_FILE_SECONDS = 30
# Index map: each file links to its three nearest files, provided they are at
# least loosely related. Below 0.2 cosine the link is noise, not structure.
GRAPH_NEIGHBOUR_COUNT = 3
GRAPH_MIN_SIMILARITY = 0.2
# Windows attributes on cloud placeholders (OneDrive "online-only" files).
ONLINE_ONLY_ATTRIBUTES = (
    getattr(stat, "FILE_ATTRIBUTE_OFFLINE", 0x1000)
    | getattr(stat, "FILE_ATTRIBUTE_RECALL_ON_OPEN", 0x40000)
    | getattr(stat, "FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS", 0x400000)
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS source_file (
    file_path TEXT PRIMARY KEY,
    content_hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS chunk (
    chunk_id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path TEXT NOT NULL,
    heading_path TEXT NOT NULL,
    chunk_text TEXT NOT NULL,
    embedding BLOB
);
CREATE INDEX IF NOT EXISTS chunk_file_idx ON chunk(file_path);
CREATE VIRTUAL TABLE IF NOT EXISTS chunk_fts USING fts5(
    chunk_text, heading_path, content='chunk', content_rowid='chunk_id'
);
"""

EmbedFunction = Callable[[list[str]], Awaitable[list[list[float]]]]


@dataclass(frozen=True)
class SearchHit:
    """One retrieved passage with its citation."""

    file_path: str
    heading_path: str
    text: str
    score: float


@dataclass
class IndexingProgress:
    """Live state of one folder's indexing run, read by the API while it runs.

    `state` moves scanning -> indexing -> done, or to failed if the whole run
    stops. A file that cannot be read is counted in `failed_file_count` and
    the run carries on.
    """

    folder: str
    state: str = "scanning"
    total_file_count: int = 0
    processed_file_count: int = 0
    indexed_file_count: int = 0
    unchanged_file_count: int = 0
    skipped_online_only_count: int = 0
    failed_file_count: int = 0
    removed_file_count: int = 0
    chunk_count: int = 0
    failures: list[str] = field(default_factory=list)
    error_message: str = ""
    started_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    finished_at: str = ""

    def record_failure(self, name: str, reason: str) -> None:
        """Count a skipped file and keep a short, capped list of reasons."""
        self.failed_file_count += 1
        if len(self.failures) < MAX_REPORTED_FAILURES:
            self.failures.append(f"{name}: {reason}")


def _log_progress(progress: IndexingProgress) -> None:
    logger.info(
        "Knowledge folder indexing progress",
        extra={
            "processed_file_count": progress.processed_file_count,
            "total_file_count": progress.total_file_count,
            "indexed_file_count": progress.indexed_file_count,
            "unchanged_file_count": progress.unchanged_file_count,
            "skipped_online_only_count": progress.skipped_online_only_count,
            "failed_file_count": progress.failed_file_count,
            "chunk_count": progress.chunk_count,
        },
    )


def _log_file_indexed(
    path: Path,
    size_bytes: int,
    chunk_count: int,
    started_at: float,
    parsed_at: float,
) -> None:
    """One line per indexed file, so a slow or stuck run can be pinned down.

    The file name is logged because the log stays on this device beside the
    index, which already holds the file's content.
    """
    finished_at = time.monotonic()
    duration_ms = int((finished_at - started_at) * 1000)
    is_slow = duration_ms >= SLOW_FILE_SECONDS * 1000
    logger.log(
        logging.WARNING if is_slow else logging.INFO,
        "Slow file indexed" if is_slow else "File indexed",
        extra={
            "file_name": path.name,
            "file_type": path.suffix.lower(),
            "size_bytes": size_bytes,
            "chunk_count": chunk_count,
            "parse_ms": int((parsed_at - started_at) * 1000),
            "embed_ms": int((finished_at - parsed_at) * 1000),
            "duration_ms": duration_ms,
        },
    )


def is_online_only(stat_result: os.stat_result) -> bool:
    """True for a OneDrive or similar cloud placeholder not stored locally.

    Opening such a file makes the sync client download it: network activity
    the assistant promises not to cause, so these files are skipped.
    """
    attributes = getattr(stat_result, "st_file_attributes", 0)
    return bool(attributes & ONLINE_ONLY_ATTRIBUTES)


def list_candidate_files(
    folder: Path, progress: IndexingProgress
) -> list[tuple[Path, os.stat_result]]:
    """Walk a folder for indexable files, reading metadata only.

    Uses os.walk with an error callback so one unreadable subfolder is
    recorded and skipped rather than ending the run.
    """
    candidates: list[tuple[Path, os.stat_result]] = []

    def record_walk_error(error: OSError) -> None:
        progress.record_failure(
            Path(error.filename or "folder").name, error.strerror or "unreadable"
        )

    for directory, folder_names, file_names in os.walk(
        folder, onerror=record_walk_error
    ):
        folder_names[:] = [
            name for name in folder_names if name not in IGNORED_FOLDER_NAMES
        ]
        for file_name in file_names:
            path = Path(directory) / file_name
            if path.suffix.lower() not in SUPPORTED_SUFFIXES or file_name.startswith(
                "~$"
            ):
                continue
            try:
                # lstat does not follow links and never opens the file, so
                # it does not trigger a cloud download.
                candidates.append((path, path.lstat()))
            except OSError as error:
                progress.record_failure(file_name, error.strerror or "unreadable")
    candidates.sort(key=lambda candidate: str(candidate[0]))
    return candidates


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source_file:
        for block in iter(lambda: source_file.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _to_fts_query(query: str) -> str:
    """Turn free text into an FTS5 OR query of quoted terms."""
    terms = re.findall(r"[A-Za-z0-9]{2,}", query)
    return " OR ".join(f'"{term}"' for term in terms)


def _greedy_similarity_order(similarity: np.ndarray) -> list[int]:
    """Order nodes so each is followed by its most similar unvisited node.

    Placing that order around a circle keeps related files adjacent, so the
    connecting lines stay short and the map reads as neighbourhoods.
    """
    node_count = similarity.shape[0]
    order = [0]
    is_visited = np.zeros(node_count, dtype=bool)
    is_visited[0] = True
    for _ in range(node_count - 1):
        candidates = np.where(is_visited, -np.inf, similarity[order[-1]])
        next_node = int(np.argmax(candidates))
        order.append(next_node)
        is_visited[next_node] = True
    return order


def build_file_graph(
    chunk_embeddings: list[tuple[str, bytes]],
    neighbour_count: int = GRAPH_NEIGHBOUR_COUNT,
) -> dict[str, Any]:
    """Build nodes and similarity edges from (file path, embedding) rows."""
    vectors_by_file: dict[str, list[np.ndarray]] = {}
    for file_path, embedding in chunk_embeddings:
        vectors_by_file.setdefault(file_path, []).append(
            np.frombuffer(embedding, dtype=np.float32)
        )
    file_paths = sorted(vectors_by_file)
    if not file_paths:
        return {"nodes": [], "edges": [], "file_count": 0, "chunk_count": 0}
    centroids = np.vstack(
        [np.mean(vectors_by_file[path], axis=0) for path in file_paths]
    )
    norms = np.linalg.norm(centroids, axis=1, keepdims=True)
    centroids = centroids / np.where(norms == 0, 1.0, norms)
    similarity = centroids @ centroids.T
    np.fill_diagonal(similarity, -np.inf)
    order = _greedy_similarity_order(similarity)
    nodes = [
        {
            "id": file_paths[index],
            "name": Path(file_paths[index]).name,
            "chunk_count": len(vectors_by_file[file_paths[index]]),
        }
        for index in order
    ]
    edge_pairs: dict[tuple[int, int], float] = {}
    for index in range(len(file_paths)):
        for neighbour in np.argsort(-similarity[index])[:neighbour_count]:
            score = float(similarity[index, neighbour])
            if score >= GRAPH_MIN_SIMILARITY:
                pair = (min(index, int(neighbour)), max(index, int(neighbour)))
                edge_pairs[pair] = score
    edges = [
        {
            "source": file_paths[first],
            "target": file_paths[second],
            "similarity": round(score, 3),
        }
        for (first, second), score in sorted(edge_pairs.items())
    ]
    return {
        "nodes": nodes,
        "edges": edges,
        "file_count": len(file_paths),
        "chunk_count": len(chunk_embeddings),
    }


def reciprocal_rank_fusion(rankings: list[list[int]]) -> list[tuple[int, float]]:
    """Merge ranked ID lists. Returns (id, score) pairs, best first."""
    scores: dict[int, float] = {}
    for ranking in rankings:
        for rank, chunk_id in enumerate(ranking, start=1):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (RRF_CONSTANT + rank)
    return sorted(scores.items(), key=lambda pair: -pair[1])


class KnowledgeIndex:
    """Indexes connected folders and answers hybrid searches over them."""

    def __init__(self, database_path: Path, embed: EmbedFunction) -> None:
        database_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(database_path, check_same_thread=False)
        self._lock = threading.Lock()
        self._embed = embed
        self._graph_cache: tuple[tuple[int, int], dict[str, Any]] | None = None
        with self._lock:
            self._connection.executescript(_SCHEMA)
            self._connection.commit()

    def close(self) -> None:
        """Close the database connection."""
        with self._lock:
            self._connection.close()

    async def index_folder(
        self, folder: Path, progress: IndexingProgress | None = None
    ) -> IndexingProgress:
        """Bring the index up to date with a folder.

        Re-indexes files whose content hash changed and removes chunks for
        files that no longer exist. Unreadable files are recorded in the
        progress and skipped; their previous chunks, if any, are kept.

        Args:
            folder: The connected folder.
            progress: Updated in place as the run goes, so a caller can
                report it while the run is in flight.

        Raises:
            OrchestratorError: If the embedding model fails. That affects
                every file, so the run stops rather than skipping them all.
        """
        folder = folder.resolve()
        progress = progress or IndexingProgress(folder=str(folder))
        candidates = await asyncio.to_thread(list_candidate_files, folder, progress)
        progress.total_file_count = len(candidates)
        progress.state = "indexing"
        logger.info(
            "Knowledge folder indexing started",
            extra={"total_file_count": progress.total_file_count},
        )
        present_paths: set[str] = set()
        for path, stat_result in candidates:
            present_paths.add(str(path))
            await self._index_candidate(path, stat_result, progress)
            progress.processed_file_count += 1
            if progress.processed_file_count % PROGRESS_LOG_INTERVAL_FILES == 0:
                _log_progress(progress)
        progress.removed_file_count = self._remove_missing(str(folder), present_paths)
        progress.state = "done"
        progress.finished_at = datetime.now(UTC).isoformat()
        logger.info(
            "Knowledge folder indexed",
            extra={
                "total_file_count": progress.total_file_count,
                "indexed_file_count": progress.indexed_file_count,
                "unchanged_file_count": progress.unchanged_file_count,
                "skipped_online_only_count": progress.skipped_online_only_count,
                "failed_file_count": progress.failed_file_count,
                "removed_file_count": progress.removed_file_count,
                "chunk_count": progress.chunk_count,
            },
        )
        return progress

    async def _index_candidate(
        self, path: Path, stat_result: os.stat_result, progress: IndexingProgress
    ) -> None:
        """Index one file, or record why it was skipped."""
        if is_online_only(stat_result):
            progress.skipped_online_only_count += 1
            return
        if stat_result.st_size > MAX_INDEXED_FILE_BYTES:
            progress.record_failure(path.name, "larger than 20 MB")
            return
        try:
            content_hash = await asyncio.to_thread(_hash_file, path)
            if self._stored_hash(str(path)) == content_hash:
                progress.unchanged_file_count += 1
                return
            progress.chunk_count += await self._index_file(
                path, content_hash, stat_result.st_size
            )
            progress.indexed_file_count += 1
        except OSError as error:
            logger.warning(
                "File skipped during indexing",
                extra={"file_name": path.name, "exception_type": type(error).__name__},
            )
            progress.record_failure(path.name, error.strerror or "could not be read")

    async def search(self, query: str, limit: int = TOP_RESULTS) -> list[SearchHit]:
        """Hybrid keyword and vector search, fused by reciprocal rank."""
        keyword_ranking = self._keyword_ranking(query)
        vector_ranking = await self._vector_ranking(query)
        fused = reciprocal_rank_fusion([keyword_ranking, vector_ranking])[:limit]
        hits: list[SearchHit] = []
        with self._lock:
            for chunk_id, score in fused:
                row = self._connection.execute(
                    "SELECT file_path, heading_path, chunk_text FROM chunk "
                    "WHERE chunk_id = ?",
                    (chunk_id,),
                ).fetchone()
                if row is not None:
                    hits.append(SearchHit(row[0], row[1], row[2], score))
        return hits

    def graph(self) -> dict[str, Any]:
        """The index as a graph of files, for the interface's index map.

        Each file is placed by the mean of its passages' embeddings. Each is
        joined to its nearest neighbours by cosine similarity, and files are
        ordered so similar ones sit next to each other on a circle. The result
        is cached until the index changes, because the interface polls it.
        """
        with self._lock:
            rows = self._connection.execute(
                "SELECT chunk_id, file_path, embedding FROM chunk "
                "WHERE embedding IS NOT NULL ORDER BY file_path, chunk_id"
            ).fetchall()
        revision = (len(rows), rows[-1][0] if rows else 0)
        if self._graph_cache is not None and self._graph_cache[0] == revision:
            return self._graph_cache[1]
        built = build_file_graph([(row[1], row[2]) for row in rows])
        self._graph_cache = (revision, built)
        return built

    def chunk_total(self) -> int:
        """Number of chunks currently indexed."""
        with self._lock:
            return int(
                self._connection.execute("SELECT COUNT(*) FROM chunk").fetchone()[0]
            )

    def _stored_hash(self, file_path: str) -> str | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT content_hash FROM source_file WHERE file_path = ?", (file_path,)
            ).fetchone()
        return row[0] if row else None

    async def _index_file(self, path: Path, content_hash: str, size_bytes: int) -> int:
        started_at = time.monotonic()
        # Parsing large Office files is CPU-bound; keep it off the event loop
        # so the API stays responsive while a folder indexes.
        markdown_text = await asyncio.to_thread(parse_document, path)
        parsed_at = time.monotonic()
        chunks = chunk_markdown(markdown_text)
        vectors = (
            await self._embed(
                [f"{chunk.heading_path}\n{chunk.text}" for chunk in chunks]
            )
            if chunks
            else []
        )
        _log_file_indexed(path, size_bytes, len(chunks), started_at, parsed_at)
        with self._lock:
            self._delete_file_rows(str(path))
            for chunk, vector in zip(chunks, vectors, strict=True):
                cursor = self._connection.execute(
                    "INSERT INTO chunk (file_path, heading_path, chunk_text, embedding) "
                    "VALUES (?, ?, ?, ?)",
                    (
                        str(path),
                        chunk.heading_path,
                        chunk.text,
                        np.asarray(vector, dtype=np.float32).tobytes(),
                    ),
                )
                self._connection.execute(
                    "INSERT INTO chunk_fts (rowid, chunk_text, heading_path) "
                    "VALUES (?, ?, ?)",
                    (cursor.lastrowid, chunk.text, chunk.heading_path),
                )
            self._connection.execute(
                "INSERT OR REPLACE INTO source_file VALUES (?, ?)",
                (str(path), content_hash),
            )
            self._connection.commit()
        return len(chunks)

    def _delete_file_rows(self, file_path: str) -> None:
        """Remove a file's chunks. Caller holds the lock."""
        rows = self._connection.execute(
            "SELECT chunk_id, chunk_text, heading_path FROM chunk WHERE file_path = ?",
            (file_path,),
        ).fetchall()
        for chunk_id, chunk_text, heading_path in rows:
            # External-content FTS5 tables need the old values to delete.
            self._connection.execute(
                "INSERT INTO chunk_fts (chunk_fts, rowid, chunk_text, heading_path) "
                "VALUES ('delete', ?, ?, ?)",
                (chunk_id, chunk_text, heading_path),
            )
        self._connection.execute("DELETE FROM chunk WHERE file_path = ?", (file_path,))
        self._connection.execute(
            "DELETE FROM source_file WHERE file_path = ?", (file_path,)
        )

    def retain_only_folders(self, connected_folders: list[str]) -> int:
        """Delete every indexed file that is not under a connected folder.

        Removing a folder must remove its content, not just hide it: otherwise
        searches keep returning passages from a folder the user disconnected,
        and the index keeps a copy of data the user withdrew.

        Returns:
            The number of files removed from the index.
        """
        prefixes = [folder.rstrip(os.sep) + os.sep for folder in connected_folders]
        with self._lock:
            stored_paths = [
                row[0]
                for row in self._connection.execute("SELECT file_path FROM source_file")
            ]
            orphaned_paths = [
                stored_path
                for stored_path in stored_paths
                if not any(stored_path.startswith(prefix) for prefix in prefixes)
            ]
            for orphaned_path in orphaned_paths:
                self._delete_file_rows(orphaned_path)
            self._connection.commit()
        if orphaned_paths:
            logger.info(
                "Removed files of disconnected folders from the index",
                extra={"removed_file_count": len(orphaned_paths)},
            )
        return len(orphaned_paths)

    def _remove_missing(self, folder_prefix: str, present_paths: set[str]) -> int:
        with self._lock:
            stored_paths = [
                row[0]
                for row in self._connection.execute(
                    "SELECT file_path FROM source_file"
                ).fetchall()
            ]
            missing_paths = [
                stored_path
                for stored_path in stored_paths
                # Trailing separator: "Files" must not match "Files 2".
                if stored_path.startswith(folder_prefix.rstrip(os.sep) + os.sep)
                and stored_path not in present_paths
            ]
            for missing_path in missing_paths:
                self._delete_file_rows(missing_path)
            self._connection.commit()
        return len(missing_paths)

    def _keyword_ranking(self, query: str) -> list[int]:
        fts_query = _to_fts_query(query)
        if not fts_query:
            return []
        with self._lock:
            rows = self._connection.execute(
                "SELECT rowid FROM chunk_fts WHERE chunk_fts MATCH ? "
                "ORDER BY bm25(chunk_fts) LIMIT ?",
                (fts_query, CANDIDATES_PER_SEARCH),
            ).fetchall()
        return [row[0] for row in rows]

    async def _vector_ranking(self, query: str) -> list[int]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT chunk_id, embedding FROM chunk WHERE embedding IS NOT NULL"
            ).fetchall()
        if not rows:
            return []
        query_vector = np.asarray((await self._embed([query]))[0], dtype=np.float32)
        matrix = np.vstack([np.frombuffer(row[1], dtype=np.float32) for row in rows])
        norms = np.linalg.norm(matrix, axis=1) * np.linalg.norm(query_vector)
        similarities = (matrix @ query_vector) / np.where(norms == 0, 1.0, norms)
        best_indices = np.argsort(-similarities)[:CANDIDATES_PER_SEARCH]
        return [int(rows[index][0]) for index in best_indices]
