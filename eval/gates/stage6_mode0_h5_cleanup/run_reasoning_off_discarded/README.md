# Reasoning-OFF discarded run (preserved for honest history)

This subdirectory preserves the prior reasoning-OFF Stage 6 Mode-0 cheap arm artifacts (committed as part of the Stage 6 cleanup gate before the truncation fix). The run has been SUPERSEDED by the corrected reasoning-ON run in the parent directory. It is kept here so the comparison is auditable.

## Why it was discarded

The prior run disabled the cheap model's reasoning (`reasoning.effort=none`) to dodge JSON parse failures. That measured a lobotomized model:

- 941/1000 generations had `reasoning_tokens=0` (the model's `reasoning` field was null)
- Median output 120 tokens
- Mode-0 coverage collapsed to 8.9% (vs the reasoning-ON baseline of ~46%)
- It violated the project's thesis: the cheap model must DO THE SEARCH; Lean only checks it.

The fix (in `src/sparseir_harness/stage6_h5_cleanup.py`) lets the model reason with a generous `reasoning.max_tokens=24000` budget and a large `max_tokens=32768` answer cap, and `extract_candidate` continues to take the last fenced ```json block or the last top-level {...} from the content channel — never from reasoning content.

## What is in here

- `results.jsonl` — the 1000-row reasoning-OFF cheap results + 30 frontier rows (untouched by the new run)
- `metrics.json`, `manifest.json`, `summary.md` — the reasoning-OFF metrics
- `h2_*.png`, `h3_*.png`, `h5_*.png`, `h11_*.png` — the reasoning-OFF figures
- `prompt_template.txt` — the old prompt (lobotomized)
- `raw/cheap_mode0__*.json` — the 1000 prior reasoning-OFF raw provider outputs

## What is NOT here

- `uniqueness.jsonl` and `prepared.json` — unchanged from the parent (oracle verification)
- `opus_cost_gate.json` — reused by the new run as-is
- Frontier raw outputs — reused by the new run as-is (both arms reasoning-ON for H5)

## Headline comparison (vs the new reasoning-ON run in parent)

| metric                    | reasoning-OFF (this dir) | reasoning-ON (parent) |
|---------------------------|-------------------------:|----------------------:|
| cheap Mode-0 coverage     | 0.089                    | 0.959                 |
| cheap malformed rate      | 0.003                    | 0.031                 |
| cheap rows reasoning>0    | 0.059                    | 0.978                 |
| cheap total cost USD      | 0.2354                   | 1.5462                |
| cheap wrong rate (unchecked) | 0.911                 | 0.041                 |

The malformed rate "improvement" in the prior run was a symptom, not a fix: with reasoning off the model produced short, well-formed JSON that was wrong, which Lean correctly rejected as `clue_violation`. With reasoning on, the model solves more puzzles and the residual failures are mostly timeouts / reasoning-budget exhaustion, which manifest as malformed (no JSON in content channel).
