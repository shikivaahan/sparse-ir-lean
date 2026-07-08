# Stage 3 stepwise G1 gate

Status: **PASS**

- Seed: 20260815 (fuzz seed 20260815)
- clingo version: 5.8.0
- Real/gold puzzle count: 1000
- Fuzzed puzzle count: 10000
- Total SAT-consistent states sampled: 139846
- Total local step queries: 139846
- Lean-accepted steps: 138244
- Lean-rejected semantic steps: 1602
- Per-rule counts: {'bijection_cell_singleton_forces_place': 34166, 'same_house_eliminate_no_possible_match': 7669, 'given_not_at_eliminate': 9880, 'bijection_value_singleton_forces_place': 42642, 'same_house_place_from_placed': 509, 'direct_left_place_from_fixed': 246, 'given_found_at_place': 15481, 'left_of_eliminate_impossible_order': 7919, 'direct_left_eliminate_no_possible_partner': 3166, 'right_of_eliminate_impossible_order': 8045, 'side_by_side_eliminate_no_possible_neighbor': 2909, 'side_by_side_place_from_single_neighbor': 305, 'one_between_eliminate_no_possible_partner': 2767, 'one_between_place_from_fixed': 49, 'two_between_eliminate_no_possible_partner': 2254, 'two_between_place_from_fixed': 13, 'direct_right_eliminate_no_possible_partner': 1682, 'direct_right_place_from_fixed': 144}
- Per-clue-type counts: {'same_house': 8178, 'not_at': 9880, 'direct_left': 3412, 'found_at': 15481, 'left_of': 7919, 'right_of': 8045, 'side_by_side': 3214, 'one_between': 2816, 'two_between': 2267, 'direct_right': 1826}
- Placement vs elimination counts: {'place': 93555, 'eliminate': 46291}
- Grid-size distribution: {'2x2': 5076, '2x3': 7530, '2x4': 8552, '2x5': 9055, '2x6': 9723, '3x2': 4244, '3x3': 6009, '3x4': 6122, '3x5': 7287, '3x6': 7543, '4x2': 3538, '4x3': 4261, '4x4': 5205, '4x5': 5013, '4x6': 6876, '5x2': 3974, '5x3': 4120, '5x4': 4600, '5x5': 4558, '5x6': 5078, '6x2': 4230, '6x3': 4132, '6x4': 4129, '6x5': 4422, '6x6': 4569}

## Headline metrics

- Candidate-level G1: see the rerun of stage3b_differential_candidates (independent gate directory).
- Stepwise global soundness: **unsound Lean accepts = 0**
- Stepwise justification-local differential: **disagreements = 0**

The exit criterion is:

* candidate G1: zero disagreements (existing gate definition)
* stepwise global soundness: zero unsound accepted steps over the recorded corpus
* stepwise local differential: zero Lean↔clingo disagreements over the recorded supported-rule corpus
