# Stage 6 Mode-0 cleanup + frontier H5 single-shot

Cheap arm: **N=1000** with `deepseek/deepseek-v4-flash`. Frontier arm: **N=30** with `anthropic/claude-opus-4.8` on a paired subset.

Lean `check_candidate` is the sole correctness judge. Oracle certificates contain no `expect`/gold field in either prompts or verifier requests.

## Headline findings

- Malformed fix: cheap malformed rate fell from 0.240 to 0.003; frontier malformed rate 0.000.
- H2: unchecked confident-wrong 0.911 to Mode-0 catastrophic rate 0.000 (drop 0.911).
- H3: Lean point (0.089 coverage, 0.000 risk); best swept P(True) risk at equal-or-higher coverage 0.756.
- H5 directional paired subset: cheap coverage 0.133 at $0.0016/verified correct; frontier coverage 1.000 at $0.0414/verified correct.

## H11: primary house-count bins (Wilson 95% CI)

| Houses | N | Wrong rate [95% CI] | Mode-0 coverage [95% CI] | Malformed | Clue violation |
|---:|---:|---:|---:|---:|---:|
| 2 | 200 | 0.740 [0.675, 0.796] | 0.260 [0.204, 0.325] | 0.000 | 0.740 |
| 3 | 200 | 0.880 [0.828, 0.918] | 0.120 [0.082, 0.172] | 0.000 | 0.880 |
| 4 | 200 | 0.970 [0.936, 0.986] | 0.030 [0.014, 0.064] | 0.000 | 0.965 |
| 5 | 200 | 0.975 [0.943, 0.989] | 0.025 [0.011, 0.057] | 0.000 | 0.965 |
| 6 | 200 | 0.990 [0.964, 0.997] | 0.010 [0.003, 0.036] | 0.015 | 0.965 |

## H5 framing

H5 here is the HONEST single-shot version: "cheap+Lean vs frontier+Lean, both gated to ~100% precision; cheap is cheaper but coverage-capped at its raw solve rate; this is NOT the retry/feedback H5 (that needs Stage 4/5)."

This shared frontier subset is a DIRECTIONAL/preliminary cost-coverage probe because it is small. It can be scaled later.

## Costs and scope

- Cheap total: $0.2354.
- Opus probe projection: $1.2027 for N=30 vs the hard $5.00 ceiling; actual frontier total $1.2425.
- Mode-0 single shot only: no retry, nudge, best-of-N, trace, or stepwise operation.
- Oracle certificates only. Faithfulness and H1 are not tested.
- P(True) is a weak baseline and was elicited only for the cheap arm.
- Malformed and parsed clue-violation outcomes remain separate in every metrics block.
- Per-grid secondary results are in `metrics.json`; rendered figures are reproducible from `plot_stage6.py`.
