# Stage 6 Mode-0 H2 + H3

**N=200** oracle certificates; model `deepseek/deepseek-v4-flash` via openrouter; seed 20260630.

One generated candidate and one follow-up P(True) response were reused across all three scoring arms. Lean `check_candidate` was the sole correctness judge.

## Overall

- H2: unchecked confident-wrong rate 0.540 to Mode-0 catastrophic rate 0.000 (drop 0.540).
- H3: Mode-0 point = (0.460 coverage, 0.000 selective risk). Lean point is strictly below every swept P(True) point at equal-or-higher coverage (best risk=0.4970).
- Lean accepted 92/200 candidates; 48 outputs had no parseable JSON candidate.
- Usage: 286,665 input tokens and 491,336 output/reasoning tokens; provider-reported cost $0.16036.

## By grid size

| Grid | N | H2 unchecked wrong | Mode-0 coverage | Mode-0 risk | H3 note |
|---|---:|---:|---:|---:|---|
| 2x2 | 8 | 0.250 | 0.750 | 0.000 | Lean point is strictly below every swept P(True) point at equal-or-higher coverage (best risk=0.2500). |
| 2x3 | 8 | 0.000 | 1.000 | 0.000 | Lean point is not strictly below the swept P(True) curve: P(True) also reaches zero observed risk at equal-or-higher coverage. |
| 2x4 | 8 | 0.375 | 0.625 | 0.000 | Lean point is strictly below every swept P(True) point at equal-or-higher coverage (best risk=0.1667). |
| 2x5 | 8 | 0.250 | 0.750 | 0.000 | Lean point is strictly below every swept P(True) point at equal-or-higher coverage (best risk=0.2500). |
| 2x6 | 8 | 0.125 | 0.875 | 0.000 | Lean point is strictly below every swept P(True) point at equal-or-higher coverage (best risk=0.1250). |
| 3x2 | 8 | 0.375 | 0.625 | 0.000 | Lean point is strictly below every swept P(True) point at equal-or-higher coverage (best risk=0.3750). |
| 3x3 | 8 | 0.125 | 0.875 | 0.000 | Lean point is strictly below every swept P(True) point at equal-or-higher coverage (best risk=0.1250). |
| 3x4 | 8 | 0.375 | 0.625 | 0.000 | Lean point is strictly below every swept P(True) point at equal-or-higher coverage (best risk=0.2857). |
| 3x5 | 8 | 0.375 | 0.625 | 0.000 | Lean point is strictly below every swept P(True) point at equal-or-higher coverage (best risk=0.2000). |
| 3x6 | 8 | 0.750 | 0.250 | 0.000 | Lean point is strictly below every swept P(True) point at equal-or-higher coverage (best risk=0.6667). |
| 4x2 | 8 | 0.625 | 0.375 | 0.000 | Lean point is strictly below every swept P(True) point at equal-or-higher coverage (best risk=0.5000). |
| 4x3 | 8 | 0.750 | 0.250 | 0.000 | Lean point is strictly below every swept P(True) point at equal-or-higher coverage (best risk=0.7500). |
| 4x4 | 8 | 0.750 | 0.250 | 0.000 | Lean point is strictly below every swept P(True) point at equal-or-higher coverage (best risk=0.6667). |
| 4x5 | 8 | 1.000 | 0.000 | 0.000 | Mode-0 commits nothing; the H3 point-vs-curve comparison is uninformative. |
| 4x6 | 8 | 0.750 | 0.250 | 0.000 | Lean point is strictly below every swept P(True) point at equal-or-higher coverage (best risk=0.6667). |
| 5x2 | 8 | 0.500 | 0.500 | 0.000 | Lean point is strictly below every swept P(True) point at equal-or-higher coverage (best risk=0.3333). |
| 5x3 | 8 | 0.500 | 0.500 | 0.000 | Lean point is strictly below every swept P(True) point at equal-or-higher coverage (best risk=0.5000). |
| 5x4 | 8 | 0.750 | 0.250 | 0.000 | Lean point is strictly below every swept P(True) point at equal-or-higher coverage (best risk=0.6667). |
| 5x5 | 8 | 0.750 | 0.250 | 0.000 | Lean point is strictly below every swept P(True) point at equal-or-higher coverage (best risk=0.6667). |
| 5x6 | 8 | 0.625 | 0.375 | 0.000 | Lean point is strictly below every swept P(True) point at equal-or-higher coverage (best risk=0.6250). |
| 6x2 | 8 | 0.625 | 0.375 | 0.000 | Lean point is strictly below every swept P(True) point at equal-or-higher coverage (best risk=0.5714). |
| 6x3 | 8 | 0.625 | 0.375 | 0.000 | Lean point is strictly below every swept P(True) point at equal-or-higher coverage (best risk=0.5714). |
| 6x4 | 8 | 0.625 | 0.375 | 0.000 | Lean point is strictly below every swept P(True) point at equal-or-higher coverage (best risk=0.6250). |
| 6x5 | 8 | 0.750 | 0.250 | 0.000 | Lean point is strictly below every swept P(True) point at equal-or-higher coverage (best risk=0.6667). |
| 6x6 | 8 | 0.875 | 0.125 | 0.000 | Lean point is strictly below every swept P(True) point at equal-or-higher coverage (best risk=0.8571). |

## Caveats

- Oracle `problem.json` certificates only; no predicted-certificate path was tested.
- Correctness means only that Lean accepted the emitted full grid as solved. Dataset `expect` fields and reference solutions were absent from prompts and scoring.
- Prompts were rendered from certificates in Python because `Pretty.lean` is a stub.
- Faithfulness and stepwise reasoning were not tested. This is a Mode-0 candidate check, not a hardened research evaluation.
- Empty committed sets use selective risk 0 and committed accuracy 0 by convention.
- Unscored preflight responses and two transient transport-error attempts are retained in named subdirectories. The final metrics use 200 complete generation-plus-confidence response pairs.
