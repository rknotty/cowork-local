# Governance, security and audit

Status of every control in plan section 13. "Built" means the code exists and
has unit tests. "Verified" means it has been run on this device and evidence
is in `docs/evidence/`.

This is a proof of concept for one user on one device, processing the user's
own working files at OFFICIAL or below. It is not production-ready. See the
table at the end.

## Controls

| # | Control | Status | Where |
| --- | --- | --- | --- |
| 1 | Hash-chained, append-only audit log | Built and unit tested, including tamper detection | `orchestrator/audit.py`. Verify with `python -c "from orchestrator.audit import AuditLog; from pathlib import Path; print(AuditLog(Path('data/audit')).verify_chain())"` |
| 2 | Tracing | **Partial.** Structured JSON logs with a correlation ID per turn and per API request. No OpenTelemetry spans, because Agent Framework's middleware was the planned host (ADR 0002) | `orchestrator/logging_setup.py` |
| 3 | Egress block | Script written, **not applied**: needs an elevated prompt | `scripts/apply-egress-rules.ps1` |
| 4 | Egress proof | Script written, **not yet run** against a working orchestrator model | `scripts/test-egress.ps1` |
| 5 | Data at rest | BitLocker **unconfirmed** (needs elevation). `data/` is git-ignored. No credentials exist in config; `config/mcp.yaml` documents Credential Manager references | |
| 6 | Prompt injection defence | Built. Tool output is wrapped in `<tool_output>` delimiters and the system prompt treats it as data. Tier 3 approval is the real control. Five adversarial evaluation tasks | `agent_loop.wrap_untrusted`, `config/prompts.yaml`, `evals/tasks.yaml` |
| 7 | Human oversight | Built. Approval for writes outside the workspace and every tier 3 call; tier 3 cannot be approved "for the session"; stop button cancels the turn and every pending approval; builders label documents AI-assisted with the model ID | `toolkit/router.py`, `tools/builder_common.py` |
| 8 | Model register | Built | `docs/model-register.md` |
| 9 | Change control | Process defined below. Not automated | |

### Additional controls built

- **Locality check in code.** The gateway refuses any model endpoint that is not
  loopback (`model_runtime.assert_endpoint_is_local`), so a mistyped or tampered
  endpoint fails closed.
- **Path allowlist.** Canonical resolution before every check, so `..`,
  symlinks and junctions cannot escape. Tested with traversal and prefix-collision
  cases.
- **No deletion.** `remove_file` moves to `_to_delete/`, is tier 3, and needs
  approval every time.
- **Sensitive memory refused.** `save_memory` refuses credential-like content and
  special category personal data. The rule is hardcoded, not configuration.
- **Workspace files served sandboxed.** The API serves workspace files with
  `Content-Security-Policy: sandbox`, so an HTML artefact cannot run with the
  interface's privileges.
- **API bound to 127.0.0.1 only.** There is no authentication. Binding it
  anywhere else would expose an agent with file access to the network.

## Deviations from the plan

| Plan | This build | Why | To close |
| --- | --- | --- | --- |
| Tier 2 runs in the sandbox only | The repository's own builder scripts may run on the host while `are_host_builders_allowed: true` | WSL is not installed. Builders take a JSON specification, not code. `run_python` (generated code) never runs on the host | Run `scripts/setup-sandbox.ps1`, then set the flag to `false` |
| Agent Framework middleware | Hand-written loop | Not installable on Arm64 (ADR 0002) | Re-test when a new release ships |
| OpenTelemetry spans | Structured logs | As above | Add an OTel file exporter around `AgentLoop` and `ToolRouter` |
| Orchestrator about 20B | See the model register | gpt-oss-20b has no tool calling; qwen3-14b crashes the daemon | Re-test after Foundry Local updates |

## Change control

Any change to a model alias, `config/prompts.yaml`, a tool definition or a skill
must be followed by:

```powershell
.venv\Scripts\python.exe -m orchestrator.evaluation --label <change-name>
```

Compare `evals/results/latest-<change-name>.md` against the previous results
before using the change. A drop on the refusal gate (100%) blocks the change.

## Regulatory position

These are considerations to check, not legal advice.

- **UK GDPR.** Local processing removes the processor and international transfer
  questions. Controller duties remain. Memory files, the knowledge index and the
  session database are personal data stores if they hold information about
  people. The audit log stores hashes of content, not content, to minimise this.
  A DPIA is needed before processing other people's personal data at any scale.
- **EU AI Act.** Classification follows the use case. A general drafting assistant
  will usually carry transparency obligations only, which the AI-assisted
  document label supports. Pointing this at recruitment, eligibility or similar
  Annex III uses could make it high-risk. Assess each use case before a customer
  conversation.

## Proof of concept versus production

| Area | This build | Production also needs |
| --- | --- | --- |
| Users | One user, one device, no authentication | Authentication, per-user data separation, central policy |
| Operations | The user fixes it | Patching, a model update process, a support route, backup and restore |
| Security | Local controls, unit tested; egress and sandbox scripts not yet run | Independent review, device management, threat model sign-off |
| Run cost | No per-token charge | Engineering time to track a preview CLI and a moving catalogue. Estimate it before quoting anyone |
| Assurance | Synthetic evaluation set | Customer-specific evaluation, documented limits, an incident process |
