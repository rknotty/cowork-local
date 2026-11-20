"""HTTP API and event stream, served on the loopback interface only.

The contract is documented in docs/event-contract.md. The interface renders
events and posts user actions; every decision is made here or below.
"""

from __future__ import annotations

import asyncio
import json
import logging
import mimetypes
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from orchestrator.bootstrap import Application, build_application
from orchestrator.errors import (
    GatewayUnavailableError,
    OrchestratorError,
    PathNotAllowedError,
    SandboxUnavailableError,
    SensitiveContentError,
    SessionNotFoundError,
    ToolExecutionError,
)
from orchestrator.events import AgentEvent
from orchestrator.folder_dialog import choose_folder_with_dialog
from orchestrator.knowledge.coordinator import IndexingCoordinator
from orchestrator.logging_setup import configure_logging, correlation_id_var
from orchestrator.mcp_client import McpServerConnection, start_mcp_servers
from orchestrator.paths import PathAllowlist
from orchestrator.settings import load_settings
from orchestrator.store import DEFAULT_SESSION_TITLE, MAX_TITLE_CHARACTERS
from orchestrator.toolkit.context import APPROVAL_DECISIONS, ToolContext

logger = logging.getLogger(__name__)

LOOPBACK_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
KEEPALIVE_SECONDS = 15
MAX_UPLOAD_BYTES = 50_000_000
MAX_AUDIO_BYTES = 25_000_000
PREVIEW_SUFFIX = ".preview.pdf"
CONNECTED_FOLDERS_FILE = "connected_folders.json"
AUDIO_SUFFIX_BY_CONTENT_TYPE = {"audio/wav": ".wav", "audio/webm": ".webm"}

STATUS_BY_ERROR: dict[type[OrchestratorError], int] = {
    SessionNotFoundError: 404,
    PathNotAllowedError: 403,
    ToolExecutionError: 400,
    SensitiveContentError: 400,
    GatewayUnavailableError: 503,
    SandboxUnavailableError: 503,
}


class CreateSessionRequest(BaseModel):
    """Body of POST /api/sessions."""

    title: str = Field(default=DEFAULT_SESSION_TITLE, max_length=MAX_TITLE_CHARACTERS)


class RenameSessionRequest(BaseModel):
    """Body of PATCH /api/sessions/{id}."""

    title: str = Field(min_length=1, max_length=MAX_TITLE_CHARACTERS)


class SendMessageRequest(BaseModel):
    """Body of POST /api/sessions/{id}/messages."""

    text: str = Field(min_length=1, max_length=20_000)


class ApprovalRequest(BaseModel):
    """Body of POST /api/sessions/{id}/approvals/{request_id}."""

    decision: str = Field(pattern=f"^({'|'.join(APPROVAL_DECISIONS)})$")


class AnswerRequest(BaseModel):
    """Body of POST /api/sessions/{id}/answers/{question_id}."""

    answer: str = Field(max_length=2000)


class MemoryRequest(BaseModel):
    """Body of PUT /api/memory/{name}."""

    description: str = Field(max_length=160)
    content: str = Field(max_length=4000)


class FoldersRequest(BaseModel):
    """Body of PUT /api/folders."""

    folders: list[str] = Field(max_length=20)


class BrowseRequest(BaseModel):
    """Body of POST /api/folders/browse."""

    start_folder: str | None = Field(default=None, max_length=1024)


@dataclass
class SessionRuntime:
    """Live state for one session: its tool context, subscribers and turn."""

    context: ToolContext
    subscribers: list[asyncio.Queue[AgentEvent]] = field(default_factory=list)
    turn_task: asyncio.Task[str] | None = None


class SessionRuntimes:
    """Creates and caches a runtime per session."""

    def __init__(self, application: Application) -> None:
        self._application = application
        self._runtimes: dict[str, SessionRuntime] = {}

    def get(self, session_id: str) -> SessionRuntime:
        """Fetch or create the runtime. Raises SessionNotFoundError."""
        runtime = self._runtimes.get(session_id)
        if runtime is None:

            def publish(event: AgentEvent) -> None:
                for subscriber in self._runtimes[session_id].subscribers:
                    subscriber.put_nowait(event)

            context = self._application.create_tool_context(session_id, publish)
            runtime = SessionRuntime(context=context)
            self._runtimes[session_id] = runtime
        return runtime

    def refresh_allowlists(self) -> None:
        """Apply a change to connected folders to every live session."""
        folders = [
            Path(folder) for folder in self._application.services.connected_folders
        ]
        for runtime in self._runtimes.values():
            runtime.context.allowlist = PathAllowlist(
                runtime.context.allowlist.workspace, folders
            )


