# Local Cowork on Foundry Local: build plan

Nov 18, 2026 · @Richard Knott

## 1. Verdict and scope

You can rebuild the harness on the laptop. You cannot rebuild the model. Plan around that gap and the project is worth doing; ignore it and you will ship a convincing shell that fails on the third tool call.

Copilot and Claude feel capable because a frontier model sits behind a well-built agent harness. The harness (interface, tool loop, skills, document builders, memory, approvals) is ordinary software and is fully reproducible with local inference, processing and data. The model is not. Your 32 GB device limits you to a model of around 20B parameters, which will follow short tool chains and lose the thread on long ones. Every design choice below compensates for that: narrower tools, smaller context, more structure, more checks.

| Capability | Local route | Parity you should expect |
| --- | --- | --- |
| Streaming chat | Foundry Local chat completions | High |
| Agent tool loop | Foundry Local tool calling | Partial. Plan for 2 to 4 step tasks on a 20B model, fragile beyond |
| Skills | SKILL.md folders, loaded on demand | High for format, partial for adherence |
| Word, PowerPoint, Excel and PDF creation | Builder tools and sandboxed code | Partial. Needs structured builders, not free-form code |
| Artefact preview pane | Sandboxed iframe | High |
| Folder access | Native file tools with an allowlist | High |
| Connectors | Local MCP servers | High for local systems. Any cloud connector breaks locality |
| Memory across sessions | Markdown files on disk | High |
| Search over your documents | Local embeddings and SQLite | High |
| Voice input | Whisper through Foundry Local | High |
| Scheduled tasks | Windows Task Scheduler calling the orchestrator | High |
| Parallel subagents | One GPU, so run sequentially | Low |
| Web search | Not local by definition | Optional toggle, off by default |
| Browser and desktop control | Vision model plus automation | Low. Defer |
| Microsoft 365 Graph grounding | No offline equivalent | None |

Three challenges before you start.

