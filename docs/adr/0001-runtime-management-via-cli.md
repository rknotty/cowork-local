# ADR 0001: Manage Foundry Local through the CLI daemon, not the in-process SDK

Status: accepted, 2026-11-19. Revisit when the SDK's daemon-client mode is confirmed.

## Context

The plan (section 6, step 1) says to use the Foundry Local Python SDK for model
download, load and unload, and the standard `openai` client for inference.

Findings on this device during Phase 0:

- `foundry-local-sdk` 2.5.0 installs and imports on Arm64 Python 3.12. It did not
  install on Python 3.15, for which most dependencies have no Arm64 wheel.
- SDK 2.5.0 describes itself as "in-process Python bindings for the Foundry Local
  native runtime". It loads ONNX Runtime into the calling process.
- The CLI (0.14.0) runs a separate daemon that serves the OpenAI-compatible API
  and already holds loaded models.

## Decision

`orchestrator/model_runtime.py` manages models through `foundry ... -o json`
against the daemon. Inference goes through the daemon's OpenAI-compatible
endpoint, which `model_runtime` reads from `foundry server status` at start-up
and refuses unless it is on loopback.

## Reasons

- Using the in-process SDK alongside the daemon would load a second copy of a
  model. The GPU share on this device is about 12 GB, which holds one.
- Only `model_runtime.py` knows how Foundry Local is managed. Swapping to the SDK
  later is a change to one module behind `ModelRuntimeProtocol`.

## Consequences

- The plan's risk register says to use the CLI "for inspection only" because it
  is in preview and its commands change. This decision accepts that risk for
  four commands (`server status`, `model list`, `model load`, `model unload`),
  all called with `-o json`, all behind one module with tests for its parsing.
- If a CLI update changes the JSON shape, `model_runtime` raises
  `GatewayRequestError` naming the command, rather than misbehaving.
