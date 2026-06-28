# Stage 2 Gate B: static mutation rejections

- Exact command run: `uv run python scripts/stage2_gate_b_mutation_rejections.py --gate-a-dir eval/gates/stage2_gate_a_compile_all --output eval/gates/stage2_gate_b_mutation_rejections`
- Status: **PASS**
- Total source problems used: 3
- Total mutations generated: 27
- Total rejected: 27

## Error-code coverage

| Error code | Mutations |
|---|---:|
| `unsupported_schema_version` | 3 |
| `invalid_domain` | 3 |
| `size_mismatch` | 3 |
| `category_size_mismatch` | 3 |
| `duplicate_value` | 3 |
| `duplicate_clue_id` | 3 |
| `unknown_category` | 3 |
| `unknown_value` | 3 |
| `house_out_of_range` | 3 |

## Grid coverage

| Grid | Mutations |
|---|---:|
| `2x2` | 9 |
| `4x4` | 9 |
| `6x6` | 9 |

## Artifacts

- `eval/gates/stage2_gate_b_mutation_rejections/manifest.json`
- `eval/gates/stage2_gate_b_mutation_rejections/mutations.jsonl`
- `eval/gates/stage2_gate_b_mutation_rejections/results.jsonl`
- `eval/gates/stage2_gate_b_mutation_rejections/mutation_examples.md`

## Rerun Gate B

```bash
uv run python scripts/stage2_gate_b_mutation_rejections.py --gate-a-dir eval/gates/stage2_gate_a_compile_all --output eval/gates/stage2_gate_b_mutation_rejections
```
