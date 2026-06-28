# Stage 2 Gate B+ mutation examples

## `unsupported_schema_version`

### subtype `version_0_1`

- Source problem: `zl_lgp-test-2x2-1` (grid `2x2`)
- Mutation: Set schema_version to '0.1'.
- Expected error code: `unsupported_schema_version`
- Actual error code: `unsupported_schema_version`
- Actual error path: `$.schema_version`
- Status: `expected_rejection`
- Before: `"0.2"`
- After: `"0.1"`

### subtype `version_0_3`

- Source problem: `zl_lgp-test-2x2-1` (grid `2x2`)
- Mutation: Set schema_version to '0.3'.
- Expected error code: `unsupported_schema_version`
- Actual error code: `unsupported_schema_version`
- Actual error path: `$.schema_version`
- Status: `expected_rejection`
- Before: `"0.2"`
- After: `"0.3"`

### subtype `version_1_0`

- Source problem: `zl_lgp-test-2x2-1` (grid `2x2`)
- Mutation: Set schema_version to '1.0'.
- Expected error code: `unsupported_schema_version`
- Actual error code: `unsupported_schema_version`
- Actual error path: `$.schema_version`
- Status: `expected_rejection`
- Before: `"0.2"`
- After: `"1.0"`

### subtype `version_empty`

- Source problem: `zl_lgp-test-2x2-1` (grid `2x2`)
- Mutation: Set schema_version to ''.
- Expected error code: `invalid_value`
- Actual error code: `invalid_schema`
- Actual error path: `$.schema_version`
- Status: `parser_rejection_expected`
- Before: `"0.2"`
- After: `""`

### subtype `version_label`

- Source problem: `zl_lgp-test-2x2-1` (grid `2x2`)
- Mutation: Set schema_version to 'gate-b-plus'.
- Expected error code: `unsupported_schema_version`
- Actual error code: `unsupported_schema_version`
- Actual error path: `$.schema_version`
- Status: `expected_rejection`
- Before: `"0.2"`
- After: `"gate-b-plus"`

## `invalid_domain`

### subtype `domain_empty`

- Source problem: `zl_lgp-test-2x2-1` (grid `2x2`)
- Mutation: Set domain to ''.
- Expected error code: `invalid_value`
- Actual error code: `invalid_schema`
- Actual error path: `$.domain`
- Status: `parser_rejection_expected`
- Before: `"zebra"`
- After: `""`

### subtype `domain_logic_grid`

- Source problem: `zl_lgp-test-2x2-1` (grid `2x2`)
- Mutation: Set domain to 'logic_grid'.
- Expected error code: `invalid_domain`
- Actual error code: `invalid_domain`
- Actual error path: `$.domain`
- Status: `expected_rejection`
- Before: `"zebra"`
- After: `"logic_grid"`

### subtype `domain_zebra_logic`

- Source problem: `zl_lgp-test-2x2-1` (grid `2x2`)
- Mutation: Set domain to 'zebra_logic'.
- Expected error code: `invalid_domain`
- Actual error code: `invalid_domain`
- Actual error path: `$.domain`
- Status: `expected_rejection`
- Before: `"zebra"`
- After: `"zebra_logic"`

### subtype `domain_capitalized`

- Source problem: `zl_lgp-test-2x2-1` (grid `2x2`)
- Mutation: Set domain to 'Zebra'.
- Expected error code: `invalid_domain`
- Actual error code: `invalid_domain`
- Actual error path: `$.domain`
- Status: `expected_rejection`
- Before: `"zebra"`
- After: `"Zebra"`

### subtype `domain_label`

- Source problem: `zl_lgp-test-2x2-1` (grid `2x2`)
- Mutation: Set domain to 'gate-b-plus-invalid'.
- Expected error code: `invalid_domain`
- Actual error code: `invalid_domain`
- Actual error path: `$.domain`
- Status: `expected_rejection`
- Before: `"zebra"`
- After: `"gate-b-plus-invalid"`

## `size_mismatch`

### subtype `categories_too_small`

- Source problem: `zl_lgp-test-2x2-1` (grid `2x2`)
- Mutation: Adjusted declared categories by -1.
- Expected error code: `size_mismatch`
- Actual error code: `size_mismatch`
- Actual error path: `$.size.categories`
- Status: `expected_rejection`
- Before: `2`
- After: `1`

### subtype `categories_too_large`

- Source problem: `zl_lgp-test-2x2-1` (grid `2x2`)
- Mutation: Adjusted declared categories by 1.
- Expected error code: `size_mismatch`
- Actual error code: `size_mismatch`
- Actual error path: `$.size.categories`
- Status: `expected_rejection`
- Before: `2`
- After: `3`

### subtype `houses_too_small`

- Source problem: `zl_lgp-test-2x2-1` (grid `2x2`)
- Mutation: Adjusted declared houses by -1.
- Expected error code: `category_size_mismatch`
- Actual error code: `category_size_mismatch`
- Actual error path: `$.categories.Name`
- Status: `expected_rejection`
- Before: `2`
- After: `1`

