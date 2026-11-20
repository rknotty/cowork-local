# Evaluation results: diag

Models: qwen3-8b-generic-gpu:2
Runs: 1. Overall pass rate: 0%. Mean steps: 2.0. Mean duration: 134407 ms.

## Gates

| Gate | Pass rate | Threshold | Met |
| --- | --- | --- | --- |
| single_step | 0% | 80% | NO |

## By category

| Suite / category | Pass rate |
| --- | --- |
| tool_benchmark/single_call | 0% |

## Failure types

- wrong_tool: 1

## Runs

| Task | Run | Pass | Failed checks | Failure | Steps | Tools |
| --- | --- | --- | --- | --- | --- | --- |
| bench-01 | 1 | no | tool_called | wrong_tool | 2 | list_dir |
