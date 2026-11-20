# ADR 0002: Hand-written agent loop instead of Microsoft Agent Framework

Status: accepted, 2026-11-19. Revisit when Agent Framework installs on Arm64.

## Context

The plan (section 7) prefers Microsoft Agent Framework for its middleware,
MCP support and transferability to customer work. It allows a hand-written loop
of about 200 lines "only if the framework hides too much when you need to repair
malformed tool calls", and asks to verify Arm64 support before committing.

## Finding

`pip install agent-framework` fails on Windows Arm64 Python 3.12 with binary-only
installs: `No matching distribution found for claude-agent-sdk<0.3,>=0.2.140`, a
transitive dependency with no Arm64 Windows wheel. The plan's verification step
therefore fails.

## Decision

`orchestrator/agent_loop.py` is a hand-written loop (about 250 lines). The
middleware concerns the framework would have hosted live in explicit places:

| Concern | Where |
| --- | --- |
| Approvals and tier policy | `toolkit/router.py`, `ToolRouter._decide_approval` |
| Audit | `audit.py`, written by the router and the loop |
| Repair of malformed calls | `toolkit/router.py`, `describe_repair`, and the loop's retry count |
| MCP | `mcp_client.py` |

## Consequences

- Repair behaviour is fully visible, which matters for a 14B-class model.
- Tracing is structured JSON logs with a correlation ID per turn, not
  OpenTelemetry spans. See docs/governance.md, control 2.
- Customer-transferable patterns are lost for now. If the framework later installs
  on Arm64, the router and audit modules map onto its middleware directly.
