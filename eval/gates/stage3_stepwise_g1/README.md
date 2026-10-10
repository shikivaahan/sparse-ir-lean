# Stage 3 stepwise G1 closure artifacts

This directory is the canonical evidence for the missing stepwise half of G1.

## Headline metrics

* Status: **PASS**
* Real/gold puzzles covered: 1,000
* Fuzzed puzzles covered: 10,000
* Total SAT-consistent states sampled: 139,846
* Total semantic step queries: 139,846
* Lean-accepted steps: 138,244
* Lean-rejected semantic steps: 1,602
* Global unsound accepts: **0**
* Local differential disagreements: **0**

See [`summary.md`](summary.md) for the full breakdown and
[`DESIGN.md`](DESIGN.md) for why the global and justification-local oracles
are reported separately.

## Tracked artifacts (committed)

| File | Purpose |
| --- | --- |
| `manifest.json` | Aggregated counters, provenance hashes, seed |
| `summary.md` | Human-readable headline metrics |
| `DESIGN.md` | Why the two oracles are separate and what they test |
| `config.json` | Gate configuration (seed, corpus counts, timeouts) |
| `coverage.json` | Per-rule and per-clue-type counts |
| `disagreements.jsonl` | Empty at freeze |
| `counterexamples.jsonl` | Empty at freeze |

## Regenerable artifacts (gitignored)

These are produced by the gate runner. They can be rederived from
`config.json` + the deterministic seed + the committed `eval/gates/stage2_gate_a_compile_all/compiled_problems.jsonl`
+ the fuzz generator (`src/sparseir_harness/fuzzed_puzzles.py`).

| File | Size on freeze | Purpose |
| --- | --- | --- |
| `fabricated_problems/` | 4.6 MB, 1000 files | Re-emitted `problem.json` files from the gold compiled corpus |
| `step_cases.jsonl` | 55 MB | Per-state proposed steps used as oracle input |
| `results.jsonl` | 284 MB | Per-case Lean verdict + global + local clingo verdicts |

## Reproduce

```bash
uv run python scripts/stage3_stepwise_g1.py \
    --config eval/gates/stage3_stepwise_g1/config.json \
    --output eval/gates/stage3_stepwise_g1
```

The runner is deterministic under the recorded seed (20260815) and clingo 5.8.0.
The Lean executable identity (sha256) and clingo version are recorded in
`manifest.json` under `corpus_provenance`.