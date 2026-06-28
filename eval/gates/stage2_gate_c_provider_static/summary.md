# Stage 2 Gate C provider-output static-error evaluation

- Gate C passed: **yes**
- Dataset path: `eval/datasets/stage2_gate_c_provider_static.jsonl`
- Inspect log path: `eval/logs/stage2_gate_c_provider_static/2026-06-28T20-29-37-00-00_stage2-gate-c-provider-static_KdxQrtW9SzowTKCryupBjA.eval`
- Total samples: 30
- Total provider calls: 30
- Inspect score: `lean_compiles` (`C` = compiled, `I` = rejected; the explanation contains the Lean diagnostic)
- Task-kind coverage: `{"bad_house_index": 3, "category_size_mismatch": 3, "drop_required_field": 3, "duplicate_clue_id": 3, "freeform_convert_to_problem_json": 3, "unknown_category": 3, "unknown_value": 3, "valid_reemit_problem": 3, "wrong_domain": 3, "wrong_schema_version": 3}`
- Classification counts: `{"compiled": 10, "parse_error": 9, "static_error": 11}`
- Lean error-code coverage: `{"category_size_mismatch": 1, "duplicate_clue_id": 1, "house_out_of_range": 3, "invalid_domain": 3, "invalid_schema": 3, "unknown_category": 3, "unknown_value": 3, "unsupported_schema_version": 3}`

## Exact commands

```bash
set -a; source .env; set +a; export OPENAI_API_KEY="$OPENROUTER_API_KEY"; export XDG_DATA_HOME=/tmp/sparseir-inspect-data; export TIKTOKEN_CACHE_DIR=/tmp/sparseir-tiktoken-cache; .venv/bin/inspect eval evals/stage2_gate_c_provider_static.py --model openai/deepseek/deepseek-v4-flash --model-base-url https://openrouter.ai/api/v1 --log-dir eval/logs/stage2_gate_c_provider_static --max-connections 4 --max-tokens 8192 --temperature 0 --max-retries 2 --timeout 180 --display plain
```

```bash
.venv/bin/inspect view start --log-dir eval/logs/stage2_gate_c_provider_static
```

## Example Lean diagnostics

- `gate-c-2x2-bad_house_index`: `house_out_of_range` at `$.clues[1].house` — house 999 is outside 1..2
  Raw provider output: `eval/gates/stage2_gate_c_provider_static/raw_outputs/gate-c-2x2-bad_house_index.txt`
- `gate-c-2x2-category_size_mismatch`: `category_size_mismatch` at `$.categories.Pet` — category 'Pet' has 1 values; expected 2
  Raw provider output: `eval/gates/stage2_gate_c_provider_static/raw_outputs/gate-c-2x2-category_size_mismatch.txt`
- `gate-c-2x2-drop_required_field`: `invalid_schema` at `$.size` — missing required field 'size'
  Raw provider output: `eval/gates/stage2_gate_c_provider_static/raw_outputs/gate-c-2x2-drop_required_field.txt`
