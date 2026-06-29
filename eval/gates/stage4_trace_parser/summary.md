# Stage 4 trace-parser gate

Status: **PASS**

- Traces: 2022
- Full-candidate traces: 1000
- Stepwise traces: 1000
- Parse-error coverage: 22/22
- Protocol errors: 0
- Failures: 0

Stage 4 core parser: PASS
Provider trace-shape validation: COMPLETE (3/3 valid JSON; 0/3 schema-valid)

This gate parses and lowers trace JSON only. It does not replay operations,
check trace correctness, emit trace artifacts, call a provider, retry requests,
or perform solver/search work in Lean.
