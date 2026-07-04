# Stage 4 trace-parser gate

Status: **PASS**

- Traces: 2022
- Full-candidate traces: 1000
- Stepwise traces: 1000
- Parse-error coverage: 22/22
- Protocol errors: 0
- Failures: 0

Stage 4 core parser: PASS
Provider trace-shape validation: PASS (140/140 TRACE_PARSED; parseability only)
Provider adversarial parser diagnostics: PASS (140/140 positive parses and 120/120
expected structured rejections; parseability only)

Inspect AI log: `provider_adversarial/inspect_logs/2026-06-29T19-58-32-00-00_stage4-provider-adversarial_6yGbaoGrSuxRmYWr8CBcdf.eval`
View: `http://127.0.0.1:7577`

The core gate parses and lowers trace JSON only. Provider trace-shape diagnostics are
reported separately and do not replay operations, check trace correctness, score puzzle
answers, retry requests, or perform solver/search work in Lean.
