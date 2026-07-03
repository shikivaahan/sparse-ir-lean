# Stage 6 contamination perturbation smoke

Verdict: **passed**. This perturbation smoke did not find evidence of contamination; it does not establish absence of contamination.

- Perturbed solve rate: 36/40 (90.0%).
- Paired original baseline: 36/40 (90.0%).
- Regurgitations: 0; malformed: 2; clue violations: 2; truncations: 1.
- Reasoning present: 39/40; median 2566 tokens; finish reasons {'None': 1, 'length': 1, 'stop': 38}.
- Provider/rate-limit errors: 1/0; cost $0.078295; 2.47 examples/min.

Lean `check_candidate` is the sole correctness judge. Malformed outputs are not counted as clue violations.

## Readable samples

### Solved perturbed: `zl_lgp-test-2x2-11__perturbed_20260701`

Outcome: `solved`; Lean `ACCEPT_SOLVED/solved`.

Reasoning excerpt: We are given a puzzle with 2 houses (house 1 and house 2). Categories: Name (values: yarrow, wren) and Occupation (values: tulip, ocean). Clues: 1. c1: same_house: Name yarrow and Occupation tulip are in the same house. 2. c2: found_at: Occupation tulip is at house 2. From c2, tulip is at house 2. Then from c1, yarrow is in the same house as tulip, so yarrow is also at house 2. That leaves wren for house 1, and ocean for house 1 (since occupation ocean must be at the other house). So solution: H

### Failed/clue-violating: `zl_lgp-test-5x6-34__perturbed_20260701`

Outcome: `clue_violation`; Lean `REJECT/clue_violation`.

Reasoning excerpt: We are given a logic puzzle with 6 categories, each with 5 values, and 5 houses (positions 1-5). We need to assign each value to a house such that all clues are satisfied. The categories: Birthday, BookGenre, Children, Color, FavoriteSport, Name. Values are given. Let's list all values per category: Birthday: grove, pine, raven, xenia, thistle BookGenre: frost, azure, ivory, garnet, violet Children: jasmine, dawn, jade, dahlia, river Color: north, cedar, indigo, wheat, tide FavoriteSport: island

### Regurgitation

None observed.
