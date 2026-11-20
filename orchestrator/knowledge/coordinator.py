"""Runs folder indexing in the background and keeps its status for the API.

Indexing a folder can take minutes: every changed file is parsed and
embedded. The API starts it and returns at once; the interface polls
`status()` to show progress. A failed run is recorded, not lost.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from orchestrator.errors import OrchestratorError
from orchestrator.knowledge.index import IndexingProgress, KnowledgeIndex

logger = logging.getLogger(__name__)

RUNNING_STATES = ("scanning", "indexing")
UNEXPECTED_FAILURE_MESSAGE = (
    "Indexing stopped unexpectedly. The details are in the orchestrator log."
)


class IndexingCoordinator:
    """One background indexing run per folder, with its latest status."""

    def __init__(self, knowledge: KnowledgeIndex) -> None:
        self._knowledge = knowledge
        self._progress_by_folder: dict[str, IndexingProgress] = {}
        # Holding the task stops it being garbage-collected mid-run, and lets
        # a folder's run be cancelled when the folder is disconnected.
        self._running_tasks: dict[str, asyncio.Task[None]] = {}

    def start(self, folder: Path) -> None:
        """Start indexing a folder unless a run for it is already in progress."""
        folder_key = str(folder)
        current = self._progress_by_folder.get(folder_key)
        if current is not None and current.state in RUNNING_STATES:
            return
        progress = IndexingProgress(folder=folder_key)
        self._progress_by_folder[folder_key] = progress
        task = asyncio.create_task(self._run(folder, progress))
        self._running_tasks[folder_key] = task
        task.add_done_callback(lambda finished: self._forget_task(folder_key, finished))

    async def disconnect_others(self, connected_folders: list[str]) -> int:
        """Stop indexing, and remove from the index, every folder not connected.

        Cancels a run still in progress first, so it cannot write the
        folder's files back after they have been removed.

        Returns:
            The number of files removed from the index.
        """
        connected = set(connected_folders)
        stopping = [
            task
            for folder, task in self._running_tasks.items()
            if folder not in connected
        ]
        for task in stopping:
            task.cancel()
        # Wait for cancellation to land: writes happen only between awaits.
        await asyncio.gather(*stopping, return_exceptions=True)
        for folder in list(self._progress_by_folder):
            if folder not in connected:
                del self._progress_by_folder[folder]
        return await asyncio.to_thread(
            self._knowledge.retain_only_folders, connected_folders
        )

    def _forget_task(self, folder_key: str, finished: asyncio.Task[None]) -> None:
        if self._running_tasks.get(folder_key) is finished:
            del self._running_tasks[folder_key]

    def status(self, connected_folders: list[str]) -> list[dict[str, object]]:
        """Latest progress for each connected folder, `not_indexed` if none."""
        statuses: list[dict[str, object]] = []
        for folder in connected_folders:
            progress = self._progress_by_folder.get(folder)
            if progress is None:
                statuses.append({"folder": folder, "state": "not_indexed"})
            else:
                statuses.append(asdict(progress))
        return statuses

    async def _run(self, folder: Path, progress: IndexingProgress) -> None:
        # Boundary of a background task: nothing above it can catch, so every
        # failure is logged and recorded here instead of disappearing.
        try:
            await self._knowledge.index_folder(folder, progress)
        except OrchestratorError as error:
            logger.exception("Indexing failed", extra={"error_code": error.error_code})
            self._mark_failed(progress, error.safe_message)
        except Exception:  # noqa: BLE001 - background task boundary, see above
            logger.exception("Indexing failed unexpectedly")
            self._mark_failed(progress, UNEXPECTED_FAILURE_MESSAGE)

    @staticmethod
    def _mark_failed(progress: IndexingProgress, message: str) -> None:
        progress.state = "failed"
        progress.error_message = message
        progress.finished_at = datetime.now(UTC).isoformat()
