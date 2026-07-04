# Stage 4 provider diagnosis

Status: **PASS**

- Primary model: `deepseek/deepseek-v4-flash`
- Baseline: 3/3 valid JSON, 0/3 schema-valid
- After fix: 20/20 valid JSON, 20/20 schema-valid
- Unexpected-field failures after fix: 0
- Wrapper failures after fix: 0
- Extraction failures after fix: 0
- Prompt exemplar failures: 0
- Fixed: true

This is trace-shape validation only. It does not score puzzle correctness, replay traces,
request reasoning, retry calls, or run solver/search in Lean.