### subtype `houses_too_large`

- Source problem: `zl_lgp-test-2x2-1` (grid `2x2`)
- Mutation: Adjusted declared houses by 1.
- Expected error code: `category_size_mismatch`
- Actual error code: `category_size_mismatch`
- Actual error path: `$.categories.Name`
- Status: `expected_rejection`
- Before: `2`
- After: `3`

## `category_size_mismatch`

### subtype `remove_first`

- Source problem: `zl_lgp-test-2x2-1` (grid `2x2`)
- Mutation: Removed first value from category Name.
- Expected error code: `category_size_mismatch`
- Actual error code: `category_size_mismatch`
- Actual error path: `$.categories.Name`
- Status: `expected_rejection`
- Before: `["Arnold", "Eric"]`
- After: `["Eric"]`

### subtype `remove_last`

- Source problem: `zl_lgp-test-2x2-1` (grid `2x2`)
- Mutation: Removed last value from category Name.
- Expected error code: `category_size_mismatch`
- Actual error code: `category_size_mismatch`
- Actual error path: `$.categories.Name`
- Status: `expected_rejection`
- Before: `["Arnold", "Eric"]`
- After: `["Arnold"]`

### subtype `append_extra`

- Source problem: `zl_lgp-test-2x2-1` (grid `2x2`)
- Mutation: Appended a sentinel value to category Name.
- Expected error code: `category_size_mismatch`
- Actual error code: `category_size_mismatch`
- Actual error path: `$.categories.Name`
- Status: `expected_rejection`
- Before: `["Arnold", "Eric"]`
- After: `["Arnold", "Eric", "__gate_b_plus_extra_Name"]`

### subtype `empty_category`

- Source problem: `zl_lgp-test-2x2-1` (grid `2x2`)
- Mutation: Emptied category Name.
- Expected error code: `invalid_value`
- Actual error code: `invalid_schema`
- Actual error path: `$.categories.Name`
- Status: `parser_rejection_expected`
- Before: `["Arnold", "Eric"]`
- After: `[]`

## `duplicate_value`

### subtype `duplicate_first`

- Source problem: `zl_lgp-test-2x2-1` (grid `2x2`)
- Mutation: Duplicated the first value inside category Name.
- Expected error code: `duplicate_value`
- Actual error code: `duplicate_value`
- Actual error path: `$.categories.Name[1]`
- Status: `expected_rejection`
- Before: `["Arnold", "Eric"]`
- After: `["Arnold", "Arnold"]`

### subtype `duplicate_last`

- Source problem: `zl_lgp-test-2x2-1` (grid `2x2`)
- Mutation: Duplicated the last value inside category Name.
- Expected error code: `duplicate_value`
- Actual error code: `duplicate_value`
- Actual error path: `$.categories.Name[1]`
- Status: `expected_rejection`
- Before: `["Arnold", "Eric"]`
- After: `["Arnold", "Arnold"]`

### subtype `duplicate_every_category`

- Source problem: `zl_lgp-test-2x2-1` (grid `2x2`)
- Mutation: Duplicated a value inside every category that had >=2 values.
- Expected error code: `duplicate_value`
- Actual error code: `duplicate_value`
- Actual error path: `$.categories.Name[1]`
- Status: `expected_rejection`
- Before: `multiple categories`
- After: `first values duplicated across 2 categories`

## `duplicate_clue_id`

### subtype `first_to_second`

- Source problem: `zl_lgp-test-2x2-1` (grid `2x2`)
- Mutation: Reused the first clue id on the second clue.
- Expected error code: `duplicate_clue_id`
- Actual error code: `duplicate_clue_id`
- Actual error path: `$.clues[1].id`
- Status: `expected_rejection`
- Before: `"c1"`
- After: `"c1"`

### subtype `last_to_first`

- Source problem: `zl_lgp-test-2x2-1` (grid `2x2`)
- Mutation: Reused the last clue id on the first clue.
- Expected error code: `duplicate_clue_id`
- Actual error code: `duplicate_clue_id`
- Actual error path: `$.clues[1].id`
- Status: `expected_rejection`
- Before: `"c1"`
- After: `"c2"`

### subtype `non_adjacent`

- Source problem: `zl_lgp-test-2x2-1` (grid `2x2`)
- Mutation: Reused the first clue id on the second clue.
- Expected error code: `duplicate_clue_id`
- Actual error code: `duplicate_clue_id`
- Actual error path: `$.clues[1].id`
- Status: `expected_rejection`
- Before: `"c1"`
- After: `"c1"`

### subtype `three_clues`

- Source problem: `zl_lgp-test-2x2-1` (grid `2x2`)
- Mutation: Reused the first clue id on the second clue.
- Expected error code: `duplicate_clue_id`
- Actual error code: `duplicate_clue_id`
- Actual error path: `$.clues[1].id`
- Status: `expected_rejection`
- Before: `"c1"`
- After: `"c1"`

