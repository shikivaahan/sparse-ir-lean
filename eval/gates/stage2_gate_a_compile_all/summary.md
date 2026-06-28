# Stage 2 Gate A: full ZebraLogic eval compilation

- Status: **PASS**
- Coverage: **full eval-intended coverage**
- Exact command run: `uv run python scripts/stage2_gate_a_compile_all.py --output eval/gates/stage2_gate_a_compile_all`
- Total source records seen: 1006
- Total ingested: 1000
- Total compiled: 1000
- Total failed: 0
- Total skipped: 6
- Source roots scanned: `data/zebralogic`, `src/sparseir_harness/data/zebra`
- Fixture roots scanned: `data`, `eval`, `src/sparseir_harness/data`, `tests`
- Raw source manifest: `eval/gates/stage2_gate_a_compile_all/source_manifest.jsonl`
- Compiled manifest: `eval/gates/stage2_gate_a_compile_all/compiled_problems.jsonl`

## Rerun Gate A

```bash
uv run python scripts/stage2_gate_a_compile_all.py --output eval/gates/stage2_gate_a_compile_all
```
