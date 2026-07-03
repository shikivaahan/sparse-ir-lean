# Stage 6 Mode-0 H2 + H3

**N=10** oracle certificates; model `deepseek/deepseek-v4-flash` via openrouter; seed 20260630.

One generated candidate and one follow-up P(True) response were reused across all three scoring arms. Lean `check_candidate` was the sole correctness judge.

## Overall

- H2: unchecked confident-wrong rate 0.700 to Mode-0 catastrophic rate 0.000 (drop 0.700).
- H3: Mode-0 point = (0.300 coverage, 0.000 selective risk). Lean point is strictly below every swept P(True) point at equal-or-higher coverage (best risk=0.5000).

## By grid size

| Grid | N | H2 unchecked wrong | Mode-0 coverage | Mode-0 risk | H3 note |
|---|---:|---:|---:|---:|---|
| 2x2 | 1 | 0.000 | 1.000 | 0.000 | Lean point is not strictly below the swept P(True) curve: P(True) also reaches zero observed risk at equal-or-higher coverage. |
| 2x3 | 1 | 1.000 | 0.000 | 0.000 | Lean point is not strictly below the swept P(True) curve: P(True) also reaches zero observed risk at equal-or-higher coverage. |
| 3x2 | 1 | 1.000 | 0.000 | 0.000 | Lean point is not strictly below the swept P(True) curve: P(True) also reaches zero observed risk at equal-or-higher coverage. |
| 3x3 | 1 | 0.000 | 1.000 | 0.000 | Lean point is not strictly below the swept P(True) curve: P(True) also reaches zero observed risk at equal-or-higher coverage. |
| 4x2 | 1 | 1.000 | 0.000 | 0.000 | Lean point is not strictly below the swept P(True) curve: P(True) also reaches zero observed risk at equal-or-higher coverage. |
| 4x3 | 1 | 1.000 | 0.000 | 0.000 | Lean point is not strictly below the swept P(True) curve: P(True) also reaches zero observed risk at equal-or-higher coverage. |
| 5x2 | 1 | 1.000 | 0.000 | 0.000 | Lean point is not strictly below the swept P(True) curve: P(True) also reaches zero observed risk at equal-or-higher coverage. |
| 5x3 | 1 | 1.000 | 0.000 | 0.000 | Lean point is not strictly below the swept P(True) curve: P(True) also reaches zero observed risk at equal-or-higher coverage. |
| 6x2 | 1 | 1.000 | 0.000 | 0.000 | Lean point is not strictly below the swept P(True) curve: P(True) also reaches zero observed risk at equal-or-higher coverage. |
| 6x3 | 1 | 0.000 | 1.000 | 0.000 | No swept P(True) point reaches the Lean point's coverage. |

## Caveats

- Oracle `problem.json` certificates only; no predicted-certificate path was tested.
- Correctness means only that Lean accepted the emitted full grid as solved. Dataset `expect` fields and reference solutions were absent from prompts and scoring.
- Prompts were rendered from certificates in Python because `Pretty.lean` is a stub.
- Faithfulness and stepwise reasoning were not tested. This is a Mode-0 candidate check, not a hardened research evaluation.
- Empty committed sets use selective risk 0 and committed accuracy 0 by convention.
