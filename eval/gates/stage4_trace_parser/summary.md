# Stage 4 trace-parser gate

Status: **PASS**

- Traces: 2022
- Full-candidate traces: 1000
- Stepwise traces: 1000
- Parse-error coverage: 22/22
- Protocol errors: 0
- Failures: 0

Stage 4 core parser: PASS
Provider trace-shape validation: PASS (20/20 valid JSON; 20/20 schema-valid)

The core gate parses and lowers trace JSON only. Provider trace-shape diagnostics are
reported separately and do not replay operations, check trace correctness, score puzzle
answers, retry requests, or perform solver/search work in Lean.