1. **Decide what this is for.** A personal tool, a demo and a sovereign offline assistant for public sector customers are three different builds. The third is the commercially interesting one, and its value sits in the governance layer, not the chat window. If that is the real target, say so now, because it changes Phase 8 from a tidy-up into the product.
2. **Do not build the chat interface first.** Microsoft documents [Open WebUI running against Foundry Local](https://learn.microsoft.com/azure/foundry-local/reference/reference-cli#use-open-webui-with-the-local-server). Use it for a one-evening spike to test model quality on your own tasks. Build the orchestrator next. Build your own interface last, once you know what it must show.
3. **Match the function, not the look.** Copy the interaction pattern (conversation, task list, preview pane, approval prompts). Give it its own name and visual identity. A lookalike of a Microsoft or Anthropic product is a problem the moment you show it to a customer.

This also competes with your other priorities. Timebox it. The milestones in section 15 are sized so you can stop after any one and still hold something usable.

## 2. Assumptions and decisions to confirm

Memory is confirmed at 32 GB and the plan is now sized for it. Five decisions remain open. I have assumed an answer for each so the plan is complete; change any of them and the affected sections are named.

| Decision | Assumed | If different |
| --- | --- | --- |
| Unified memory on your device | 32 GB, confirmed | Sections 4, 7, 9, 10 and 11 carry the limits this sets |
| Purpose | Personal working tool first, reusable as a demo | An SCC offering needs multi-user design, a support model and a product development review |
| Runtime strictness | Foundry Local only | Allowing a second runner widens the model choice. Section 4 explains the trade |
| Offline strictness | No network calls at run time | A web search toggle is a half-day addition in Phase 4 |
| Language | Python orchestrator, TypeScript interface | C# is equally well supported by the Foundry Local SDK |
| Data | Your own working files at OFFICIAL or below | Customer data on this device needs SCC security sign-off first |

- [ ] Record how much of the 32 GB the GPU gets: Task Manager, Performance, GPU, dedicated GPU memory
- [ ] Confirm whether the laptop is SCC-managed. Disabling Smart App Control, enabling WSL and changing the GPU memory split all need IT approval on a managed device
- [ ] Confirm the purpose, and whether a customer will ever see it
- [ ] Confirm whether a second model runner is acceptable

**Status of what you are building on.** The Foundry Local CLI is in [public preview](https://learn.microsoft.com/azure/foundry-local/reference/reference-cli). The 2.x SDK releases are not labelled preview on the [releases page](https://github.com/microsoft/Foundry-Local/releases), but confirm general availability in the docs before you describe this to anyone as production-ready. Treat the whole build as a proof of concept until section 13 and section 14 are complete.

## 3. Target architecture

Five components on one machine, with a single rule: only the model gateway talks to Foundry Local, and only the tool router touches files, code or connectors.

&#91;embedded content: target architecture · four layers on a governance base\]

Read it top down. The interface only renders events. The orchestrator owns every decision. The highlighted box is the one piece you do not build. The governance spine is not a later phase; each layer writes to it from its first version.

| Component | Technology | Why this choice |
| --- | --- | --- |
| Interface | React, TypeScript, Vite | Fast to iterate, packages to a desktop app later |
| Orchestrator | Python, FastAPI, Microsoft Agent Framework | Middleware for approvals and audit, MCP support, transferable to customer work |
| Model gateway | Foundry Local SDK plus the `openai` client | Microsoft's documented integration pattern |
| Sandbox | Dedicated WSL 2 distribution | Isolates generated code from the host |
| Stores | SQLite and plain files | No services to run, easy to inspect and back up |

## 4. Hardware and model selection

Memory decides everything. The Surface Laptop Ultra ships with [24 to 128 GB of unified memory](https://learn.microsoft.com/en-us/surface/tech-specs/surface-laptop-ultra-1stedition) on an Arm64 NVIDIA RTX Spark N1X, and Windows reserves a share of it for the GPU. Reviewers report a default even split, so a 128 GB machine gives the GPU roughly 62.5 GB ([StorageReview](https://www.storagereview.com/review/microsoft-surface-laptop-ultra-for-business-review-rtx-spark-n1x)).

| Unified memory | Model class that fits | What it means for this build |
| --- | --- | --- |
| 24 GB | 9B to 12B at 4-bit | Chat and single tool calls. Not a credible agent |
| 32 GB | Around 20B | Your device. Short agent tasks. Tight once embeddings and the sandbox are loaded |
| 64 GB | 27B to 35B | Comfortable for this project |
| 128 GB | Up to about 120B, heavily compressed | Headroom for a strong orchestrator plus helpers loaded together |

Sizing guidance from [i-SCOOP](https://www.i-scoop.eu/rtx-spark-n1x-laptops/). It is third-party and should be checked against your own device.

### Sizing for your 32 GB device

32 GB is workable for a constrained assistant and marginal for a Cowork-style agent. That is the plain reading, and it is better to design to it than to discover it in week three.

The memory is shared. Reviewers report the GPU takes about half by default, which would leave you roughly 16 GB for model weights, context cache and embeddings together, and roughly 16 GB for Windows, the orchestrator, the sandbox and everything else you have open. Confirm the real figure in Task Manager.

| Design point | Setting for 32 GB | Reason |
| --- | --- | --- |
| Orchestrator model | One model of around 20B. i-SCOOP names gpt-oss-20b as fitting this tier, and GPT-OSS is a listed Foundry Local family. Confirm the alias exists and lists `tools` | Largest class that fits |
| Fallback model | A 12B to 14B tool-capable model | Use it if the 20B leaves no room for context |
| Models loaded | One chat model at a time | No room for a second |
| Context window | Start at 16K tokens. Raise only after measuring memory at that size | Context cache grows with window size and comes out of the same pool |
| Embeddings | Smallest catalogue model. Run on CPU if the GPU is full | Search quality matters less than keeping the orchestrator loaded |
| Speech | Load on demand, unload straight after | Same pool |
| Sandbox | Cap WSL at 4 GB | The Windows side has little to spare |
| GPU memory split | Leave at default | Moving memory to the GPU starves Windows and the sandbox |

The context and sandbox figures are my starting values, not measured ones. Tune them in Phase 0.

**What you give up.** Long documents held in context, long tool chains, a second model for visual review and a large connector set. Retrieval replaces the first; the others are simply out of scope on this device.

**What still works.** Summarising, drafting, question answering over indexed documents, builder-based document creation from short specifications and short, tightly written skills.

**If that is not enough.** The gateway is the seam. Point it at a larger machine and the rest of the build is unchanged. That stops being a laptop-only system, so treat it as a separate decision.

**Catalogue caveat.** Foundry Local runs ONNX models from a curated catalogue covering Qwen, DeepSeek, Mistral, Phi and GPT-OSS families plus Whisper ([Microsoft Learn](https://learn.microsoft.com/azure/foundry-local/what-is-foundry-local)). Sources disagree on how large the catalogue goes on this chip. One developer write-up says it stops at small and mid-size models, with larger ones run through llama.cpp ([Imbery](https://dev.to/holgerimbery/local-ai-development-with-the-surface-laptop-ultra-13gk)). The only authority is `foundry model list` on your own machine. Do not pick models from this document.

### Roles, not models

Bind the application to four roles. Map each role to a catalogue alias in one config file, so changing a model is a one-line edit.

| Role | Job | Selection rule |
| --- | --- | --- |
| Orchestrator | Plans, calls tools, writes | Largest model that lists the `tools` task and leaves 30% of GPU memory free |
| Utility | Titles, summaries, context compaction, routing | On 32 GB, reuse the orchestrator. Add a separate small model only if it fits alongside |
| Embeddings | Document and memory search | Any catalogue text embedding model |
| Speech | Dictation and meeting audio | `whisper-small` or larger, per the [REST reference](https://learn.microsoft.com/azure/foundry-local/reference/reference-rest) |

### Selection steps

1. Run `foundry model list` and filter to rows whose Task column includes `tools`. Microsoft documents this as the [marker for tool calling support](https://learn.microsoft.com/azure/foundry-local/how-to/how-to-use-tool-calling-with-foundry-local).
2. Shortlist the three largest that fit your GPU share.
3. Run the ten-task tool benchmark in section 14 against each. Choose on task completion, not on tokens per second.
4. Record the model licence for each alias. Every model carries its own terms.
5. If nothing in the catalogue is strong enough, you have two routes. Compile a larger model to ONNX with [Olive](https://learn.microsoft.com/azure/foundry-local/how-to/how-to-compile-hugging-face-models) and register it through bring your own model, added in v2.1.0. Or accept a second OpenAI-compatible runner behind the same gateway. The first keeps you on one runtime and costs you a conversion project. The second is quicker and weakens the Foundry Local story.

**Known issue to watch.** The release notes list a first-load failure for TensorRT RTX models on RTX Spark when decoding is set to `top_k`. If a model fails on first load, check the sampling settings before anything else.

## 5. Phase 0: environment and model spike

This phase ends with a go or no-go on model quality before you write any application code. Allow one or two evenings.

1. **Patch the machine.** Run Windows Update until nothing remains, including optional driver updates. Update the RTX Spark driver from the NVIDIA app. Foundry Local needs [Windows 11 24H2 or later](https://learn.microsoft.com/windows/ai/foundry-local/get-started#prerequisites).
2. **Record the memory split.** Task Manager, Performance, GPU. Note dedicated GPU memory. Leave the split at default for now.
3. **Plug in and set Best performance.** Reviewers measured a 14% to 25% slowdown on battery.
4. **Install Arm64 tooling.** x64 builds run under emulation and cannot load GPU drivers, so force the architecture:

   ```powershell
   winget install --id Git.Git --architecture arm64
   winget install --id Python.Python.3.12 --architecture arm64
   winget install --id OpenJS.NodeJS.LTS --architecture arm64
   winget install Microsoft.FoundryLocal
   ```

   Close and reopen the terminal, then run `foundry --version`. Confirm in Task Manager's Architecture column that each process shows Arm64.
5. **Inspect the catalogue.**

   ```powershell
   foundry model list
   foundry server status
   ```

   Save the output to the repo. It is your evidence for section 4. Note that CLI 0.10 renamed several commands: `foundry server start`, `foundry run` and `foundry model show` replace the older `service` and `model run` forms you will see in blog posts.
6. **Run the largest tool-capable model.** `foundry run <alias>`, then hold a five-minute conversation. Check Task Manager to confirm the GPU is doing the work. If the CPU is pegged and the GPU idle, the wrong execution provider is in use; stop and fix that first.
7. **Run the spike.** Install Open WebUI, connect it to the endpoint from `foundry server status` following the [Microsoft steps](https://learn.microsoft.com/azure/foundry-local/reference/reference-cli#use-open-webui-with-the-local-server) and spend an hour on real work: summarise a tender document, draft an email, outline a deck.
8. **Install the sandbox host.** From an elevated terminal: `wsl --install -d Ubuntu-24.04`. Section 9 configures it.
9. **Create the repository.**

   ```text
   local-cowork/
     orchestrator/     Python service
     web/              React interface
     skills/           SKILL.md folders
     tools/            builder scripts run in the sandbox
     evals/            golden tasks and results
     config/           roles.yaml, tools.yaml, mcp.yaml
     data/             sessions, audit log, index (git-ignored)
   ```

**Exit test.** The orchestrator candidate answers your real tasks well enough that you would use it for a first draft. If it does not, stop. No amount of harness work will rescue a model that cannot do the base task.

## 6. Phase 1: inference layer

Build one module, the model gateway, that every other component calls. Nothing else in the codebase should know Foundry Local exists.

1. **Choose the integration mode.** Use the Foundry Local Python SDK to manage model download, load and unload, and start its OpenAI-compatible web service. Talk to that service with the standard `openai` client. Microsoft documents this pattern in [Integrate inference SDKs](https://learn.microsoft.com/azure/foundry-local/how-to/how-to-integrate-with-inference-sdks). Requires Python 3.11 or later: `pip install foundry-local-sdk openai`.
2. **Never hardcode the port.** The service takes a dynamic port unless you configure one. Read the endpoint from the SDK at start-up and bind it to 127.0.0.1 only.
3. **Write `config/roles.yaml`.** Four entries (orchestrator, utility, embeddings, speech), each with alias, context limit, temperature and maximum output tokens.
4. **Implement four gateway functions.** `chat(role, messages, tools, stream)`, `embed(texts)`, `transcribe(file)` and `health()`. Each returns token usage and latency for the audit log.
5. **Set tool choice to `auto`.** Microsoft rates `auto` and `none` as reliable across tool-calling models, and `required` or a named function as best effort.
6. **Handle the stateless API.** The HTTP layer keeps no conversation state, so the gateway resends history on every call. This is why context budgeting in Phase 2 matters.
7. **Manage memory explicitly.** Keep the orchestrator and embeddings models loaded. Load speech on demand and unload after use. Log GPU memory after each load.
8. **Pin versions.** Record the model ID and version returned at load time. Catalogue aliases can move to newer versions, which silently changes behaviour and invalidates your evaluations.
9. **Smoke test each endpoint.** One chat call, one streamed call, one tool call using the multiply example from the docs, one embeddings call, one transcription of a short WAV.

**Exit test.** A script prints a streamed answer, a correctly parsed tool call, a vector and a transcript, with timings, without touching the network. Disable Wi-Fi and run it again to prove it.

## 7. Phase 2: agent orchestrator

The orchestrator is the product. It is a local Python service (FastAPI) that runs the tool loop, manages context and emits events to the interface.

**Framework choice.** Use Microsoft Agent Framework with its OpenAI-compatible client pointed at the gateway. Its middleware layer is where approvals, audit and tracing attach, it has local MCP support, and Microsoft lists [local models among its Foundry integrations](https://learn.microsoft.com/agent-framework/integrations/). It is also the framework you will meet in customer work. The alternative is a hand-written loop of about 200 lines. Take that route only if the framework hides too much when you need to repair malformed tool calls. Verify the Python package supports Foundry Local on Arm64 before committing.

### Build steps

1. **Define the event stream.** One server-sent events endpoint per session. Event types: `text_delta`, `tool_call`, `tool_result`, `approval_request`, `task_update`, `artefact`, `error`, `done`. Fix this contract first; the interface depends on it.
2. **Assemble the system prompt in layers.** Identity and rules, then the tool list, then the skill index (names and one-line descriptions only), then memory, then the working folder listing. Measure the token count of each layer.
3. **Run the loop.** Send messages and tools. If the reply has tool calls, validate arguments against the JSON schema, execute through the tool router, append results, repeat. Stop on a plain answer, a step limit of 8, or cancellation.
4. **Repair bad calls.** Local models produce malformed JSON and invented tool names. On a validation failure, return a short error naming the fault and the valid options, and allow two retries before surfacing the failure. v2.1.0 improved recovery from malformed calls, but do not rely on it.
5. **Budget the context.** Reserve fixed shares: 15% system, 25% tools and skills, 45% conversation, 15% output. With a 16K window, truncate tool results over 1,000 tokens to a head, a tail and a file reference. When conversation passes its share, have the utility model compact older turns into a summary.
6. **Add a planning tool.** A `task_list` tool the model calls to write and tick off steps. This gives the interface its progress panel and tends to steady weaker models on multi-step work.
7. **Add `ask_user`.** A tool that pauses the loop and renders a question with options. Cheaper than letting the model guess.
8. **Persist sessions.** SQLite: sessions, messages, tool calls, artefacts. Every row carries the model ID and version.
9. **Run sequentially.** One GPU means one generation at a time. Queue requests. Do not attempt parallel subagents; if you need delegation, run a sub-task as a fresh context in series and return only its summary.

**Exit test.** From a terminal client: "read the three files in this folder and write a one-page summary to summary.md" completes without intervention on eight of ten runs.

## 8. Phase 3: the interface

A React and TypeScript single-page app, built with Vite and served by the orchestrator on 127.0.0.1. Keep it a browser app until it is stable. Package it as a desktop app later with Tauri, which uses the WebView2 runtime already on Windows and has native Arm64 builds.

### Layout

| Region | Contents |
| --- | --- |
| Left rail | Session list, new session, folder picker, skills browser, settings |
| Centre | Conversation: streamed text, collapsible tool-call cards, approval prompts, question cards |
| Right panel | Tabs for task list, artefact preview and files changed this session |
| Composer | Text box, file attach, microphone, role and model indicator, stop button |
| Status bar | Model loaded, tokens per second, context used, network state (should read Offline) |

### Build steps

1. **Stream rendering.** Subscribe to the event endpoint. Render `text_delta` as markdown with code highlighting. Batch updates to animation frames or long answers will stutter.
2. **Tool-call cards.** Collapsed by default: tool name, one-line argument summary, status, duration. Expand for full arguments and result. This is your transparency story in a demo.
3. **Approval prompts.** Inline card with the exact action, the target path or command and three buttons: allow once, allow for this session, deny. The loop blocks until answered.
4. **Task list panel.** Driven by `task_update` events from the planning tool.
5. **Artefact preview.** Render HTML and SVG in an iframe with `sandbox="allow-scripts"` and a content security policy that blocks all network requests. Render markdown natively. For Word, PowerPoint and Excel output, show the PDF or image render produced in section 11 with an Open in Office button.
6. **File handling.** Drag and drop copies files into the session workspace. Show a diff view for edited text files.
7. **Model and role indicator.** Show which model answered each turn. Make the model version visible on hover. Auditors and sceptical technical leads both look for this.
8. **Voice input.** Record in the browser, post the audio to the orchestrator, insert the transcript into the composer for review before sending.
9. **Accessibility pass.** Keyboard navigation, focus order, contrast at WCAG 2.1 AA. Do this before any customer sees it.

**Exit test.** A colleague who has used Copilot completes a three-step task with no instruction from you.

## 9. Phase 4: tools, sandbox and connectors

Every tool call passes through one router that checks its tier, asks for approval where needed, executes, logs and returns. No tool is callable any other way.

### Tool tiers

| Tier | Examples | Default policy |
| --- | --- | --- |
| 0 Read | `read_file`, `list_dir`, `search_files`, `search_knowledge` | Automatic inside allowed folders |
| 1 Write | `write_file`, `edit_file`, `save_memory` | Automatic inside the session workspace, approval elsewhere |
| 2 Execute | `run_python`, `run_shell`, builder tools | Sandbox only, never on the host |
| 3 External | MCP tools that reach other systems, web search, deletion | Approval every time |

### Build steps

1. **Write the core tools.** Keep the set under 10; every definition costs context you do not have. Each needs a verb-first name, a two-sentence description and a strict JSON schema with enums wherever possible. Small models choose tools from descriptions, so vague descriptions are the main cause of wrong calls.
2. **Enforce a path allowlist.** Resolve every path to its canonical form, reject anything outside the folders the user connected, and reject symlinks that escape. Deny deletion by default; move files to a `_to_delete` folder instead.
3. **Build the sandbox.** Create a dedicated WSL 2 distribution used for nothing else. In its `/etc/wsl.conf`, disable Windows drive automount and Windows interop so code inside cannot see or launch anything on the host. The orchestrator copies inputs in and outputs out through the `\\wsl.localhost` share. Install Python and the document libraries from section 11 once, then export the distribution as a clean image you can restore.
4. **Restrict the sandbox.** Run as a non-root user. Apply a wall-clock timeout of 120 seconds and a 4 GB memory cap in `.wslconfig`. Block outbound network from the distribution with a Hyper-V firewall rule. Verify that rule on Arm64 by attempting a download from inside; I have not confirmed its behaviour on this device.
5. **Add the MCP client.** Read `config/mcp.yaml`, start each listed server as a local stdio process and register its tools at tier 3 until you reclassify them by hand. Only allowlisted servers start. Each server is third-party code with your file permissions, so review it before adding it.
6. **Defer tool definitions.** Twenty MCP tools can consume a quarter of a local model's context. Expose a single `find_tool` tool that searches tool descriptions by keyword and loads matching schemas on demand.
7. **Optional web search.** If you allow it, make it a tier 3 tool behind a visible toggle, and change the status bar to Online while it is enabled. Leave it out of the first build.

**Exit test.** Ask the agent to delete a file outside the workspace, to fetch a URL from the sandbox and to read `C:\Users`. All three are refused and logged.

## 10. Phase 5: skills

Use the open [Agent Skills](https://agentskills.io) format unchanged. A skill is a folder with a `SKILL.md` at its root plus optional scripts and reference files. Microsoft Foundry [uses the same format](https://learn.microsoft.com/azure/foundry/agents/how-to/tools/skills), so skills you write here move to cloud agents and back.

The pattern is progressive disclosure in three stages: advertise names and descriptions, load the body when relevant, read supporting files on demand. It matters more locally than in the cloud because your context window is smaller and slower to fill.

### Build steps

1. **Scan at start-up.** Walk `skills/`, parse the YAML front matter of each `SKILL.md` and build an index of name, description and path. Reject any skill whose front matter fails validation.
2. **Advertise within a budget.** Inject the index into the system prompt, capped at about 800 tokens. If you exceed it, shorten descriptions or switch to search (step 6).
3. **Add `load_skill(name)`.** Returns the body of `SKILL.md` as a tool result. Instruct the model in the system prompt to load a matching skill before starting the task.
4. **Add `read_skill_file(name, path)`.** Returns a reference file from inside the skill folder. Constrain the path to that folder.
5. **Run skill scripts in the sandbox only.** Copy the skill's `scripts/` folder into the sandbox at session start. Skills are executable instructions; treat a skill from an unknown source like an unknown executable.
6. **Add skill search for larger libraries.** Past 30 skills, replace the full index with `find_skill(query)` over embedded descriptions.
7. **Port your own library first.** Your SCC skills are already in this format. Start with two that have clear inputs and outputs. Expect to rewrite them: instructions tuned for a frontier model are usually too long and too implicit for a 30B model. Shorten, number the steps and move judgement into checklists.
8. **Check licences before copying third-party skills.** Some published skills, including vendor document skills, are source-available and not open for reuse. Write your own document skills against the builders in section 11.
9. **Test triggering.** For each skill write five prompts that should load it and five that should not. Record the hit rate per model in `evals/`.

**Exit test.** A ported skill loads without being named in the prompt on at least four of five matching requests, and the output follows its numbered steps.

## 11. Phase 6: document creation

This is where the local model gap bites hardest, and where the design must differ from the cloud products. Frontier models write 300 lines of correct document-generation code in one pass. A local model will not do that reliably. So do not ask it to.

**Design rule: the model writes a specification, your code writes the file.** Each builder tool accepts a constrained JSON document and produces the output deterministically. The model's job shrinks to content and structure, which it can do.

| Output | Builder tool | Library in the sandbox | Model supplies |
| --- | --- | --- | --- |
| Word | `build_docx` | python-docx with a house template | Headings, paragraphs, tables, lists as JSON |
| PowerPoint | `build_pptx` | python-pptx with a fixed set of named layouts | Slide list: layout name, title, bullets, notes |
| Excel | `build_xlsx` | openpyxl | Sheets, headers, rows, formulas as strings |
| PDF | `build_pdf` | Convert the Word output | Nothing extra |
| Web page | `write_file` | None | Self-contained HTML |
| Diagram | `write_file` | None | Mermaid or SVG source |

### Build steps

1. **Define the schemas.** One JSON schema per builder. Keep each small: eight slide layouts, five block types for Word. Reject anything outside the schema with a specific error.
2. **Write the builders.** Plain Python scripts in `tools/`, run in the sandbox. Styling comes from a template file, never from the model.
3. **Add a render step.** After every build, convert the result to PDF and to page images inside the sandbox using LibreOffice in headless mode. The interface previews these.
4. **Add automated checks.** Deterministic first: file opens, page or slide count matches the specification, no empty placeholders, no text box overflowing its bounds. Return failures to the model as a tool result so it can correct the specification.
5. **Add visual review if you have a vision-capable model.** Foundry Local 2.0.1 added image inputs. Pass the page image and ask for layout faults. Skip this on 32 GB; there is no room for a second model.
6. **Support editing existing files.** Add `read_docx`, `read_pptx` and `read_xlsx` tools that return structure as JSON, and a `patch` mode on each builder that changes named elements only. Always write to a new file beside the original.
7. **Keep a free-form escape hatch.** `run_python` remains available for cases the builders cannot express. Expect a lower success rate and say so in the interface.
8. **Write one skill per document type.** Each tells the model when to use the builder, how to plan content before calling it and what the checks will test.

**Exit test.** "Turn these meeting notes into a six-slide deck" produces a file that opens in PowerPoint with no manual repair on four of five runs.

## 12. Phase 7: knowledge and memory

Two separate stores with different jobs. Knowledge is your documents, indexed for search. Memory is a small set of facts about you and your work, loaded into every session.

### Knowledge search

1. **Parse.** Convert Word, PowerPoint, Excel, PDF and HTML to markdown. Microsoft's open-source MarkItDown library covers these formats; confirm it installs on Arm64 Python before depending on it.
2. **Chunk.** Split on headings, target 400 to 600 tokens with a 50-token overlap, and keep the heading path and source file with each chunk.
3. **Embed.** Call the gateway's `embed` function. Foundry Local exposes `/v1/embeddings` through an `EmbeddingsSession` added in 2.0.1. The equivalent Azure Local documentation limits ONNX embedding requests to 32 strings of 8,192 characters; assume similar limits and batch accordingly.
4. **Store.** One SQLite file holding chunks, an FTS5 keyword index and vectors through the sqlite-vec extension. Check that sqlite-vec ships an Arm64 Windows build; if not, a brute-force cosine search in NumPy is fast enough below about 100,000 chunks.
5. **Retrieve.** Run keyword and vector search together, merge with reciprocal rank fusion and return the top six chunks with file path and heading.
6. **Cite.** The `search_knowledge` tool result carries source paths. Require the model to cite them and render citations as links that open the file.
7. **Keep the index current.** Watch connected folders, re-index changed files by hash and remove chunks for deleted files.

### Memory

1. **Use plain markdown files.** A `memory/` folder: a profile, preferences and one file per ongoing project. Human-readable, editable and diffable.
2. **Load selectively.** Profile and preferences go into every system prompt. Project files load only when the conversation matches their one-line description.
3. **Write deliberately.** A `save_memory` tool at tier 1, used when you ask it to remember something. Avoid automatic background memory writes in the first build; a small model will file noise.
4. **Make it inspectable.** A memory page in the interface listing every file with edit and delete.
5. **Exclude sensitive categories.** Hardcode a rule in the tool: no credentials, no health or other special category data about anyone.

**Exit test.** Index a folder of 50 documents. Ten factual questions with known answers return the right source in the top three results for at least eight.

## 13. Phase 8: governance, security and audit

"It runs locally" is a claim. Governance is what turns it into evidence. For a buyer who sees audit and controls as cost, the argument is simple: without them you cannot prove that nothing left the device, which is the only reason to accept a weaker model in the first place.

Start the audit log in Phase 2, not here. This phase completes and tests the controls.

### Controls to build

1. **Audit log.** Append-only JSON lines in `data/audit/`. One record per model call and per tool call: timestamp, session, model ID and version, input hash, tool name, arguments, tier, approval decision, result hash, tokens, duration. Chain each record to the previous one with a hash so tampering is detectable.
2. **Tracing.** Emit OpenTelemetry spans from the orchestrator middleware to a local file or local collector. Configure no cloud exporter.
3. **Egress block.** A Windows Firewall outbound rule denying the orchestrator process, plus the sandbox rule from section 9. Model downloads are the one legitimate network use; run them as a separate, deliberate step and then go offline.
4. **Egress proof.** A test that runs a full agent task with Wi-Fi on while capturing connections, and fails if any are attempted. Keep the output as evidence.
5. **Data at rest.** Confirm BitLocker is on. Restrict the `data/` folder to your user. Store any MCP credentials in Windows Credential Manager, never in config files or the repository.
6. **Prompt injection defence.** Treat every document, tool result and MCP response as untrusted. Wrap them in clear delimiters, instruct the model that their contents are data, and rely on tier 3 approvals as the real control. A local model is more easily steered by injected text than a frontier one.
7. **Human oversight.** Approvals for tiers 1 to 3 as defined, a visible stop button and no unattended external actions. Label generated documents as AI-assisted in their properties.
8. **Model register.** A table of every model used: alias, version, source, licence, date added and evaluation score. Models registered through bring your own model need a recorded provenance check.
9. **Change control.** Any change to a model, system prompt, tool or skill triggers the evaluation suite in section 14 before use.

### Regulatory position

These are considerations to check, not legal advice.

- **UK GDPR.** Local processing removes the processor and international transfer questions. It does not remove controller duties. If the tool processes personal data, lawful basis, minimisation, retention and, for higher-risk uses, a DPIA still apply. Memory and the knowledge index are both personal data stores if they hold information about people.
- **EU AI Act.** Classification follows the use case, not where inference runs. A general assistant will usually carry transparency obligations only. Point the same tool at recruitment screening or eligibility decisions and it can become high-risk. Assess each use case separately before a customer conversation.

### Proof of concept versus production

| Area | What this plan delivers | What production also needs |
| --- | --- | --- |
| Users | One user, one device | Authentication, per-user data separation, central policy |
| Operations | You fix it when it breaks | Patching, model update process, support route, backup and restore |
| Security | Local controls you tested yourself | Independent review, device management, threat model sign-off |
| Run cost | No per-token charge. Your time, the device and power | Engineering time to track a preview CLI and a moving catalogue is the real cost. Estimate it before quoting anyone |
| Assurance | Your own evaluation set | Customer-specific evaluation, documented limits, incident process |

## 14. Phase 9: evaluation

Build the evaluation set in Phase 0 and run it at every milestone. Without it you will tune by feel and mistake a good demo run for a working system.

1. **Write 30 golden tasks from your real work.** Six categories of five: question answering over documents, summarising, drafting, multi-step file tasks, document creation and skill-driven tasks. Use synthetic or anonymised content only.
2. **Define a pass check for each.** Prefer deterministic checks: file exists, contains required headings, cites the right source, tool sequence includes the expected call. Use a rubric scored by you for writing quality.
3. **Write the ten-task tool benchmark.** A subset used for model selection in section 4: single call, two chained calls, a call needing an enum, a call that should be refused, a task needing no tool at all.
4. **Add adversarial cases.** Five prompt injection documents, five out-of-scope path requests and five requests that should trigger a clarifying question.
5. **Build the runner.** A script that replays every task against the orchestrator three times, records pass rate, steps taken, tokens, duration and failure type, and writes a dated results file.
6. **Record a cloud baseline once.** Run the same tasks through a frontier model. This gives you an honest, quantified statement of the gap, which is more persuasive to a technical lead than a claim of parity.
7. **Set thresholds.** Suggested starting gates, to adjust once you have data: 80% on single-step tasks, 60% on multi-step tasks, 100% refusal on adversarial path and egress cases.
8. **Classify failures.** Wrong tool, malformed call, lost context, bad content, sandbox error. The distribution tells you whether to fix the prompt, the tool design or the model choice.

**Exit test.** A single command produces a results table for the current build, and you can state the local-versus-cloud gap as a number.

## 15. Build sequence and effort

Six milestones, each usable on its own. Effort figures are my planning estimates for one person working part-time with a coding assistant, around eight to ten hours a week. They are not commitments and will move with model quality.

| Milestone | Scope | You can stop here with | Estimate |
| --- | --- | --- | --- |
| M0 Spike | Phase 0, first ten golden tasks | A go or no-go on local model quality | 1 to 2 evenings |
| M1 Terminal agent | Phases 1 and 2, core file tools, audit log | A command-line agent that works on your folders | 2 weeks |
| M2 Skills and documents | Phases 5 and 6, sandbox | Skill-driven Word, PowerPoint and Excel output | 2 to 3 weeks |
| M3 Interface | Phase 3 | Something you can demonstrate | 2 weeks |
| M4 Knowledge and connectors | Phase 7, MCP client | Search over your documents, local connectors | 1 to 2 weeks |
| M5 Hardening | Phases 8 and 9 completed | Evidence pack: audit, egress proof, evaluation results | 1 to 2 weeks |

The order is deliberate. The interface comes fourth because it is the most visible and least risky part. If you start there, which is the natural temptation when moving fast, you will have a polished shell before you know whether the agent underneath can finish a task.

M5 is the milestone most likely to be skipped under time pressure and the one that makes this worth showing to a budget holder. If the purpose is an SCC offering, bring M5 forward and run the idea through the product development stages before investing past M3.

On 32 GB, M0 is a real gate and not a formality. If a 20B model cannot complete your first ten golden tasks to first-draft standard, stop at M0 and decide between a narrower tool, a larger machine behind the gateway or shelving it. Do not carry on to M1 hoping the harness will close the gap.

## 16. Risks and facts to verify

| Risk | Likelihood | Mitigation |
| --- | --- | --- |
| Catalogue models too weak for multi-step agent work | High | M0 go or no-go. Bring your own model through Olive, or a second runner behind the gateway |
| Foundry Local on Arm64 RTX Spark falls back to CPU or fails to load | Medium | Check GPU use in Phase 0 step 6. Watch the TensorRT RTX `top_k` known issue |
| Preview CLI changes break scripts | High | Use the SDK for everything the application does. Use the CLI for inspection only |
| Python packages lack Arm64 Windows wheels | Medium | Test each dependency in Phase 0. Move anything awkward into the WSL sandbox |
| Context overflow on long sessions | High | Budgets, truncation and compaction from section 7 |
| Sandbox escape or data leak through a tool | Low, high impact | Tiers, allowlists, egress block and the adversarial tests |
| Managed-device policy blocks WSL or unsigned binaries | Medium | Raise with IT before Phase 0 |
| Scope creep toward full parity | High | Stop at any milestone. Browser control and parallel agents stay out of scope |

### Verify on your device before relying on it

- [ ] Which catalogue aliases exist, which list the `tools` task and how large they go
- [ ] Which execution provider Foundry Local selects on the N1X. I found no first-party statement
- [ ] Whether the 2.x SDK is generally available
- [ ] The current Foundry Local version. The releases page showed v2.1.0 as latest when read, while one search result referred to a later version with larger models. I could not reconcile the two
- [ ] Microsoft Agent Framework Python support for a Foundry Local endpoint on Arm64, and its skills provider
- [ ] Arm64 builds of sqlite-vec, MarkItDown and LibreOffice
- [ ] Hyper-V firewall behaviour for WSL on this device
- [ ] How the GPU memory split is changed. Only reviewer reports describe it

### Sources

Read on 18 November 2026.

- [Surface Laptop Ultra tech specs](https://learn.microsoft.com/en-us/surface/tech-specs/surface-laptop-ultra-1stedition), Microsoft Learn
- [What is Foundry Local?](https://learn.microsoft.com/azure/foundry-local/what-is-foundry-local), Microsoft Learn
- [Get started with Foundry Local](https://learn.microsoft.com/windows/ai/foundry-local/get-started), Microsoft Learn
- [Foundry Local CLI reference](https://learn.microsoft.com/azure/foundry-local/reference/reference-cli), Microsoft Learn
- [Foundry Local REST API reference](https://learn.microsoft.com/azure/foundry-local/reference/reference-rest), Microsoft Learn
- [How to use tool calling with Foundry Local](https://learn.microsoft.com/azure/foundry-local/how-to/how-to-use-tool-calling-with-foundry-local), Microsoft Learn
- [Compile Hugging Face models to run on Foundry Local](https://learn.microsoft.com/azure/foundry-local/how-to/how-to-compile-hugging-face-models), Microsoft Learn
- [Foundry Local architecture overview](https://learn.microsoft.com/azure/foundry-local/concepts/foundry-local-architecture), Microsoft Learn
- [Use skills in Foundry (preview)](https://learn.microsoft.com/azure/foundry/agents/how-to/tools/skills), Microsoft Learn
- [Agent Framework integrations](https://learn.microsoft.com/agent-framework/integrations/), Microsoft Learn
- [Foundry Local releases](https://github.com/microsoft/Foundry-Local/releases), GitHub
- [Local AI Development with the Surface Laptop Ultra](https://dev.to/holgerimbery/local-ai-development-with-the-surface-laptop-ultra-13gk), Holger Imbery. A personal write-up, not vendor documentation
- [Surface Laptop Ultra for Business review](https://www.storagereview.com/review/microsoft-surface-laptop-ultra-for-business-review-rtx-spark-n1x), StorageReview
- [RTX Spark laptops and memory](https://www.i-scoop.eu/rtx-spark-n1x-laptops/), i-SCOOP