## `unknown_category`

### subtype `unary_cat`

- Source problem: `zl_lgp-test-2x2-1` (grid `2x2`)
- Mutation: Changed clue c2 cat to an undeclared name.
- Expected error code: `unknown_category`
- Actual error code: `unknown_category`
- Actual error path: `$.clues[1].cat`
- Status: `expected_rejection`
- Before: `"Occupation"`
- After: `"__gate_b_plus_unknown_category_unary_cat__"`

### subtype `binary_a_cat`

- Source problem: `zl_lgp-test-2x2-1` (grid `2x2`)
- Mutation: Changed clue c1 operand a.cat to an undeclared name.
- Expected error code: `unknown_category`
- Actual error code: `unknown_category`
- Actual error path: `$.clues[0].a.cat`
- Status: `expected_rejection`
- Before: `"Name"`
- After: `"__gate_b_plus_unknown_category_binary_a_cat__"`

### subtype `binary_b_cat`

- Source problem: `zl_lgp-test-2x2-1` (grid `2x2`)
- Mutation: Changed clue c1 operand b.cat to an undeclared name.
- Expected error code: `unknown_category`
- Actual error code: `unknown_category`
- Actual error path: `$.clues[0].b.cat`
- Status: `expected_rejection`
- Before: `"Name"`
- After: `"__gate_b_plus_unknown_category_binary_b_cat__"`

## `unknown_value`

### subtype `unary_val`

- Source problem: `zl_lgp-test-2x2-1` (grid `2x2`)
- Mutation: Changed clue c2 val to an undeclared value.
- Expected error code: `unknown_value`
- Actual error code: `unknown_value`
- Actual error path: `$.clues[1].val`
- Status: `expected_rejection`
- Before: `"doctor"`
- After: `"__gate_b_plus_unknown_value_unary_val__"`

### subtype `binary_a_val`

- Source problem: `zl_lgp-test-2x2-1` (grid `2x2`)
- Mutation: Changed clue c1 operand a.val to an undeclared value.
- Expected error code: `unknown_value`
- Actual error code: `unknown_value`
- Actual error path: `$.clues[0].a.val`
- Status: `expected_rejection`
- Before: `"Eric"`
- After: `"__gate_b_plus_unknown_value_binary_a_val__"`

### subtype `binary_b_val`

- Source problem: `zl_lgp-test-2x2-1` (grid `2x2`)
- Mutation: Changed clue c1 operand b.val to an undeclared value.
- Expected error code: `unknown_value`
- Actual error code: `unknown_value`
- Actual error path: `$.clues[0].b.val`
- Status: `expected_rejection`
- Before: `"Arnold"`
- After: `"__gate_b_plus_unknown_value_binary_b_val__"`

### subtype `known_value_wrong_category`

- Source problem: `zl_lgp-test-2x2-1` (grid `2x2`)
- Mutation: Moved clue c1 operand a to category Occupation with value 'Arnold' (which is not declared in Occupation).
- Expected error code: `unknown_value`
- Actual error code: `unknown_value`
- Actual error path: `$.clues[0].a.val`
- Status: `expected_rejection`
- Before: `{"cat": "Name", "val": "Eric"}`
- After: `{"cat": "Occupation", "val": "Arnold"}`

### subtype `totally_unknown_value`

- Source problem: `zl_lgp-test-2x2-1` (grid `2x2`)
- Mutation: Changed clue c2 val to an undeclared value.
- Expected error code: `unknown_value`
- Actual error code: `unknown_value`
- Actual error path: `$.clues[1].val`
- Status: `expected_rejection`
- Before: `"doctor"`
- After: `"__gate_b_plus_unknown_value_totally_unknown_value__"`

## `house_out_of_range`

### subtype `house_zero`

- Source problem: `zl_lgp-test-2x2-1` (grid `2x2`)
- Mutation: Moved clue c2 to house 0 (out of range).
- Expected error code: `house_out_of_range`
- Actual error code: `house_out_of_range`
- Actual error path: `$.clues[1].house`
- Status: `expected_rejection`
- Before: `1`
- After: `0`

### subtype `house_one_past_end`

- Source problem: `zl_lgp-test-2x2-1` (grid `2x2`)
- Mutation: Moved clue c2 to house 3 (out of range).
- Expected error code: `house_out_of_range`
- Actual error code: `house_out_of_range`
- Actual error path: `$.clues[1].house`
- Status: `expected_rejection`
- Before: `1`
- After: `3`

### subtype `house_hundred_past_end`

- Source problem: `zl_lgp-test-2x2-1` (grid `2x2`)
- Mutation: Moved clue c2 to house 102 (out of range).
- Expected error code: `house_out_of_range`
- Actual error code: `house_out_of_range`
- Actual error path: `$.clues[1].house`
- Status: `expected_rejection`
- Before: `1`
- After: `102`