def _error_response(error_code: str, message: str, status_code: int) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error": error_code,
            "message": message,
            "trace_id": correlation_id_var.get(),
        },
    )


def _load_connected_folders(application: Application) -> None:
    folders_path = application.services.settings.data_directory / CONNECTED_FOLDERS_FILE
    if folders_path.is_file():
        stored = json.loads(folders_path.read_text(encoding="utf-8"))
        application.services.connected_folders = [str(folder) for folder in stored]


def _workspace_file_path(runtime: SessionRuntime, relative_path: str) -> Path:
    """Resolve a path that must stay inside the session workspace."""
    workspace_only = PathAllowlist(runtime.context.allowlist.workspace, [])
    return workspace_only.resolve_allowed(relative_path)


def _list_workspace_files(runtime: SessionRuntime) -> list[dict[str, object]]:
    workspace = runtime.context.allowlist.workspace
    files = []
    for path in sorted(workspace.rglob("*")):
        if not path.is_file() or path.name.endswith(PREVIEW_SUFFIX):
            continue
        relative_path = path.relative_to(workspace).as_posix()
        preview = path.with_suffix(PREVIEW_SUFFIX)
        stat = path.stat()
        files.append(
            {
                "relative_path": relative_path,
                "size_bytes": stat.st_size,
                "modified_at": datetime.fromtimestamp(stat.st_mtime, UTC).isoformat(),
                "is_changed_this_session": relative_path
                in runtime.context.changed_paths,
                "preview_path": (
                    preview.relative_to(workspace).as_posix()
                    if preview.is_file()
                    else None
                ),
            }
        )
    return files


async def _event_frames(
    request: Request, runtime: SessionRuntime
) -> AsyncIterator[str]:
    queue: asyncio.Queue[AgentEvent] = asyncio.Queue()
    runtime.subscribers.append(queue)
    try:
        while not await request.is_disconnected():
            try:
                event = await asyncio.wait_for(queue.get(), KEEPALIVE_SECONDS)
            except TimeoutError:
                # Comment frame: keeps the connection open through idle turns.
                yield ": keepalive\n\n"
                continue
            yield event.to_server_sent_event()
    finally:
        runtime.subscribers.remove(queue)


