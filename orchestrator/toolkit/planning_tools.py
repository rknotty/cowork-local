"""Planning and interaction tools: task_list, ask_user and find_tool.

`task_list` gives the interface its progress panel and tends to steady weaker
models on multi-step work. `ask_user` is cheaper than letting the model guess.
`find_tool` keeps deferred tool definitions out of the context until needed.
"""

from __future__ import annotations

from typing import Any

from orchestrator.errors import ToolExecutionError
from orchestrator.events import AgentEvent, EventType
from orchestrator.toolkit.context import PlannedTask, ToolContext
from orchestrator.toolkit.registry import (
    ToolDefinition,
    ToolOutput,
    ToolRegistry,
    ToolTier,
    object_schema,
)

TASK_STATUSES = ["pending", "in_progress", "done"]
MAX_TASKS = 8
MAX_QUESTION_OPTIONS = 4


async def task_list(context: ToolContext, arguments: dict[str, Any]) -> ToolOutput:
    """Create the plan, or update the status of one step."""
    action = arguments["action"]
    if action == "create":
        titles = arguments.get("titles") or []
        if not titles:
            raise ToolExecutionError("action 'create' needs a non-empty titles list")
        context.tasks = [
            PlannedTask(id=index, title=title)
            for index, title in enumerate(titles[:MAX_TASKS], start=1)
        ]
    else:
        task_id = arguments.get("task_id")
        matching_task = next(
            (task for task in context.tasks if task.id == task_id), None
        )
        if matching_task is None:
            valid_ids = [task.id for task in context.tasks]
            raise ToolExecutionError(
                f"no task with id {task_id}. Valid ids: {valid_ids}"
            )
        matching_task.status = arguments.get("status", "done")
    context.emit_task_update()
    rendered = "\n".join(
        f"{task.id}. [{task.status}] {task.title}" for task in context.tasks
    )
    return ToolOutput(rendered)


async def ask_user(context: ToolContext, arguments: dict[str, Any]) -> ToolOutput:
    """Pause the loop on a question and return the user's answer."""
    question_id, future = context.broker.open_request()
    context.emit(
        AgentEvent(
            EventType.QUESTION,
            {
                "question_id": question_id,
                "question": arguments["question"],
                "options": arguments.get("options", [])[:MAX_QUESTION_OPTIONS],
            },
        )
    )
    # Cancellation (the stop button) must propagate: catching it here would
    # turn "stop" into a tool result and let the loop carry on.
    answer = await future
    return ToolOutput(f"The user answered: {answer}")


def make_find_tool(registry: ToolRegistry) -> ToolDefinition:
    """Build `find_tool`, bound to the registry it searches."""

    async def find_tool(context: ToolContext, arguments: dict[str, Any]) -> ToolOutput:
        matches = registry.search_deferred(arguments["query"])
        if not matches:
            available = ", ".join(
                definition.name for definition in registry.deferred_definitions()
            )
            return ToolOutput(f"No tool matched. Other tools available: {available}")
        for definition in matches:
            context.discovered_tool_names.add(definition.name)
        listing = "\n".join(
            f"- {definition.name}: {definition.description}" for definition in matches
        )
        return ToolOutput(f"These tools are now available to call:\n{listing}")

    return ToolDefinition(
        name="find_tool",
        description=(
            "Search for extra tools by keyword, such as 'word document', "
            "'spreadsheet', 'memory' or 'knowledge search'. Matching tools "
            "become callable on your next step."
        ),
        parameters=object_schema(
            {"query": {"type": "string", "minLength": 2}}, ["query"]
        ),
        tier=ToolTier.READ,
        handler=find_tool,
    )


def register_planning_tools(registry: ToolRegistry) -> None:
    """Register task_list, ask_user and find_tool."""
    registry.register(
        ToolDefinition(
            name="task_list",
            description=(
                "Plan multi-step work and track progress. Call with action "
                "'create' and titles first, then 'update' with task_id and "
                "status as you start and finish each step."
            ),
            parameters=object_schema(
                {
                    "action": {"type": "string", "enum": ["create", "update"]},
                    "titles": {
                        "type": "array",
                        "items": {"type": "string"},
                        "maxItems": MAX_TASKS,
                    },
                    "task_id": {"type": "integer", "minimum": 1},
                    "status": {"type": "string", "enum": TASK_STATUSES},
                },
                ["action"],
            ),
            tier=ToolTier.READ,
            handler=task_list,
        )
    )
    registry.register(
        ToolDefinition(
            name="ask_user",
            description=(
                "Ask the user one short question when the request is ambiguous "
                "or a needed detail is missing. Offer up to four options."
            ),
            parameters=object_schema(
                {
                    "question": {"type": "string", "minLength": 5},
                    "options": {
                        "type": "array",
                        "items": {"type": "string"},
                        "maxItems": MAX_QUESTION_OPTIONS,
                    },
                },
                ["question"],
            ),
            tier=ToolTier.READ,
            handler=ask_user,
        )
    )
    registry.register(make_find_tool(registry))
