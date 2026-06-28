# Stage 2 Gate B mutation examples

## `unsupported_schema_version`

- Source problem: `zl_lgp-test-2x2-0`
- Mutation: Changed schema_version to an unsupported value.
- Expected error code: `unsupported_schema_version`
- Actual error code: `unsupported_schema_version`
- Actual error path: `$.schema_version`
- Before: `"0.2"`
- After: `"gate-b-unsupported"`

## `invalid_domain`

- Source problem: `zl_lgp-test-2x2-0`
- Mutation: Changed domain away from zebra.
- Expected error code: `invalid_domain`
- Actual error code: `invalid_domain`
- Actual error path: `$.domain`
- Before: `"zebra"`
- After: `"gate-b-invalid-domain"`

## `size_mismatch`

- Source problem: `zl_lgp-test-2x2-0`
- Mutation: Increased the declared category count without adding a category.
- Expected error code: `size_mismatch`
- Actual error code: `size_mismatch`
- Actual error path: `$.size.categories`
- Before: `2`
- After: `3`

## `category_size_mismatch`

- Source problem: `zl_lgp-test-2x2-0`
- Mutation: Removed one value from category MusicGenre.
- Expected error code: `category_size_mismatch`
- Actual error code: `category_size_mismatch`
- Actual error path: `$.categories.MusicGenre`
- Before: `["pop", "rock"]`
- After: `["pop"]`

## `duplicate_value`

- Source problem: `zl_lgp-test-2x2-0`
- Mutation: Duplicated value 'pop' inside category MusicGenre.
- Expected error code: `duplicate_value`
- Actual error code: `duplicate_value`
- Actual error path: `$.categories.MusicGenre[1]`
- Before: `["pop", "rock"]`
- After: `["pop", "pop"]`

## `duplicate_clue_id`

- Source problem: `zl_lgp-test-2x2-0`
- Mutation: Reused the first clue ID on the second clue.
- Expected error code: `duplicate_clue_id`
- Actual error code: `duplicate_clue_id`
- Actual error path: `$.clues[1].id`
- Before: `"c2"`
- After: `"c1"`

## `unknown_category`

- Source problem: `zl_lgp-test-2x2-0`
- Mutation: Changed clue c2 operand a.cat to an undeclared name.
- Expected error code: `unknown_category`
- Actual error code: `unknown_category`
- Actual error path: `$.clues[1].a.cat`
- Before: `"Name"`
- After: `"__gate_b_unknown_category__"`

## `unknown_value`

- Source problem: `zl_lgp-test-2x2-0`
- Mutation: Changed clue c2 operand a.val to an undeclared name.
- Expected error code: `unknown_value`
- Actual error code: `unknown_value`
- Actual error path: `$.clues[1].a.val`
- Before: `"Eric"`
- After: `"__gate_b_unknown_value__"`

## `house_out_of_range`

- Source problem: `zl_lgp-test-2x2-0`
- Mutation: Moved clue c1 beyond the last house.
- Expected error code: `house_out_of_range`
- Actual error code: `house_out_of_range`
- Actual error path: `$.clues[0].house`
- Before: `1`
- After: `3`
