# Phase 0 findings: device, runtime and model spike

Recorded 2026-11-19 on the target device. Facts are observed on this machine
unless marked otherwise. Raw output is in `docs/evidence/`.

## Device

| Item | Observed |
| --- | --- |
| Device | Microsoft Surface Laptop Ultra, NVIDIA RTX Spark N1X (18-core CPU, 5120-core Blackwell GPU, plus an NVIDIA NPU) |
| OS | Windows 11 Pro, build 28000, Arm64 |
| Memory visible to Windows | 18.9 GB of 32 GB |
| GPU memory (driver-reported) | 12 GB (`HardwareInformation.qwMemorySize`) |
| Device management | Not domain, Entra ID or enterprise joined. Workgroup only. Not an SCC-managed device on this evidence |
| Power plan | Balanced. The plan recommends Best performance on mains power |
| BitLocker | Not confirmed: the query needs elevation. Check with `manage-bde -status C:` from an elevated prompt |
| WSL | Not installed. The sandbox (section 9) cannot be built until it is |

The plan assumed about half the memory would go to the GPU. On this device about
13 GB is reserved, so roughly 12 GB is available for model weights, KV cache and
embeddings together.

## Tooling

| Tool | Version | Notes |
| --- | --- | --- |
| Foundry Local CLI | 0.14.0 | Daemon serves an OpenAI-compatible API on a dynamic loopback port |
| Python | 3.12.10 Arm64 | Installed for this build. The pre-installed 3.15 has no Arm64 wheels for PyYAML, NumPy and others |
| Node.js | 26.13.1 Arm64 | |
| Git | 2.56.1 | |
| foundry-local-sdk | 2.5.0 | Installs and imports. In-process runtime, see ADR 0001 |
| agent-framework | Not installable | Transitive dependency has no Arm64 wheel, see ADR 0002 |
| MarkItDown | Installs | Used for PDF parsing only |
| sqlite-vec | Not used | See ADR 0003 |
| LibreOffice | Not installed on the host | Planned for the sandbox only |

## Runtime behaviour

- The daemon logs on every start: "Execution provider registration did not
  complete successfully. Failed: CUDAExecutionProvider." It continues with
  WebGPU and CPU. All catalogue GPU variants on this device are WebGPU or
  TensorRT RTX, so CUDA is not needed for them, but the warning should be raised
  with Microsoft if CUDA variants appear.
- Model downloads run inside the daemon. A daemon crash kills any download in
  progress. Do not test inference while a download runs.
- The network on this site dropped repeatedly during the session. Downloads
  resumed correctly and were verified (`.dlverified` markers present).

## Catalogue (tool-capable chat models only)

From `foundry model list` on this device. Full list in
`docs/evidence/2026-11-19-foundry-model-list.txt`.

| Alias | Size | Tools | Licence |
| --- | --- | --- | --- |
| qwen3-14b | 9.9 GB | yes | Apache-2.0 |
| qwen2.5-14b / qwen2.5-coder-14b | 8.8 GB | yes | MIT (catalogue metadata) |
| mistral-nemo-12b-instruct | 7.3 GB | yes | Apache-2.0 |
| qwen3.5-9b (multimodal) | 7.0 GB | yes | Apache-2.0 |
| qwen3-8b | 6.0 GB | yes | Apache-2.0 |
| gpt-oss-20b | 11.8 GB | **no** | MIT |

gpt-oss-20b, the plan's expected orchestrator for this tier, is in the catalogue
but does not list tool calling, so it cannot drive the agent loop. The largest
tool-capable model is qwen3-14b.

## Model spike results

| Model | Load | Generate | Notes |
| --- | --- | --- | --- |
| phi-4-reasoning (no tools) | yes | yes, 47 s for a short reply | Proves inference works on WebGPU here |
| qwen3-14b | yes, 16 s | **daemon crashes** on every request | Reproduced with Foundry's own `foundry complete`, so not caused by this code |
| qwen3-14b, context capped at 16K (BYOM copy) | yes | **daemon crashes** after 3.5 s | Rules out KV-cache size as the cause |
| qwen3-8b | yes | yes | All four Phase 1 smoke checks pass: streamed chat (13 to 28 s for a one-sentence answer, including the hidden reasoning phase), a correct tool call, embeddings and transcription. Evidence: `docs/evidence/2026-11-19-smoke-test-qwen3-8b.txt` |
| mistral-nemo-12b-instruct | not downloaded | | The download was killed by a daemon crash. Retry before the full model comparison |

## Transcription endpoint

