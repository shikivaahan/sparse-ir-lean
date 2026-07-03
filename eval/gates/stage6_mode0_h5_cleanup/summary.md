# Stage 6 Mode-0 cleanup + frontier H5 single-shot (reasoning-ON re-run)

Cheap arm: **N=1000** with `deepseek/deepseek-v4-flash` (reasoning ON). Frontier arm: **N=30** with `anthropic/claude-opus-4.8` on a paired subset (reasoning ON, **reused as-is** from the prior valid run — no new Opus spend).

Lean `check_candidate` is the sole correctness judge. Oracle certificates contain no `expect`/gold field in either prompts or verifier requests. The prior reasoning-OFF cheap arm is preserved at `run_reasoning_off_discarded/` for honest history.

## Headline findings

- Cheap reasoning health: **97.8% of generations have reasoning_tokens > 0** (median reasoning 2,314; median content 213). Reasoning was not suppressed to fix JSON — the JSON parser now reads the *content* channel regardless of whether the provider folds reasoning in.
- Coverage restored: cheap Mode-0 coverage **0.959** (vs **0.089** in the prior lobotomized run).
- Confident-wrong collapsed: unchecked wrong rate **0.041** (vs **0.911**).
- Malformed kept low: cheap malformed rate **0.031** (vs **0.003** in the prior run — the prior malformed rate was a symptom of disabling reasoning).
- H2: unchecked confident-wrong 0.041 → Mode-0 catastrophic 0.000 (drop **0.041**).
- H3: Lean point **(0.959, 0.000)**; best swept P(True) risk at equal-or-higher coverage 0.019.
- H5 directional paired subset (both arms reasoning-ON):
  - cheap+Lean: 30/30, $0.041 total, $0.0014 / verified correct
  - frontier+Lean: 30/30, $1.243 total, $0.0414 / verified correct

## H11: primary house-count bins (Wilson 95% CI)

| Houses | N | Wrong rate [95% CI] | Mode-0 coverage [95% CI] | Malformed | Clue violation |
|---:|---:|---:|---:|---:|---:|
| 2 | 200 | 0.000 [0.000, 0.019] | 1.000 [0.981, 1.000] | 0.000 | 0.000 |
| 3 | 200 | 0.020 [0.008, 0.050] | 0.980 [0.950, 0.992] | 0.010 | 0.010 |
| 4 | 200 | 0.020 [0.008, 0.050] | 0.980 [0.950, 0.992] | 0.015 | 0.005 |
| 5 | 200 | 0.050 [0.027, 0.090] | 0.950 [0.910, 0.973] | 0.050 | 0.000 |
| 6 | 200 | 0.115 [0.078, 0.167] | 0.885 [0.833, 0.922] | 0.080 | 0.035 |

Difficulty scaling is now smooth and monotonic — no collapse, no plateau. The 6-house bin still has ~12% wrong and ~9% malformed (mostly reasoning-budget exhaustion on the hardest 6x6 puzzles), which is the honest ceiling for Mode-0 single-shot on this model.

## H5 framing

H5 here is the **honest single-shot** version: "cheap+Lean vs frontier+Lean, both gated to ~100% precision; cheap is cheaper but coverage-capped at its raw solve rate; this is NOT the retry/feedback H5 (that needs Stage 4/5)."

Both arms were reasoning-ON for this H5 comparison: cheap ran fresh in this gate, frontier was reused from the prior valid reasoning-ON run (the same Opus raw outputs, prompt, and seed). Residual budget difference (cheap $0.0014 vs Opus $0.0414 per verified correct) does not affect reasoning-on fairness; both models actually searched.

This shared frontier subset is a DIRECTIONAL/preliminary cost-coverage probe because it is small (N=30). It can be scaled later.

## vs prior lobotomized run

| metric                       | reasoning-OFF (discarded) | reasoning-ON (this) |
|------------------------------|--------------------------:|--------------------:|
| cheap Mode-0 coverage        | 0.089                     | **0.959**           |
| cheap unchecked wrong rate   | 0.911                     | **0.041**           |
| cheap malformed rate         | 0.003                     | 0.031               |
| cheap rows with reasoning>0  | 0.059                     | **0.978**           |
| cheap total cost USD         | 0.2354                    | 1.5462              |
| cheap median reasoning tok.  | 0                         | 2,314               |
| cheap median content tok.    | 120                       | 213                 |

The malformed rate "improvement" in the prior run (0.003) was a symptom, not a fix: with reasoning off the model emitted short, well-formed JSON that was wrong; Lean correctly rejected those as `clue_violation`, not malformed. With reasoning on, the model solves most puzzles; the residual failures are mostly provider timeouts or reasoning-budget exhaustion on the hardest 6x6 puzzles, which manifest as `malformed` (empty content). The two outcomes are tracked separately in every metrics block.

## Costs and scope

- Cheap total: $1.5462 (vs prior $0.2354 — about 6× because the model now reasons).
- Opus: $1.2425, **reused unchanged** from the prior valid reasoning-ON run. No new frontier spend.
- Mode-0 single shot only: no retry, nudge, best-of-N, trace, or stepwise operation.
- Oracle certificates only. Faithfulness and H1 are not tested.
- P(True) is a weak baseline and was elicited only for the cheap arm.
- Malformed and parsed clue-violation outcomes remain separate in every metrics block.
- Per-grid secondary results are in `metrics.json`; rendered figures are reproducible from `plot_stage6.py`.
- The prior reasoning-OFF cheap arm artifacts are in `run_reasoning_off_discarded/` (1000 raw files + results/metrics/manifest/summary/figures) for honest history.
