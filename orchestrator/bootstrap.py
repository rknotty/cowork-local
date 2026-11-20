"""Composition root: builds the services, registry and router once."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from orchestrator.agent_loop import AgentLoop
from orchestrator.audit import AuditLog
from orchestrator.gateway import ModelGateway
from orchestrator.knowledge.index import KnowledgeIndex
from orchestrator.memory import MemoryStore
from orchestrator.model_runtime import FoundryCliRuntime, ModelRuntimeProtocol
from orchestrator.paths import PathAllowlist
from orchestrator.sandbox import Sandbox
from orchestrator.services import Services
from orchestrator.settings import Settings, load_settings
from orchestrator.skills import SkillIndex
from orchestrator.store import SessionStore
from orchestrator.toolkit.context import EventEmitter, ToolContext
from orchestrator.toolkit.document_tools import register_document_tools
from orchestrator.toolkit.extraction import register_extraction_tool
from orchestrator.toolkit.file_tools import register_file_tools
from orchestrator.toolkit.knowledge_tools import register_knowledge_tools
from orchestrator.toolkit.planning_tools import register_planning_tools
from orchestrator.toolkit.registry import ToolRegistry
from orchestrator.toolkit.router import ToolRouter


@dataclass
class Application:
    """The assembled orchestrator."""

    services: Services
    registry: ToolRegistry
    router: ToolRouter
    agent_loop: AgentLoop

    def create_tool_context(self, session_id: str, emit: EventEmitter) -> ToolContext:
        """Build the per-session tool context with its path allowlist."""
        session = self.services.store.get_session(session_id)
        allowlist = PathAllowlist(
            Path(session.workspace_path),
            [Path(folder) for folder in self.services.connected_folders],
        )
        return ToolContext(
            session_id=session_id,
            allowlist=allowlist,
            services=self.services,
            emit=emit,
        )


def build_application(
    settings: Settings | None = None, runtime: ModelRuntimeProtocol | None = None
) -> Application:
    """Wire the orchestrator together.

    Args:
        settings: Loaded configuration. Defaults to the repository's config.
        runtime: Model runtime. Tests pass a fake; production uses Foundry.
    """
    resolved_settings = settings or load_settings()
    data_directory = resolved_settings.data_directory
    gateway = ModelGateway(
        resolved_settings, runtime or FoundryCliRuntime(resolved_settings.gateway)
    )

    async def embed_texts(texts: list[str]) -> list[list[float]]:
        return (await gateway.embed(texts)).vectors

    services = Services(
        settings=resolved_settings,
        audit_log=AuditLog(data_directory / "audit"),
        store=SessionStore(data_directory / "sessions.sqlite"),
        gateway=gateway,
        skills=SkillIndex(resolved_settings.skills_directory),
        memory=MemoryStore(resolved_settings.memory_directory),
        sandbox=Sandbox(
            resolved_settings.sandbox,
            resolved_settings.builders_directory,
            resolved_settings.sandbox.are_host_builders_allowed,
        ),
        knowledge=KnowledgeIndex(data_directory / "knowledge.sqlite", embed_texts),
        connected_folders=[
            str(folder) for folder in resolved_settings.connected_folders
        ],
    )
    registry = ToolRegistry(resolved_settings.core_tool_names)
    register_file_tools(registry)
    register_planning_tools(registry)
    register_knowledge_tools(registry)
    register_document_tools(registry, resolved_settings.builders_directory)
    register_extraction_tool(registry)
    router = ToolRouter(registry)
    return Application(services, registry, router, AgentLoop(services, router))
