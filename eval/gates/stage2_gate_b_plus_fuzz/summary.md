# Stage 2 Gate B+: broader fuzzing

- Exact command run: `uv run python scripts/stage2_gate_b_plus_fuzz.py --gate-a-dir eval/gates/stage2_gate_a_compile_all --output eval/gates/stage2_gate_b_plus_fuzz --seed 20260628 --max-problems-per-grid 25`
- Seed: `20260628`
- Status: **PASS**
- Total source problems available: 1000
- Total source problems used: 625
- Total mutations generated: 22042
- Total rejected: 22042
- Total unexpected compiled: 0
- Total wrong error code: 0
- Total missing error path: 0
- Total controls generated: 2495
- Total controls compiled: 2495
- Total controls rejected: 0

## Error-code coverage

| Error code | Mutations |
|---|---:|
| `unsupported_schema_version` | 2500 |
| `invalid_domain` | 2500 |
| `size_mismatch` | 1250 |
| `category_size_mismatch` | 3125 |
| `duplicate_value` | 1875 |
| `duplicate_clue_id` | 2480 |
| `unknown_category` | 1795 |
| `unknown_value` | 2971 |
| `house_out_of_range` | 1671 |

## Mutation-subtype coverage

| Mutation kind | Subtype | Count |
|---|---|---:|
| `unsupported_schema_version` | `version_0_1` | 625 |
| `unsupported_schema_version` | `version_0_3` | 625 |
| `unsupported_schema_version` | `version_1_0` | 625 |
| `unsupported_schema_version` | `version_label` | 625 |
| `invalid_domain` | `domain_capitalized` | 625 |
| `invalid_domain` | `domain_label` | 625 |
| `invalid_domain` | `domain_logic_grid` | 625 |
| `invalid_domain` | `domain_zebra_logic` | 625 |
| `size_mismatch` | `categories_too_large` | 625 |
| `size_mismatch` | `categories_too_small` | 625 |
| `size_mismatch` | `houses_too_large` | 625 |
| `size_mismatch` | `houses_too_small` | 625 |
| `category_size_mismatch` | `append_extra` | 625 |
| `category_size_mismatch` | `remove_first` | 625 |
| `category_size_mismatch` | `remove_last` | 625 |
| `duplicate_value` | `duplicate_every_category` | 625 |
| `duplicate_value` | `duplicate_first` | 625 |
| `duplicate_value` | `duplicate_last` | 625 |
| `duplicate_clue_id` | `first_to_second` | 620 |
| `duplicate_clue_id` | `last_to_first` | 620 |
| `duplicate_clue_id` | `non_adjacent` | 620 |
| `duplicate_clue_id` | `three_clues` | 620 |
| `unknown_category` | `binary_a_cat` | 619 |
| `unknown_category` | `binary_b_cat` | 619 |
| `unknown_category` | `unary_cat` | 557 |
| `unknown_value` | `binary_a_val` | 619 |
| `unknown_value` | `binary_b_val` | 619 |
| `unknown_value` | `known_value_wrong_category` | 619 |
| `unknown_value` | `totally_unknown_value` | 557 |
| `unknown_value` | `unary_val` | 557 |
| `house_out_of_range` | `house_hundred_past_end` | 557 |
| `house_out_of_range` | `house_one_past_end` | 557 |
| `house_out_of_range` | `house_zero` | 557 |

## Grid coverage

| Grid | Mutations | Controls |
|---|---:|---:|
| `2x2` | 824 | 95 |
| `2x3` | 859 | 100 |
| `2x4` | 829 | 100 |
| `2x5` | 864 | 100 |
| `2x6` | 864 | 100 |
| `3x2` | 900 | 100 |
| `3x3` | 858 | 100 |
| `3x4` | 864 | 100 |
| `3x5` | 870 | 100 |
| `3x6` | 882 | 100 |
| `4x2` | 900 | 100 |
| `4x3` | 894 | 100 |
| `4x4` | 894 | 100 |
| `4x5` | 900 | 100 |
| `4x6` | 900 | 100 |
| `5x2` | 888 | 100 |
| `5x3` | 894 | 100 |
| `5x4` | 900 | 100 |
| `5x5` | 894 | 100 |
| `5x6` | 876 | 100 |
| `6x2` | 900 | 100 |
| `6x3` | 900 | 100 |
| `6x4` | 900 | 100 |
| `6x5` | 900 | 100 |
| `6x6` | 888 | 100 |

## Findings (error-severity only shown above pass threshold)

- Total findings: 0
- Error-severity findings: 0

## Artifacts

- `eval/gates/stage2_gate_b_plus_fuzz/manifest.json`
- `eval/gates/stage2_gate_b_plus_fuzz/mutations.jsonl`
- `eval/gates/stage2_gate_b_plus_fuzz/results.jsonl`
- `eval/gates/stage2_gate_b_plus_fuzz/controls.jsonl`
- `eval/gates/stage2_gate_b_plus_fuzz/control_results.jsonl`
- `eval/gates/stage2_gate_b_plus_fuzz/findings.jsonl`
- `eval/gates/stage2_gate_b_plus_fuzz/mutation_examples.md`

## Rerun Gate B+

```bash
uv run python scripts/stage2_gate_b_plus_fuzz.py --gate-a-dir eval/gates/stage2_gate_a_compile_all --output eval/gates/stage2_gate_b_plus_fuzz --seed 20260628 --max-problems-per-grid 25
```

## Outcome

- Gate B+ **PASSED**