Microsoft's REST reference documents `POST /v1/audio/transcriptions` as
`multipart/form-data`, compatible with OpenAI's API. The daemon in CLI 0.14.0
rejects that request with "Invalid JSON". The gateway therefore transcribes
through `foundry transcribe --file <path> -o json`, which works (under 1 s for a
one-second clip). Re-test the HTTP endpoint after each Foundry Local update.

## Qwen3 thinking mode

Foundry Local streams Qwen3's reasoning in a separate `reasoning_content` field,
not inline in the content. With the default settings, qwen3-8b reasons before
every step. Measured on one-word answers:

| Mode | Time |
| --- | --- |
| Default (thinking on) | 8.6 s |
| `/no_think` in the system message | 0.4 s |
| `chat_template_kwargs: {enable_thinking: false}` | 0.2 s, no reasoning generated |

In the first tool benchmark run (thinking on), a multi-step turn spent its whole
2,048-token output budget reasoning and ended with no answer. Thinking is
therefore off for the orchestrator and utility roles (`is_thinking_enabled:
false` in `config/roles.yaml`). Re-enable it per role only if the evaluation
shows it improves pass rates enough to justify the time.

## Harness fixes found by the first benchmark run

| Observed | Fix |
| --- | --- |
| The model called the same tool with the same arguments five times in a row | Identical repeat calls in a turn are not re-run; the model is told the result is already above. Counted against the repair allowance |
| A turn that ended with no visible answer was recorded as "answered" | Reported as `MODEL_GAVE_NO_ANSWER` |
| The model used `/` to mean "the workspace" and was refused | `/`, `\`, `.` and empty paths resolve to the workspace |
| `search_knowledge` was deferred behind `find_tool` | Now a core tool |
| Refusal checks failed a model that declined without trying | Refusal now passes when nothing outside the workspace was touched |

The qwen3-14b crash is a native fault in the daemon with no log entry after
"Daemon Ready". GPU memory does not rise before the crash. Raise it with
`foundry report` (which opens a pre-filled GitHub issue) once the user has
reviewed what that report contains.

A second native crash occurred on 2026-11-19 with qwen3-8b. A folder of about
1,000 files was indexing with qwen3-embedding-0.6b when a chat message loaded
qwen3-8b. The daemon died one second later. The Windows Application log
recorded an access violation (0xc0000005) in `onnxruntime_providers_webgpu.dll`
(WebGPU execution provider bundle 0.2.1), with nothing in `foundry server
logs`. The daemon was not restarted, so every later request failed. The
probable trigger is two models running on the WebGPU provider at once; this
is inferred from the timing, not reproduced. Mitigations: the gateway now
sends one load or inference request to the service at a time. It also starts
a stopped daemon (at most once a minute) and retries an embedding batch once
after a crash.

Follow-up on 2026-11-20. Indexing stalled again at the same file, a 159 KB
spreadsheet that chunks into 150 passages. Measured findings:

- In isolation the file embeds normally on WebGPU: 32 passages (51,043
  tokens) in 25 s, also with qwen3-8b loaded and after a 3,300-token chat.
  The CPU build of qwen3-embedding-0.6b is 3 to 7 times slower, and its
  vectors differ from the GPU build's (cosine 0.97 to 0.98), so it is not a
  substitute.
- Spreadsheet text tokenises at about 1.3 characters per token, against about
  6 for prose. A 32-passage spreadsheet batch is about 51,000 tokens.
- The device was memory-starved. Free RAM was 1.5 GB of 18.9 GB, 33.8 GB was
  committed, and paging ran at 11,000 to 28,000 pages a second. foundrylocald
  had 10.5 GB committed but only 1.9 GB resident, so model memory was in the
  page file. A fresh daemon commits 1.1 GB with the embedding model and
  7.4 GB with qwen3-8b as well. Unloading a model released nothing.
- CUDA is unavailable because the CUDA runtime is not installed
  (`onnxruntime_providers_cuda.dll`, error 126). The catalogue has no CUDA
  variants for this device anyway. TensorRT for RTX registers, but only older
  models (qwen2.5, phi, mistral, deepseek-r1 distills) have TensorRT builds;
  qwen3 and the embedding models are WebGPU or CPU only.

Changes: embedding requests are capped at 16,000 characters as well as 32
passages, and time out after 120 s. Operating advice: run large indexing
with the chat model unloaded (a fresh daemon) and other large applications
closed.

## Exit test status

The M0 exit test is "the orchestrator candidate answers your real tasks well
enough that you would use it for a first draft". That is a judgement only the
user can make, against their own tasks. The tool benchmark and golden tasks in
`evals/` give the measured half of it.
