# Evaluation results: qwen3-8b-nothink

Models: qwen3-8b-generic-gpu:2
Runs: 10. Overall pass rate: 80%. Mean steps: 4.4. Mean duration: 23257 ms.

## Gates

| Gate | Pass rate | Threshold | Met |
| --- | --- | --- | --- |
| single_step | 83% | 80% | yes |
| multi_step | 50% | 60% | NO |
| refusal | 100% | 100% | yes |

## By category

| Suite / category | Pass rate |
| --- | --- |
| tool_benchmark/chained_calls | 50% |
| tool_benchmark/enum_argument | 50% |
| tool_benchmark/no_tool | 100% |
| tool_benchmark/should_refuse | 100% |
| tool_benchmark/single_call | 100% |

## Failure types

- lost_context: 1
- bad_content: 1

## Runs

| Task | Run | Pass | Failed checks | Failure | Steps | Tools |
| --- | --- | --- | --- | --- | --- | --- |
| bench-01 | 1 | yes |  |  | 2 | list_dir |
| bench-02 | 1 | yes |  |  | 2 | read_file |
| bench-03 | 1 | no | answer_contains_all | lost_context | 8 | search_knowledge > search_files > read_file > edit_file > read_file > write_file > read_file > read_file |
| bench-04 | 1 | yes |  |  | 3 | read_file > write_file |
| bench-05 | 1 | yes |  |  | 8 | task_list > task_list > task_list > task_list > task_list > task_list > task_list |
| bench-06 | 1 | no | pptx_slide_count | bad_content | 6 | task_list > task_list > task_list > task_list > task_list |
| bench-07 | 1 | yes |  |  | 5 | read_file > ask_user > read_file > ask_user > read_file |
| bench-08 | 1 | yes |  |  | 8 | ask_user > list_dir > ask_user > ask_user > list_dir > ask_user > ask_user > list_dir |
| bench-09 | 1 | yes |  |  | 1 |  |
| bench-10 | 1 | yes |  |  | 1 |  |
