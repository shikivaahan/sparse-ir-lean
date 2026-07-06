# Stage 4 trace-parser gate

Status: **PASS**

- Traces: 3028
- Full-candidate traces: 1000
- Stepwise traces: 2000 (1000 clue-based + 1000 bijection-based)
- Parse-error coverage: 26/26
- Protocol errors: 0
- Failures: 0

Stage 4 core parser: PASS

## Provider trace-shape diagnostics

| Diagnostic | Model | Samples | TRACE_PARSED | Status |
|---|---|---|---|---|
| `provider_validation/raw_outputs.jsonl` (stored) | deepseek/deepseek-v4-flash | 140 | 140 (100%) | pass (reparse, parseability only) |
| `provider_adversarial/raw_outputs.jsonl` (stored) | deepseek/deepseek-v4-flash | 120 adversarial + 140 positive | 120 rejected + 140 parsed | pass (reparse) |
| `provider_stepwise/raw_outputs.jsonl` (this freeze) | deepseek/deepseek-v4-flash | 36 | 20 (55.5%) | partial (parseability only) |

The stepwise diagnostic enforces the new public justification contract: the
prompt explicitly forbids the 22 private kernel rule names. 0 out of 36 raw
outputs leaked a forbidden rule name. The 13 `unknown_op` rejections are
the model forgetting the `op` discriminator field on some objects — the
parser-rejection path is functioning as designed.

The core gate parses and lowers trace JSON only. Provider trace-shape
diagnostics are reported separately and do not replay operations, check
trace correctness, score puzzle answers, retry requests, or perform
solver/search work in Lean.
