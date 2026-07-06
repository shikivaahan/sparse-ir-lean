# Stage 4 trace-parser gate

Status: **PASS**

- Traces: 3028
- Full-candidate traces: 1000
- Stepwise traces: 2000 (1000 clue-based + 1000 bijection-based)
- Parse-error coverage: 26/26
- Protocol errors: 0
- Failures: 0
- Source fixtures: `eval/gates/stage4_trace_parser/parser_fixtures/parser_fixture_solutions.jsonl`
  (synthetic; structurally valid; not clingo gold; Stage 4 only)

Stage 4 core parser: PASS

## Provider trace-shape diagnostics

| Diagnostic | Model | Samples | TRACE_PARSED | Status |
|---|---|---|---|---|
| `provider_validation/raw_outputs.jsonl` (stored) | deepseek/deepseek-v4-flash | 140 | 140 (100%) | pass (reparse, parseability only) |
| `provider_adversarial/raw_outputs.jsonl` (stored) | deepseek/deepseek-v4-flash | 120 adversarial + 140 positive | 120 rejected + 140 parsed | pass (reparse) |
| `provider_stepwise/raw_outputs.jsonl` (this freeze) | deepseek/deepseek-v4-flash | 36 attempted | 20/35 returned text, 33/35 raw-JSON valid, 20/33 schema-valid, 20/35 Lean TRACE_PARSED, 0 schema<->Lean disagreements | partial (parseability only) |

The stepwise diagnostic now measures each validator layer independently.
Trace validity claims are DENOMINATED on the layer above them, not on
`samples attempted`. 0 out of 36 raw outputs leaked any of the 22 private
kernel rule names.

The core gate parses and lowers trace JSON only. Provider trace-shape
diagnostics are reported separately and do not replay operations, check
trace correctness, score puzzle answers, retry requests, or perform
solver/search work in Lean.
