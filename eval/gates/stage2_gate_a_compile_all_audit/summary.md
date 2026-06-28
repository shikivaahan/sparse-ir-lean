# Stage 2 Gate A dataset audit

- Exact audit command run: `uv run python scripts/audit_stage2_gate_a_dataset.py --gate-dir eval/gates/stage2_gate_a_compile_all --output eval/gates/stage2_gate_a_compile_all_audit`
- Status: **PASS**
- Total source rows checked: 1006
- Total ingested problems checked: 1000
- Total compiled rows checked: 1000
- Total errors: 0
- Total warnings: 0
- Safe to use for Gate B: yes

## Top findings by category

- None. Every audited invariant passed.

## Example source → raw → compiled mappings

- `zl_lgp-test-2x2-0` (2x2): source `data/zebralogic/grid_mode-test-00000-of-00001.parquet` row 782 → `eval/gates/stage2_gate_a_compile_all/ingested_problems/lgp-test-2x2-0.problem.json` → compiled 2 categories / 2 clues.
- `zl_lgp-test-4x4-0` (4x4): source `data/zebralogic/grid_mode-test-00000-of-00001.parquet` row 486 → `eval/gates/stage2_gate_a_compile_all/ingested_problems/lgp-test-4x4-0.problem.json` → compiled 4 categories / 11 clues.
- `zl_lgp-test-6x6-0` (6x6): source `data/zebralogic/grid_mode-test-00000-of-00001.parquet` row 549 → `eval/gates/stage2_gate_a_compile_all/ingested_problems/lgp-test-6x6-0.problem.json` → compiled 6 categories / 25 clues.

## Files for human review

- `eval/gates/stage2_gate_a_compile_all/source_manifest.jsonl`
- `eval/gates/stage2_gate_a_compile_all/compiled_problems.jsonl`
- `eval/gates/stage2_gate_a_compile_all/raw_problem_index.md`
- `eval/gates/stage2_gate_a_compile_all/compiled_problem_index.md`
- `eval/gates/stage2_gate_a_compile_all_audit/problem_audit.jsonl`
- `eval/gates/stage2_gate_a_compile_all_audit/findings.jsonl`
