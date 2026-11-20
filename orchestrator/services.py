"""The orchestrator's long-lived collaborators, built once at start-up."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from orchestrator.audit import AuditLog
from orchestrator.gateway import ModelGateway
from orchestrator.memory import MemoryStore
from orchestrator.settings import Settings
from orchestrator.skills import SkillIndex
from orchestrator.store import SessionStore

if TYPE_CHECKING:
    from orchestrator.knowledge.index import KnowledgeIndex
    from orchestrator.sandbox import Sandbox


@dataclass
class Services:
    """Shared dependencies handed to tools and the agent loop."""

    settings: Settings
    audit_log: AuditLog
    store: SessionStore
    gateway: ModelGateway
    skills: SkillIndex
    memory: MemoryStore
    sandbox: Sandbox
    knowledge: KnowledgeIndex
    # Folders the user connected at run time, on top of config/tools.yaml.
    connected_folders: list[str]
