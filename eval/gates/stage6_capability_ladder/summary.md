# stage6_capability_ladder

Verdict: reduced 3-model capability ladder, Lean `check_candidate` sole judge.

- Models evaluated: qwen3-8b (`qwen/qwen3-8b`), qwen3-32b (`qwen/qwen3-32b`), v4-flash-baseline (`deepseek/deepseek-v4-flash`).
- Puzzles per model: 200 (same 200-puzzle balanced subset as the budget sweep).
- Total cost across all models: $1.4889.

## Capability ladder (sorted by coverage)

| label | model | role | coverage | solved/n | cost USD | cost/verified | median rsn | trunc | clue violation | malformed | tput ex/min | wall min |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| qwen3-8b | `qwen/qwen3-8b` | small | 64.0% | 128/200 | $0.6409 | $0.005007 | 3902 | 0 | 53 | 2 | 0.6 | 359.2 |
| qwen3-32b | `qwen/qwen3-32b` | mid_large | 73.0% | 146/200 | $0.5883 | $0.004030 | 3265 | 0 | 39 | 13 | 108634.2 | 0.0 |
| v4-flash-baseline | `deepseek/deepseek-v4-flash` | cheap_frontier_baseline | 98.0% | 196/200 | $0.2596 | $0.001325 | 2501 | 2 | 0 | 4 | 108062.8 | 0.0 |

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

Reasoning excerpt: Okay, let's try to solve this Zebra puzzle. First, I need to understand the given information. The puzzle has two categories: CarModel and Name. There are two houses, numbered 1 and 2. The clues provided are: Clue c1: The CarModel "ford f150" and Name "Arnold" are in the same house. Clue c2: The Name "Arnold" is found at house 1. So, starting with clue c2, since Arnold is in house 1, that means the Name category for house 1 is Arnold. Now, clue c1 says that Arnold (who is in house 1) is in the s

### `qwen3-32b` solved `zl_lgp-test-2x2-10`

Lean verdict: `ACCEPT_SOLVED/solved`.

Reasoning excerpt: Okay, let's try to solve this Zebra puzzle. The problem has two categories: CarModel and Name. The CarModel options are "ford f150" and "tesla model 3", while the Name options are "Eric" and "Arnold". There are two houses, numbered 1 and 2. Looking at the clues provided, the first one is c1: same_house for CarModel's "ford f150" and Name's "Arnold". That means wherever the ford f150 is, Arnold must be in the same house. The second clue, c2, says that Arnold is found at house 1. So from c2, Arnol

### `v4-flash-baseline` solved `zl_lgp-test-2x2-10`

Lean verdict: `ACCEPT_SOLVED/solved`.

Reasoning excerpt: We need to solve a small logic puzzle. The puzzle has 2 houses (1 and 2) and two categories: CarModel (ford f150, tesla model 3) and Name (Eric, Arnold). Clues: 1. (c1) same_house: ford f150 and Arnold are in the same house. 2. (c2) found_at: Arnold is at house 1. So from c2, Arnold is at house 1. Then c1 says ford f150 is in the same house as Arnold, so ford f150 is also at house 1. That means house 1 has Arnold and ford f150. Then house 2 must have the remaining: Eric and tesla model 3. Thus s
