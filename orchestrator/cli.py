"""Terminal client for the agent (milestone M1).

Usage:
    python -m orchestrator.cli --workspace C:\\path\\to\\folder "your request"
    python -m orchestrator.cli                      (interactive)

Approval prompts and questions are asked on the terminal. `--auto-approve`
answers "allow once" to every approval and is intended for evaluation runs
only; tier policy and the path allowlist still apply.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from orchestrator.bootstrap import Application, build_application
from orchestrator.events import AgentEvent, EventType
from orchestrator.logging_setup import configure_logging
from orchestrator.toolkit.context import ToolContext

APPROVAL_ANSWERS = {"y": "allow_once", "s": "allow_session", "n": "deny"}


def _write(text: str) -> None:
    sys.stdout.write(text)
    sys.stdout.flush()


class TerminalRenderer:
    """Renders agent events and answers interaction requests from stdin."""

    def __init__(self, is_auto_approve: bool) -> None:
        self._is_auto_approve = is_auto_approve
        self._context: ToolContext | None = None
        self._pending_interactions: list[asyncio.Task[None]] = []

    def bind(self, context: ToolContext) -> None:
        """Attach the tool context whose broker receives the answers."""
        self._context = context

    def handle_event(self, event: AgentEvent) -> None:
        """Print one event. Interaction requests are answered asynchronously."""
        payload = event.payload
        if event.type == EventType.TEXT_DELTA:
            _write(str(payload["text"]))
        elif event.type == EventType.TOOL_CALL:
            _write(f"\n  [tool] {payload['summary']} (tier {payload['tier']})\n")
        elif event.type == EventType.TOOL_RESULT:
            _write(f"  [{payload['outcome']}] {payload['duration_ms']} ms\n")
        elif event.type == EventType.TASK_UPDATE:
            for task in payload["tasks"]:
                _write(f"  [{task['status']}] {task['title']}\n")
        elif event.type == EventType.ERROR:
            _write(f"\n  [error] {payload['message']} (trace {payload['trace_id']})\n")
        elif event.type == EventType.DONE:
            _write(f"\n  [done: {payload['reason']}] {payload['model_id']}\n")
        elif event.type in (EventType.APPROVAL_REQUEST, EventType.QUESTION):
            self._pending_interactions.append(
                asyncio.get_running_loop().create_task(self._answer(event))
            )

    async def _answer(self, event: AgentEvent) -> None:
        if self._context is None:
            return
        payload = event.payload
        if event.type == EventType.APPROVAL_REQUEST:
            request_id = str(payload["request_id"])
            if self._is_auto_approve:
                self._context.broker.resolve(request_id, "allow_once")
                return
            reply = await asyncio.to_thread(
                input,
                f"\n  Approve {payload['action']} on {payload['target']}? "
                "[y]es once / [s]ession / [n]o: ",
            )
            decision = APPROVAL_ANSWERS.get(reply.strip().lower()[:1], "deny")
            self._context.broker.resolve(request_id, decision)
            return
        options = ", ".join(str(option) for option in payload.get("options", []))
        reply = await asyncio.to_thread(
            input, f"\n  {payload['question']} ({options}): "
        )
        self._context.broker.resolve(str(payload["question_id"]), reply.strip())


async def run_prompt(
    application: Application, context: ToolContext, prompt: str
) -> str:
    """Run one turn and return the stop reason."""
    return await application.agent_loop.run_turn(context, prompt)


async def _main_async(arguments: argparse.Namespace) -> int:
    application = build_application()
    services = application.services
    workspace = Path(arguments.workspace).resolve() if arguments.workspace else None
    session = services.store.create_session(
        "Terminal session",
        services.settings.data_directory / "workspaces",
        existing_workspace=workspace,
    )
    renderer = TerminalRenderer(arguments.auto_approve)
    context = application.create_tool_context(session.session_id, renderer.handle_event)
    renderer.bind(context)
    _write(f"Workspace: {session.workspace_path}\n")
    if arguments.prompt:
        reason = await run_prompt(application, context, arguments.prompt)
        return 0 if reason == "answered" else 1
    while True:
        prompt = (await asyncio.to_thread(input, "\n> ")).strip()
        if prompt in ("exit", "quit"):
            return 0
        if prompt:
            await run_prompt(application, context, prompt)


def main() -> None:
    """Entry point for `python -m orchestrator.cli`."""
    parser = argparse.ArgumentParser(description="Local Cowork terminal agent")
    parser.add_argument("prompt", nargs="?", help="Run one request and exit")
    parser.add_argument("--workspace", help="Work in this folder")
    parser.add_argument(
        "--auto-approve",
        action="store_true",
        help="Answer every approval with allow-once (evaluation runs only)",
    )
    configure_logging()
    sys.exit(asyncio.run(_main_async(parser.parse_args())))


if __name__ == "__main__":
    main()