def _register_session_routes(
    app: FastAPI, application: Application, runtimes: SessionRuntimes
) -> None:
    services = application.services

    @app.get("/api/sessions")
    async def list_sessions() -> list[dict[str, str]]:
        return [asdict(session) for session in services.store.list_sessions()]

    @app.post("/api/sessions", status_code=201)
    async def create_session(body: CreateSessionRequest) -> dict[str, str]:
        session = services.store.create_session(
            body.title, services.settings.data_directory / "workspaces"
        )
        return asdict(session)

    @app.patch("/api/sessions/{session_id}")
    async def rename_session(
        session_id: str, body: RenameSessionRequest
    ) -> dict[str, str]:
        title = " ".join(body.title.split())
        if not title:
            raise ToolExecutionError("a session name cannot be blank")
        services.store.get_session(session_id)
        services.store.rename_session(session_id, title)
        return asdict(services.store.get_session(session_id))

    @app.get("/api/sessions/{session_id}/messages")
    async def list_messages(session_id: str) -> list[dict[str, object]]:
        services.store.get_session(session_id)
        return [
            message
            for message in services.store.load_messages(session_id)
            if message.get("role") != "system"
        ]

    @app.post("/api/sessions/{session_id}/messages", status_code=202)
    async def send_message(
        session_id: str, body: SendMessageRequest
    ) -> dict[str, bool]:
        runtime = runtimes.get(session_id)
        if runtime.turn_task is not None and not runtime.turn_task.done():
            raise ToolExecutionError("a turn is already running in this session")
        runtime.turn_task = asyncio.create_task(
            application.agent_loop.run_turn(runtime.context, body.text)
        )
        return {"accepted": True}

    @app.get("/api/sessions/{session_id}/events")
    async def stream_events(session_id: str, request: Request) -> StreamingResponse:
        runtime = runtimes.get(session_id)
        return StreamingResponse(
            _event_frames(request, runtime),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.post("/api/sessions/{session_id}/approvals/{request_id}", status_code=204)
    async def answer_approval(
        session_id: str, request_id: str, body: ApprovalRequest
    ) -> Response:
        runtimes.get(session_id).context.broker.resolve(request_id, body.decision)
        return Response(status_code=204)

    @app.post("/api/sessions/{session_id}/answers/{question_id}", status_code=204)
    async def answer_question(
        session_id: str, question_id: str, body: AnswerRequest
    ) -> Response:
        runtimes.get(session_id).context.broker.resolve(question_id, body.answer)
        return Response(status_code=204)

    @app.post("/api/sessions/{session_id}/stop", status_code=204)
    async def stop_turn(session_id: str) -> Response:
        runtime = runtimes.get(session_id)
        if runtime.turn_task is not None and not runtime.turn_task.done():
            runtime.turn_task.cancel()
        return Response(status_code=204)


def _register_file_routes(app: FastAPI, runtimes: SessionRuntimes) -> None:
    @app.get("/api/sessions/{session_id}/files")
    async def list_files(session_id: str) -> list[dict[str, object]]:
        return _list_workspace_files(runtimes.get(session_id))

    @app.get("/api/sessions/{session_id}/files/{relative_path:path}")
    async def read_workspace_file(session_id: str, relative_path: str) -> FileResponse:
        file_path = _workspace_file_path(runtimes.get(session_id), relative_path)
        if not file_path.is_file():
            raise ToolExecutionError("file not found")
        content_type = (
            mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
        )
        return FileResponse(
            file_path,
            media_type=content_type,
            # Workspace files are untrusted content. Stop the browser running
            # an HTML artefact with the interface's own origin privileges.
            headers={
                "Content-Security-Policy": "sandbox; default-src 'none'",
                "X-Content-Type-Options": "nosniff",
            },
        )

    @app.put("/api/sessions/{session_id}/files/{relative_path:path}", status_code=204)
    async def upload_workspace_file(
        session_id: str, relative_path: str, request: Request
    ) -> Response:
        runtime = runtimes.get(session_id)
        file_path = _workspace_file_path(runtime, relative_path)
        body = await request.body()
        if len(body) > MAX_UPLOAD_BYTES:
            raise ToolExecutionError("file is larger than the 50 MB upload limit")
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_bytes(body)
        return Response(status_code=204)


def _register_library_routes(
    app: FastAPI,
    application: Application,
    runtimes: SessionRuntimes,
    indexing: IndexingCoordinator,
) -> None:
    services = application.services

    @app.get("/api/health")
    async def health() -> dict[str, object]:
        gateway_health = await services.gateway.health()
        return {
            "is_healthy": bool(gateway_health.get("is_healthy")),
            "is_offline": not services.settings.is_web_search_enabled,
            "sandbox_state": services.sandbox.state(),
            "roles": gateway_health.get("roles", {}),
            "context_limit_tokens": services.settings.roles[
                "orchestrator"
            ].context_limit_tokens,
        }

    @app.get("/api/skills")
    async def list_skills() -> list[dict[str, str]]:
        return [
            {"name": skill.name, "description": skill.description}
            for skill in services.skills.all_skills()
        ]

    @app.get("/api/memory")
    async def list_memory() -> list[dict[str, str]]:
        return [asdict(memory_file) for memory_file in services.memory.list_files()]

    @app.put("/api/memory/{name}", status_code=204)
    async def save_memory(name: str, body: MemoryRequest) -> Response:
        services.memory.save(name, body.description, body.content)
        return Response(status_code=204)

    @app.delete("/api/memory/{name}", status_code=204)
    async def delete_memory(name: str) -> Response:
        services.memory.delete(name)
        return Response(status_code=204)

    @app.get("/api/folders")
    async def list_folders() -> dict[str, list[str]]:
        return {"folders": services.connected_folders}

    @app.put("/api/folders", status_code=204)
    async def set_folders(body: FoldersRequest) -> Response:
        resolved_folders = []
        for folder in body.folders:
            folder_path = Path(folder)
            if not folder_path.is_absolute() or not folder_path.is_dir():
                raise ToolExecutionError(
                    "each folder must be an absolute path to an existing folder"
                )
            resolved_folders.append(str(folder_path.resolve()))
        services.connected_folders = resolved_folders
        folders_path = services.settings.data_directory / CONNECTED_FOLDERS_FILE
        folders_path.write_text(json.dumps(resolved_folders), encoding="utf-8")
        runtimes.refresh_allowlists()
        # Disconnecting a folder removes its content from the index at once,
        # so searches and the index map never show a folder the user removed.
        await indexing.disconnect_others(resolved_folders)
        for folder in resolved_folders:
            # Indexing embeds every changed file; it runs behind the response
            # and reports through /api/knowledge/status.
            indexing.start(Path(folder))
        return Response(status_code=204)

    @app.post("/api/folders/browse")
    async def browse_for_folder(body: BrowseRequest) -> dict[str, str | None]:
        # Requiring a JSON body forces a CORS preflight, which this API does
        # not answer, so another website cannot pop a dialog on this desktop.
        chosen = await asyncio.to_thread(choose_folder_with_dialog, body.start_folder)
        return {"folder": chosen}

    @app.get("/api/knowledge/graph")
    async def knowledge_graph() -> dict[str, object]:
        # Similarity across every file is CPU work; keep it off the event loop.
        return await asyncio.to_thread(services.knowledge.graph)

    @app.get("/api/knowledge/status")
    async def knowledge_status() -> list[dict[str, object]]:
        return indexing.status(services.connected_folders)

    @app.post("/api/knowledge/reindex", status_code=202)
    async def reindex_knowledge() -> dict[str, bool]:
        for folder in services.connected_folders:
            indexing.start(Path(folder))
        return {"accepted": True}

    @app.post("/api/transcriptions")
    async def transcribe(request: Request) -> dict[str, str]:
        content_type = request.headers.get("content-type", "").split(";")[0]
        suffix = AUDIO_SUFFIX_BY_CONTENT_TYPE.get(content_type)
        if suffix is None:
            raise ToolExecutionError("audio must be audio/wav or audio/webm")
        audio_bytes = await request.body()
        if not audio_bytes or len(audio_bytes) > MAX_AUDIO_BYTES:
            raise ToolExecutionError("audio is empty or larger than 25 MB")
        audio_directory = services.settings.data_directory / "tmp"
        audio_directory.mkdir(parents=True, exist_ok=True)
        audio_path = audio_directory / f"{uuid.uuid4().hex}{suffix}"
        audio_path.write_bytes(audio_bytes)
        try:
            transcription = await services.gateway.transcribe(audio_path)
        finally:
            audio_path.unlink(missing_ok=True)
        return {"text": transcription.text}


def _register_error_handling(app: FastAPI) -> None:
    @app.middleware("http")
    async def attach_correlation_id(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        correlation_id_var.set(uuid.uuid4().hex)
        response = await call_next(request)
        response.headers["X-Trace-Id"] = correlation_id_var.get()
        return response

    @app.exception_handler(OrchestratorError)
    async def handle_domain_error(
        request: Request, error: OrchestratorError
    ) -> JSONResponse:
        status_code = next(
            (
                status
                for error_type, status in STATUS_BY_ERROR.items()
                if isinstance(error, error_type)
            ),
            500,
        )
        if status_code >= 500:
            logger.error(
                "Request failed",
                extra={"error_code": error.error_code, "detail": error.detail},
            )
        # ToolExecutionError details are written for the user (which input is
        # wrong and how to fix it); other details stay in the log.
        message = (
            error.detail if type(error) is ToolExecutionError else error.safe_message
        )
        return _error_response(error.error_code, message, status_code)

    @app.exception_handler(Exception)
    async def handle_unexpected_error(
        request: Request, error: Exception
    ) -> JSONResponse:
        logger.exception("Unhandled error", extra={"path": request.url.path})
        return _error_response(
            "INTERNAL_ERROR", "Something went wrong. The details were logged.", 500
        )


def create_app(application: Application | None = None) -> FastAPI:
    """Build the FastAPI app.

    Args:
        application: The assembled orchestrator. Tests pass one built on a
            fake model runtime.
    """
    resolved_application = application or build_application()
    runtimes = SessionRuntimes(resolved_application)
    mcp_connections: list[McpServerConnection] = []

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        _load_connected_folders(resolved_application)
        # Clear content left by folders disconnected while the orchestrator
        # was stopped, or by builds before removal deleted content.
        await asyncio.to_thread(
            resolved_application.services.knowledge.retain_only_folders,
            resolved_application.services.connected_folders,
        )
        mcp_connections.extend(
            await start_mcp_servers(
                resolved_application.services.settings.mcp_servers,
                resolved_application.registry,
            )
        )
        yield
        for connection in mcp_connections:
            await connection.stop()

    app = FastAPI(title="Local Cowork orchestrator", lifespan=lifespan)
    _register_error_handling(app)
    _register_session_routes(app, resolved_application, runtimes)
    _register_file_routes(app, runtimes)
    _register_library_routes(
        app,
        resolved_application,
        runtimes,
        IndexingCoordinator(resolved_application.services.knowledge),
    )
    interface_directory = (
        resolved_application.services.settings.repository_root / "web" / "dist"
    )
    if interface_directory.is_dir():
        app.mount("/", StaticFiles(directory=interface_directory, html=True))
    return app


def main() -> None:
    """Serve the API on the loopback interface."""
    import uvicorn

    settings = load_settings()
    log_file = configure_logging(settings.data_directory / "logs")
    logger.info("Orchestrator starting", extra={"log_file": str(log_file)})
    # Loopback only: binding to 0.0.0.0 would expose an unauthenticated agent
    # with file access to the network.
    uvicorn.run(
        create_app(build_application(settings)),
        host=LOOPBACK_HOST,
        port=DEFAULT_PORT,
        log_config=None,
    )


if __name__ == "__main__":
    main()
