"""Path allowlist (plan section 9, step 2).

Every path a tool touches is resolved to its canonical form first, so `..`
segments, symlinks and junctions cannot be used to step outside the folders
the user connected.
"""

from __future__ import annotations

from pathlib import Path

from orchestrator.errors import PathNotAllowedError

TO_DELETE_FOLDER_NAME = "_to_delete"
WORKSPACE_ROOT_ALIASES = frozenset({"", ".", "./", ".\\", "/", "\\"})


class PathAllowlist:
    """Decides whether a path is inside the workspace or a connected folder."""

    def __init__(self, workspace: Path, connected_folders: list[Path]) -> None:
        self._workspace = workspace.resolve()
        self._connected_folders = [folder.resolve() for folder in connected_folders]

    @property
    def workspace(self) -> Path:
        """The session workspace. Relative paths resolve against it."""
        return self._workspace

    @property
    def allowed_roots(self) -> list[Path]:
        """Workspace first, then every connected folder."""
        return [self._workspace, *self._connected_folders]

    def resolve_allowed(self, requested_path: str) -> Path:
        """Return the canonical path, or refuse it.

        Args:
            requested_path: Absolute, or relative to the session workspace.

        Raises:
            PathNotAllowedError: If the canonical path is outside every
                allowed root. This covers symlinks that escape, because
                resolution follows them before the check.
        """
        if requested_path.strip() in WORKSPACE_ROOT_ALIASES:
            # Small models write "/" to mean "the folder I am working in". On
            # Windows that resolves to the drive root and is refused, leaving
            # the model stuck; mapping it to the workspace widens nothing.
            return self._workspace
        candidate = Path(requested_path)
        if not candidate.is_absolute():
            candidate = self._workspace / candidate
        # strict=False: the target of a write may not exist yet. Existing
        # parents are still resolved through any symlink.
        canonical_path = candidate.resolve(strict=False)
        if not any(
            canonical_path == root or root in canonical_path.parents
            for root in self.allowed_roots
        ):
            raise PathNotAllowedError(
                "path outside allowed roots", requested_path=requested_path
            )
        return canonical_path

    def is_inside_workspace(self, canonical_path: Path) -> bool:
        """True when the path is the workspace or beneath it."""
        return (
            canonical_path == self._workspace
            or self._workspace in canonical_path.parents
        )
