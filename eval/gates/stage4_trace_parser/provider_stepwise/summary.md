# Stage 4 provider stepwise trace-shape diagnostic

Status: **PARTIAL** (parseability only)

- Model: `deepseek/deepseek-v4-flash`
- Samples: 36
- TRACE_PARSED: 20/36
- Valid JSON: 20/36
- Provider errors: 1
- Private-rule-name leakage count: 0

Success means raw provider outputs parsed under the trusted Lean verifier and the published JSON Schema. The trace did NOT have to be semantically sound.
