# stage6_capability_ladder

Verdict: reduced 3-model capability ladder, Lean `check_candidate` sole judge.

- Models evaluated: qwen3-8b (`qwen/qwen3-8b`), qwen3-32b (`qwen/qwen3-32b`), v4-flash-baseline (`deepseek/deepseek-v4-flash`).
- Puzzles per model: 200 (same 200-puzzle balanced subset as the budget sweep).
- Total cost across all models: $1.4889.

## Provenance: historical wall time

Wall time is reported as `n/a` for any model whose result rows do not include persisted per-puzzle `started_at` / `ended_at` timestamps. Filesystem mtimes, Git commit times, and per-example `elapsed_seconds` sums are NOT substitutes for concurrent-run wall-clock duration, so no historical wall time or throughput is reconstructed for those runs. Future reruns of this gate write both timestamps on every result row.

- `qwen3-32b` (`qwen/qwen3-32b`): wall_time_status = `unavailable_missing_persisted_timestamps`.
- `v4-flash-baseline` (`deepseek/deepseek-v4-flash`): wall_time_status = `unavailable_missing_persisted_timestamps`.

## Capability ladder (sorted by coverage)

| label | model | role | coverage | solved/n | cost USD | cost/verified | median rsn | trunc | clue violation | malformed | tput ex/min | wall min |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| qwen3-8b | `qwen/qwen3-8b` | small | 64.0% | 128/200 | $0.6409 | $0.005007 | 3902 | 0 | 53 | 2 | 0.6 | 359.2 |
| qwen3-32b | `qwen/qwen3-32b` | mid_large | 73.0% | 146/200 | $0.5883 | $0.004030 | 3265 | 0 | 39 | 13 | n/a | n/a |
| v4-flash-baseline | `deepseek/deepseek-v4-flash` | cheap_frontier_baseline | 98.0% | 196/200 | $0.2596 | $0.001325 | 2501 | 2 | 0 | 4 | n/a | n/a |

## Coverage by house bin

| label | 2 | 3 | 4 | 5 | 6 |
| --- | --- | --- | --- | --- | --- |
| qwen3-8b | 35/40 | 34/40 | 28/40 | 18/40 | 13/40 |
| qwen3-32b | 30/40 | 37/40 | 32/40 | 27/40 | 20/40 |
| v4-flash-baseline | 40/40 | 40/40 | 39/40 | 39/40 | 38/40 |

## Coverage by grid

| label | 2x2 | 2x3 | 2x4 | 2x5 | 2x6 | 3x2 | 3x3 | 3x4 | 3x5 | 3x6 | 4x2 | 4x3 | 4x4 | 4x5 | 4x6 | 5x2 | 5x3 | 5x4 | 5x5 | 5x6 | 6x2 | 6x3 | 6x4 | 6x5 | 6x6 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| qwen3-8b | 8/8 | 7/8 | 6/8 | 7/8 | 7/8 | 7/8 | 8/8 | 7/8 | 5/8 | 7/8 | 7/8 | 6/8 | 6/8 | 5/8 | 4/8 | 7/8 | 6/8 | 1/8 | 3/8 | 1/8 | 7/8 | 5/8 | 1/8 | 0/8 | 0/8 |
| qwen3-32b | 4/8 | 6/8 | 8/8 | 7/8 | 5/8 | 7/8 | 8/8 | 7/8 | 8/8 | 7/8 | 7/8 | 7/8 | 7/8 | 5/8 | 6/8 | 7/8 | 8/8 | 4/8 | 5/8 | 3/8 | 8/8 | 7/8 | 3/8 | 0/8 | 2/8 |
| v4-flash-baseline | 8/8 | 8/8 | 8/8 | 8/8 | 8/8 | 8/8 | 8/8 | 8/8 | 8/8 | 8/8 | 8/8 | 8/8 | 7/8 | 8/8 | 8/8 | 8/8 | 8/8 | 8/8 | 7/8 | 8/8 | 8/8 | 8/8 | 8/8 | 8/8 | 6/8 |

## Solver-vs-budget band check (30-70%)

- `qwen3-8b` (qwen/qwen3-8b): 64.0%
- `qwen3-32b` (qwen/qwen3-32b): 73.0% (just above the 30-70% band, closest to the verifier-value region)

## Recommendation on expanding to the full 6-model ladder

- `v4-flash-baseline` is too easy (98.0%) — it will not stress the verifier.

## Readable samples

### `qwen3-8b` solved `zl_lgp-test-2x2-10`

Lean verdict: `ACCEPT_SOLVED/solved`.

Reasoning excerpt: (reasoning content unavailable; token metadata is retained)

### `qwen3-32b` solved `zl_lgp-test-2x2-10`

Lean verdict: `ACCEPT_SOLVED/solved`.

Reasoning excerpt: (reasoning content unavailable; token metadata is retained)

### `v4-flash-baseline` solved `zl_lgp-test-2x2-10`

Lean verdict: `ACCEPT_SOLVED/solved`.

Reasoning excerpt: (reasoning content unavailable; token metadata is retained)
