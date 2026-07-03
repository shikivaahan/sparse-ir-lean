# stage6_h3_confidence

H3 (does Lean beat model self-confidence?) on the Stage 6 capability ladder. Confidence is P(True) elicited with reasoning OFF, exactly the v4-flash confidence protocol from `stage6_h5_cleanup` (answer-token cap = 1024, target cap per spec = 32; the cap was raised because Qwen models still emit reasoning under `effort: none` for the longer system+puzzle+confidence prompt and would burn a 32-token cap on reasoning alone, returning null content for 60+ rows on the harder puzzles). Lean verdicts are reused verbatim from the capability-ladder results; the candidates are also reused; no regeneration, no re-judging.

- Models: v4-flash (`deepseek/deepseek-v4-flash`), qwen3-32b (`qwen/qwen3-32b`), qwen3-8b (`qwen/qwen3-8b`).
- Total cost: $0.0837.

## H3 result (the headline)

On all three models, **the Lean operating point (coverage, 0% risk) sits below the best P(True) operating point at matched coverage.** The gap is small on the strong model (v4-flash), largest on the mid-capability model (qwen3-32b):

| model | Lean coverage | Lean risk | best P(True) at Lean coverage | P(True) risk | gap to Lean risk | high-conf wrong |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `v4-flash` | 98.0% | 0.0% | 13.8% (tau=0.05) | 0.0% | +0.0% | hc_wrong=0/18 (0.0%) |
| `qwen3-32b` | 73.0% | 0.0% | 74.1% (tau=0.55) | 9.3% | +9.3% | hc_wrong=13/139 (9.4%) |
| `qwen3-8b` | 63.5% | 0.0% | 99.0% (tau=0.05) | 35.1% | +35.1% | hc_wrong=18/31 (58.1%) |

## Per-model interpretation

- **v4-flash (strong model):** P(True) is *over-conservative* (mean 0.106, only 18/200 rows   with confidence >= 0.9). The P(True) curve never reaches Lean's 98% coverage because the model almost never says it's sure. Lean wins trivially because P(True) doesn't even try.
- **qwen3-32b (mid/large model):** P(True) is *over-confident* (mean 0.895, 139/200 rows with   confidence >= 0.9, of which 13/139 are *wrong*). The P(True) curve reaches 81.5% coverage   at 9.7% selective risk; at Lean's 73% coverage the best P(True) operating point still   carries **9.3% risk**. This is the clearest H3 win: same coverage, 0% risk vs ~10% risk.
- **qwen3-8b (small model):** P(True) is the *most over-confident* (mean 0.739, 31/200 rows with confidence >= 0.9, of which 18/31 are *wrong* = **58.1% wrong**). The P(True) curve reaches 99% coverage at 35.1% risk; Lean's 63.5% has 0% risk. The 35-percentage-point risk gap is the most dramatic of the three.

**Why this matters:** on the strong model P(True) is a poor abstention signal because the model is *under*-confident; on the weak model P(True) is a poor abstention signal because the model is *over*-confident. In the middle, P(True) reaches the same coverage as Lean but at non-trivial risk. The classic H3 thesis (Lean beats P(True)) is reproduced on all three rungs, and the verifier's value scales with the gap between P(True) and Lean.

## Per-model numbers

## `v4-flash` (`deepseek/deepseek-v4-flash`)

- Puzzles: 200 (parseable: 196; malformed skipped: 4; unparseable confidence: 0)
- Lean operating point: coverage = 98.0%, selective risk = 0.0 (n_committed = 196)
- Mean confidence: 0.106; median: 0.000
- High-confidence (>=0.9) rows: 18; wrong among them: 0 (0.0%)
- Best P(True) match at Lean's coverage: tau=0.05, coverage=13.8% (-84.2%), selective_risk=0.0% (gap to Lean risk = +0.0%).

## `qwen3-32b` (`qwen/qwen3-32b`)

- Puzzles: 200 (parseable: 189; malformed skipped: 11; unparseable confidence: 25)
- Lean operating point: coverage = 73.0%, selective risk = 0.0 (n_committed = 146)
- Mean confidence: 0.895; median: 1.000
- High-confidence (>=0.9) rows: 139; wrong among them: 13 (9.4%)
- Best P(True) match at Lean's coverage: tau=0.55, coverage=74.1% (+1.1%), selective_risk=9.3% (gap to Lean risk = +9.3%).

## `qwen3-8b` (`qwen/qwen3-8b`)

- Puzzles: 200 (parseable: 196; malformed skipped: 4; unparseable confidence: 2)
- Lean operating point: coverage = 63.5%, selective risk = 0.0 (n_committed = 127)
- Mean confidence: 0.739; median: 0.800
- High-confidence (>=0.9) rows: 31; wrong among them: 18 (58.1%)
- Best P(True) match at Lean's coverage: tau=0.05, coverage=99.0% (+35.5%), selective_risk=35.1% (gap to Lean risk = +35.1%).

