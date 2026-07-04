# Stage 4 trace-parser gate

Status: **PASS**

- Traces: 2025
- Full-candidate traces: 1000
- Stepwise traces: 1000
- Parse-error coverage: 25/25
- Protocol errors: 0
- Failures: 0

Stage 4 core parser: PASS
Provider trace-shape validation: BLOCKED by missing provider authorization/access

The core gate parses and lowers trace JSON only. Provider trace-shape diagnostics are
reported separately and do not replay operations, check trace correctness, score puzzle
answers, retry requests, or perform solver/search work in Lean.
