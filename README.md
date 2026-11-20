# Local Cowork

A local agent harness on Foundry Local: chat, a tool loop, skills, document
builders, knowledge search and memory, running on one laptop with no network
calls at run time.

**Status: proof of concept.** One user, one device, the user's own files at
OFFICIAL or below. See `docs/governance.md` for which controls are verified and
what production would also need. The build plan is
`Local Cowork on Foundry Local build plan.md`.

## Layout

| Folder | Contents |
| --- | --- |
| `orchestrator/` | Python service: model gateway, agent loop, tool router, stores, API, terminal client, evaluation runner |
| `web/` | React interface, served by the orchestrator from `web/dist` |
| `skills/` | Agent Skills (`SKILL.md` folders) |
| `tools/` | Deterministic document builders and their JSON schemas |
| `evals/` | Golden tasks, tool benchmark, adversarial cases, skill-trigger prompts, results |
| `config/` | `roles.yaml` (models), `tools.yaml` (policy), `prompts.yaml`, `mcp.yaml` (connectors) |
| `scripts/` | Sandbox setup, egress rules and egress proofs (PowerShell) |
| `docs/` | Event contract, governance, model register, Phase 0 findings, ADRs, evidence |
| `data/` | Run-time state: sessions, audit log, index, memory, workspaces. Git-ignored |

## Set up

Prerequisites: Windows 11 on Arm64, Foundry Local CLI, Python 3.12 Arm64,
Node.js LTS Arm64. Use Python 3.12: most dependencies have no Arm64 wheels for
newer versions yet.

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[dev]" python-docx python-pptx openpyxl markitdown
foundry model download <orchestrator alias from config/roles.yaml>
foundry model download qwen3-embedding-0.6b
foundry model download whisper-small
cd web; npm install; npm run build; cd ..
```

The interface's `package.json` is in `web/`, so run every `npm` command from
there. For normal use, run `npm run build` once and open the orchestrator at
`http://127.0.0.1:8765`.

For interface development only, run the orchestrator in one terminal and
`npm run dev` in `web/` in another, then open `http://127.0.0.1:5173`. Vite
forwards `/api` to `127.0.0.1:8765`. On Windows its file watcher can miss
rapid successive saves and serve a half-updated module; the page then shows
"Something went wrong". Restart `npm run dev` if that happens.

Download models as a deliberate step, then work offline.

## Run

```powershell
# Phase 1 check: chat, streaming, a tool call, embeddings, transcription
.venv\Scripts\python.exe -m orchestrator.smoke_test

# Terminal agent working in a folder
.venv\Scripts\python.exe -m orchestrator.cli --workspace C:\path\to\folder "Summarise the files here into summary.md"

# Interface and API: then open http://127.0.0.1:8765 in a browser.
# This serves the production build in web/dist; no dev server is needed.
.venv\Scripts\python.exe -m orchestrator.api

# Evaluation (writes evals/results/)
.venv\Scripts\python.exe -m orchestrator.evaluation --suite tool_benchmark --repeats 1
.venv\Scripts\python.exe -m orchestrator.evaluation            # everything, 3 runs each
```

## Logs

The orchestrator writes one JSON object per line to the console and to
`data\logs\orchestrator.log` (10 MB per file, the last ten kept). Successful
polling requests are left out so the log stays readable. Each indexing run
logs a start line, one `File indexed` line per file with its parse and embed
times, a progress line every 25 files, and a `Slow file indexed` warning for
any file over 30 seconds. Each conversation turn logs `Turn finished` with
its reason and duration.

The log holds file names from connected folders. It stays on this device,
beside the index that already holds their content; treat it with the same
care.

```powershell
# Follow the log as it is written
Get-Content data\logs\orchestrator.log -Wait -Tail 20

# Warnings and errors only
Get-Content data\logs\orchestrator.log | Select-String '"level": "(WARNING|ERROR)"'

# The Foundry Local daemon keeps its own log
foundry server logs -n 100
```

If the model service stops, the status bar says "Model service stopped" and
the orchestrator starts it again on the next message or indexing batch. It
will not restart it more than once a minute; repeated crashes are reported
instead. A daemon crash leaves an "Application Error" entry naming
`foundrylocald.exe` in the Windows Application event log.

## Develop

```powershell
.venv\Scripts\python.exe -m ruff check orchestrator tools
.venv\Scripts\python.exe -m ruff format orchestrator tools
.venv\Scripts\python.exe -m mypy orchestrator
.venv\Scripts\python.exe -m pytest --cov=orchestrator
```

Unit tests never touch Foundry Local, the network or WSL: the model is scripted
in `orchestrator/tests/conftest.py`.

## Changing the model

Edit the alias in `config/roles.yaml`, add a row to `docs/model-register.md`,
then run the full evaluation before use (`docs/governance.md`, change control).
