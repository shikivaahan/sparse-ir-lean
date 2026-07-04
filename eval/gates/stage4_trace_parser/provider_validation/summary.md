# Stage 4 provider feature validation

Status: **PASS**

- Model: `deepseek/deepseek-v4-flash`
- Samples: 140
- Valid JSON: 140/140
- TRACE_PARSED: 140/140
- Schema invalid: 0
- Provider output not JSON: 0
- Protocol errors: 0

Success means only that provider output parsed as the requested trace syntax. No trace was
replayed or scored for semantic correctness, proof validity, or solved-state acceptance.
