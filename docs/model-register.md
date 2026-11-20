# Model register

Every model this build uses or has evaluated (plan section 13, control 8). The
model ID includes the catalogue version; an alias can move to a new version, so
the ID is what results and audit records refer to.

Licences are as reported by the Foundry Local catalogue metadata on 2026-11-19.
Check each against the model's own licence file before any use beyond
personal evaluation.

| Role | Alias | Model ID | Source | Licence | Added | Status | Evaluation |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Orchestrator (planned) | qwen3-14b | qwen3-14b-generic-gpu:2 | Foundry catalogue | Apache-2.0 | 2026-11-19 | **Unusable**: daemon crashes on generation | n/a |
| Orchestrator (experiment) | qwen3-14b-16k | qwen3-14b-16k:1 | Local registration of the catalogue model above, context capped at 16K. Provenance: hard link to the verified catalogue weights, only `genai_config.json` lengths changed | Apache-2.0 | 2026-11-19 | **Unusable**: same crash. Unregistered and its folder deleted on 2026-11-19 | n/a |
| Orchestrator and utility | qwen3-8b | qwen3-8b-generic-gpu:2 | Foundry catalogue | Apache-2.0 | 2026-11-19 | **In use** from 2026-11-19. Phase 1 smoke test passes | `evals/results/latest-qwen3-8b.md` |
| Orchestrator candidate | mistral-nemo-12b-instruct | mistral-nemo-12b-instruct-generic-gpu:1 | Foundry catalogue | Apache-2.0 | 2026-11-19 | Not downloaded (daemon crash ended the download) | pending |
| Embeddings | qwen3-embedding-0.6b | qwen3-embedding-0.6b-generic-gpu:1 | Foundry catalogue | Apache-2.0 | 2026-11-19 | In use. Smoke test passes | pending |
| Speech | whisper-small | openai-whisper-small-generic-cpu:4 | Foundry catalogue | Apache-2.0 | 2026-11-19 | In use, loaded on demand, via the CLI (see findings). Smoke test passes | pending |

Not used, recorded because it was considered:

| Alias | Why not |
| --- | --- |
| gpt-oss-20b | No tool calling in catalogue metadata |
| phi-4-reasoning | No tool calling. Was loaded on the device before this build; unloaded to free GPU memory |
