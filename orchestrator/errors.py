"""Domain errors for the orchestrator.

Every error carries a stable machine-readable code. The API layer maps these
to the standard response shape (error, message, trace_id) and never exposes
the underlying exception text to a caller.
"""

from __future__ import annotations

from typing import Any


class OrchestratorError(Exception):
    """Base class for all orchestrator domain errors."""

    error_code = "ORCHESTRATOR_ERROR"
    safe_message = "The request could not be completed."

    def __init__(self, detail: str, **context: Any) -> None:
        self.detail = detail
        self.context = context
        super().__init__(detail)


class ConfigurationError(OrchestratorError):
    """A config file is missing, malformed or fails validation."""

    error_code = "CONFIGURATION_INVALID"
    safe_message = "The orchestrator configuration is invalid."


class GatewayUnavailableError(OrchestratorError):
    """Foundry Local could not be reached or did not answer in time."""

    error_code = "MODEL_GATEWAY_UNAVAILABLE"
    safe_message = "The local model service is not available."


class GatewayRequestError(OrchestratorError):
    """Foundry Local rejected a request (bad model, bad payload)."""

    error_code = "MODEL_REQUEST_REJECTED"
    safe_message = "The local model service rejected the request."


class NonLocalEndpointError(OrchestratorError):
    """The model endpoint is not on the loopback interface."""

    error_code = "MODEL_ENDPOINT_NOT_LOCAL"
    safe_message = "The model endpoint is not local. Refusing to send data."


class PathNotAllowedError(OrchestratorError):
    """A path resolves outside the folders the user connected."""

    error_code = "PATH_NOT_ALLOWED"
    safe_message = "That path is outside the folders connected to this session."


class ToolNotFoundError(OrchestratorError):
    """The model asked for a tool that is not registered."""

    error_code = "TOOL_NOT_FOUND"
    safe_message = "That tool does not exist."


class ToolArgumentsInvalidError(OrchestratorError):
    """Tool arguments are not valid JSON or fail the tool's schema."""

    error_code = "TOOL_ARGUMENTS_INVALID"
    safe_message = "The tool arguments are invalid."


class ToolDeniedError(OrchestratorError):
    """Policy or the user denied the tool call."""

    error_code = "TOOL_DENIED"
    safe_message = "That action was not approved."


class ToolExecutionError(OrchestratorError):
    """A tool ran and failed for a reason the model may be able to correct."""

    error_code = "TOOL_EXECUTION_FAILED"
    safe_message = "The tool could not complete the action."


class SandboxUnavailableError(OrchestratorError):
    """The WSL sandbox distribution is missing or not usable."""

    error_code = "SANDBOX_UNAVAILABLE"
    safe_message = "The code sandbox is not available on this device."


class SandboxTimeoutError(OrchestratorError):
    """Sandboxed code exceeded its wall-clock limit."""

    error_code = "SANDBOX_TIMEOUT"
    safe_message = "The sandboxed step took too long and was stopped."


class SkillNotFoundError(OrchestratorError):
    """No skill with that name is in the index."""

    error_code = "SKILL_NOT_FOUND"
    safe_message = "That skill does not exist."


class SessionNotFoundError(OrchestratorError):
    """No session with that identifier exists."""

    error_code = "SESSION_NOT_FOUND"
    safe_message = "That session does not exist."


class SensitiveContentError(OrchestratorError):
    """Content looks like a credential or special category data."""

    error_code = "SENSITIVE_CONTENT_REFUSED"
    safe_message = "That content looks sensitive and was not stored."


class AuditChainError(OrchestratorError):
    """The audit log hash chain does not verify."""

    error_code = "AUDIT_CHAIN_BROKEN"
    safe_message = "The audit log failed its integrity check."