## P(True) risk-coverage curves (parseable rows)

### `v4-flash`

| tau | coverage | selective_risk | n_committed | n_wrong |
| ---: | ---: | ---: | ---: | ---: |
| 0.05 | 13.8% | 0.0% | 27 | 0 |
| 0.10 | 13.8% | 0.0% | 27 | 0 |
| 0.15 | 13.8% | 0.0% | 27 | 0 |
| 0.20 | 12.2% | 0.0% | 24 | 0 |
| 0.25 | 11.7% | 0.0% | 23 | 0 |
| 0.30 | 11.2% | 0.0% | 22 | 0 |
| 0.35 | 11.2% | 0.0% | 22 | 0 |
| 0.40 | 11.2% | 0.0% | 22 | 0 |
| 0.45 | 10.7% | 0.0% | 21 | 0 |
| 0.50 | 10.7% | 0.0% | 21 | 0 |
| 0.55 | 10.2% | 0.0% | 20 | 0 |
| 0.60 | 10.2% | 0.0% | 20 | 0 |
| 0.65 | 9.7% | 0.0% | 19 | 0 |
| 0.70 | 9.7% | 0.0% | 19 | 0 |
| 0.75 | 9.7% | 0.0% | 19 | 0 |
| 0.80 | 9.7% | 0.0% | 19 | 0 |
| 0.85 | 9.7% | 0.0% | 19 | 0 |
| 0.90 | 9.2% | 0.0% | 18 | 0 |
| 0.95 | 9.2% | 0.0% | 18 | 0 |

### `qwen3-32b`

| tau | coverage | selective_risk | n_committed | n_wrong |
| ---: | ---: | ---: | ---: | ---: |
| 0.05 | 81.5% | 9.7% | 154 | 15 |
| 0.10 | 81.5% | 9.7% | 154 | 15 |
| 0.15 | 81.5% | 9.7% | 154 | 15 |
| 0.20 | 81.5% | 9.7% | 154 | 15 |
| 0.25 | 81.5% | 9.7% | 154 | 15 |
| 0.30 | 81.5% | 9.7% | 154 | 15 |
| 0.35 | 81.5% | 9.7% | 154 | 15 |
| 0.40 | 81.5% | 9.7% | 154 | 15 |
| 0.45 | 81.5% | 9.7% | 154 | 15 |
| 0.50 | 81.5% | 9.7% | 154 | 15 |
| 0.55 | 74.1% | 9.3% | 140 | 13 |
| 0.60 | 74.1% | 9.3% | 140 | 13 |
| 0.65 | 74.1% | 9.3% | 140 | 13 |
| 0.70 | 74.1% | 9.3% | 140 | 13 |
| 0.75 | 74.1% | 9.3% | 140 | 13 |
| 0.80 | 74.1% | 9.3% | 140 | 13 |
| 0.85 | 73.5% | 9.4% | 139 | 13 |
| 0.90 | 73.5% | 9.4% | 139 | 13 |
| 0.95 | 73.0% | 9.4% | 138 | 13 |

### `qwen3-8b`

| tau | coverage | selective_risk | n_committed | n_wrong |
| ---: | ---: | ---: | ---: | ---: |
| 0.05 | 99.0% | 35.1% | 194 | 68 |
| 0.10 | 99.0% | 35.1% | 194 | 68 |
| 0.15 | 99.0% | 35.1% | 194 | 68 |
| 0.20 | 99.0% | 35.1% | 194 | 68 |
| 0.25 | 99.0% | 35.1% | 194 | 68 |
| 0.30 | 99.0% | 35.1% | 194 | 68 |
| 0.35 | 99.0% | 35.1% | 194 | 68 |
| 0.40 | 99.0% | 35.1% | 194 | 68 |
| 0.45 | 99.0% | 35.1% | 194 | 68 |
| 0.50 | 99.0% | 35.1% | 194 | 68 |
| 0.55 | 70.9% | 42.4% | 139 | 59 |
| 0.60 | 70.9% | 42.4% | 139 | 59 |
| 0.65 | 70.9% | 42.4% | 139 | 59 |
| 0.70 | 70.9% | 42.4% | 139 | 59 |
| 0.75 | 70.9% | 42.4% | 139 | 59 |
| 0.80 | 70.9% | 42.4% | 139 | 59 |
| 0.85 | 23.0% | 62.2% | 45 | 28 |
| 0.90 | 15.8% | 58.1% | 31 | 18 |
| 0.95 | 7.7% | 73.3% | 15 | 11 |
