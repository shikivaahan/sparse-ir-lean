"""Propose diverse, syntactically valid place/eliminate steps over a StepState.

The proposer does not consult the StepKernel to decide which step is "correct".
Its job is to enumerate a rich set of candidate steps, attach the matching
local-rule justification, and let the oracles decide the ground truth.

The diversity constraints explicitly cover the ten clue predicate families and
both `place` and `eliminate` operations, including:

* singleton-cell and singleton-value bijection cases
* same-house, direct_left/right, side_by_side, left_of/right_of,
  one_between, two_between with the partner placed or eliminated
* not_at eliminations and found_at placements
* a controlled share of syntactically valid steps whose local justification
  does NOT force the move (these become local-differential disagreements when
  the StepKernel would also accept them; the gate records every disagreement
  as evidence rather than as a pass)
"""

from __future__ import annotations

import random
from typing import Any


PLACE_RULES = (
    "given_found_at_place",
    "bijection_cell_singleton_forces_place",
    "bijection_value_singleton_forces_place",
    "same_house_place_from_placed",
    "direct_left_place_from_fixed",
    "direct_right_place_from_fixed",
    "side_by_side_place_from_single_neighbor",
    "one_between_place_from_fixed",
    "two_between_place_from_fixed",
)
ELIMINATE_RULES = (
    "given_not_at_eliminate",
    "bijection_place_eliminates_same_value_other_houses",
    "bijection_place_eliminates_other_values_same_house",
    "same_house_eliminate_no_possible_match",
    "direct_left_eliminate_no_possible_partner",
    "direct_right_eliminate_no_possible_partner",
    "side_by_side_eliminate_no_possible_neighbor",
    "left_of_eliminate_impossible_order",
    "right_of_eliminate_impossible_order",
    "one_between_eliminate_no_possible_partner",
    "two_between_eliminate_no_possible_partner",
)


def _cell(state: dict[str, Any], category: str, house: int) -> dict[str, Any]:
    return next(c for c in state["cells"] if c["cat"] == category and c["house"] == house)


def _attribute_placed(state: dict[str, Any], category: str, value: str, house: int) -> bool:
    c = _cell(state, category, house)
    return bool(c["placed"]) and c["possible"] == [value]


def _attribute_possible(state: dict[str, Any], category: str, value: str, house: int) -> bool:
    c = _cell(state, category, house)
    return value in c["possible"]


def _possible_houses(state: dict[str, Any], category: str, value: str) -> list[int]:
    return [
        int(c["house"])
        for c in state["cells"]
        if c["cat"] == category and value in c["possible"]
    ]


def _placed_house(state: dict[str, Any], category: str, value: str) -> int | None:
    for c in state["cells"]:
        if c["cat"] == category and c["placed"] and c["possible"] == [value]:
            return int(c["house"])
    return None


def _singleton_neighbor(
    state: dict[str, Any], category: str, value: str, fixed_house: int, distance: int
) -> int | None:
    candidates = [
        int(c["house"])
        for c in state["cells"]
        if c["cat"] == category
        and value in c["possible"]
        and (
            int(c["house"]) + distance == fixed_house
            or fixed_house + distance == int(c["house"])
        )
    ]
    if len(candidates) == 1:
        return candidates[0]
    return None


def _step(op: str, category: str, value: str, house: int, rule: str, clue_id: str | None) -> dict[str, Any]:
    justify: dict[str, Any] = {"rule": rule}
    if clue_id is not None:
        justify["clue_id"] = clue_id
    return {
        "op": op,
        "cat": category,
        "val": value,
        "house": house,
        "justify": justify,
    }


def _propose_bijection_place(state: dict[str, Any], rng: random.Random) -> list[dict[str, Any]]:
    proposals: list[dict[str, Any]] = []
    for c in state["cells"]:
        if c["placed"]:
            continue
        if len(c["possible"]) == 1:
            value = c["possible"][0]
            proposals.append(
                _step(
                    "place",
                    c["cat"],
                    value,
                    int(c["house"]),
                    "bijection_cell_singleton_forces_place",
                    None,
                )
            )
    for category in {c["cat"] for c in state["cells"]}:
        value_pool = list({v for c in state["cells"] if c["cat"] == category for v in c["possible"]})
        for value in value_pool:
            possible_houses = _possible_houses(state, category, value)
            if len(possible_houses) == 1:
                house = possible_houses[0]
                proposals.append(
                    _step(
                        "place",
                        category,
                        value,
                        house,
                        "bijection_value_singleton_forces_place",
                        None,
                    )
                )
    rng.shuffle(proposals)
    return proposals


def _propose_bijection_eliminate(state: dict[str, Any], rng: random.Random) -> list[dict[str, Any]]:
    proposals: list[dict[str, Any]] = []
    for c in state["cells"]:
        if c["placed"]:
            continue
        cat = c["cat"]
        house = int(c["house"])
        for value in c["possible"]:
            placed_elsewhere = any(
                int(o["house"]) != house
                and o["cat"] == cat
                and o["placed"]
                and o["possible"] == [value]
                for o in state["cells"]
            )
            if placed_elsewhere:
                proposals.append(
                    _step(
                        "eliminate",
                        cat,
                        value,
                        house,
                        "bijection_place_eliminates_same_value_other_houses",
                        None,
                    )
                )
        for other in c["possible"]:
            placed_value_here = any(
                o["cat"] == cat
                and int(o["house"]) == house
                and o["placed"]
                and o["possible"] != [other]
                for o in state["cells"]
            )
            if placed_value_here:
                proposals.append(
                    _step(
                        "eliminate",
                        cat,
                        other,
                        house,
                        "bijection_place_eliminates_other_values_same_house",
                        None,
                    )
                )
    rng.shuffle(proposals)
    return proposals


def _propose_clue_steps(
    state: dict[str, Any],
    problem: dict[str, Any],
    rng: random.Random,
) -> list[dict[str, Any]]:
    proposals: list[dict[str, Any]] = []
    for clue in problem["clues"]:
        clue_id = clue["id"]
        if clue["type"] == "found_at":
            value = clue["val"]
            category = clue["cat"]
            house = int(clue["house"])
            if _attribute_possible(state, category, value, house):
                proposals.append(
                    _step(
                        "place",
                        category,
                        value,
                        house,
                        "given_found_at_place",
                        clue_id,
                    )
                )
        elif clue["type"] == "not_at":
            value = clue["val"]
            category = clue["cat"]
            house = int(clue["house"])
            target = _cell(state, category, house)
            if (
                not target["placed"]
                and value in target["possible"]
                and len(target["possible"]) > 1
            ):
                proposals.append(
                    _step(
                        "eliminate",
                        category,
                        value,
                        house,
                        "given_not_at_eliminate",
                        clue_id,
                    )
                )
        else:
            for direction in ("place", "eliminate"):
                proposals.extend(_binary_clue_proposals(state, clue, direction, rng))
    rng.shuffle(proposals)
    return proposals


def _binary_clue_proposals(
    state: dict[str, Any],
    clue: dict[str, Any],
    direction: str,
    rng: random.Random,
) -> list[dict[str, Any]]:
    clue_type = clue["type"]
    a = clue["a"]
    b = clue["b"]
    clue_id = clue["id"]
    proposals: list[dict[str, Any]] = []
    houses = max(int(c["house"]) for c in state["cells"])
    if clue_type == "same_house":
        if direction == "place":
            for item, partner in ((a, b), (b, a)):
                partner_house = _placed_house(state, partner["cat"], partner["val"])
                if partner_house is None:
                    continue
                if not _attribute_possible(state, item["cat"], item["val"], partner_house):
                    continue
                proposals.append(
                    _step(
                        "place",
                        item["cat"],
                        item["val"],
                        partner_house,
                        "same_house_place_from_placed",
                        clue_id,
                    )
                )
        else:
            for item, partner in ((a, b), (b, a)):
                for house in range(1, houses + 1):
                    if not _attribute_possible(state, partner["cat"], partner["val"], house):
                        proposals.append(
                            _step(
                                "eliminate",
                                item["cat"],
                                item["val"],
                                house,
                                "same_house_eliminate_no_possible_match",
                                clue_id,
                            )
                        )
                        break
        return proposals
    if clue_type in {"direct_left", "direct_right"}:
        if direction == "place":
            for item, partner in ((a, b), (b, a)):
                partner_house = _placed_house(state, partner["cat"], partner["val"])
                if partner_house is None:
                    continue
                if clue_type == "direct_left":
                    if item is a:
                        target_house = partner_house - 1
                    else:
                        target_house = partner_house + 1
                else:
                    if item is a:
                        target_house = partner_house + 1
                    else:
                        target_house = partner_house - 1
                if not (1 <= target_house <= houses):
                    continue
                if not _attribute_possible(state, item["cat"], item["val"], target_house):
                    continue
                rule = f"direct_{'left' if clue_type == 'direct_left' else 'right'}_place_from_fixed"
                proposals.append(
                    _step(
                        "place",
                        item["cat"],
                        item["val"],
                        target_house,
                        rule,
                        clue_id,
                    )
                )
        else:
            for item, partner in ((a, b), (b, a)):
                for house in range(1, houses + 1):
                    partner_house = house + 1 if clue_type == "direct_left" else house - 1
                    if not (1 <= partner_house <= houses):
                        continue
                    if _attribute_possible(state, partner["cat"], partner["val"], partner_house):
                        continue
                    rule = f"direct_{'left' if clue_type == 'direct_left' else 'right'}_eliminate_no_possible_partner"
                    proposals.append(
                        _step(
                            "eliminate",
                            item["cat"],
                            item["val"],
                            house,
                            rule,
                            clue_id,
                        )
                    )
                    break
        return proposals
    if clue_type == "side_by_side":
        distance = 1
        if direction == "place":
            for item, partner in ((a, b), (b, a)):
                partner_house = _placed_house(state, partner["cat"], partner["val"])
                if partner_house is None:
                    continue
                target = _singleton_neighbor(
                    state, item["cat"], item["val"], partner_house, distance
                )
                if target is None:
                    continue
                proposals.append(
                    _step(
                        "place",
                        item["cat"],
                        item["val"],
                        target,
                        "side_by_side_place_from_single_neighbor",
                        clue_id,
                    )
                )
        else:
            for item, partner in ((a, b), (b, a)):
                for house in range(1, houses + 1):
                    has_partner = any(
                        _attribute_possible(state, partner["cat"], partner["val"], other)
                        and abs(other - house) == distance
                        for other in range(1, houses + 1)
                    )
                    if not has_partner:
                        proposals.append(
                            _step(
                                "eliminate",
                                item["cat"],
                                item["val"],
                                house,
                                "side_by_side_eliminate_no_possible_neighbor",
                                clue_id,
                            )
                        )
                        break
        return proposals
    if clue_type in {"left_of", "right_of"}:
        if direction == "eliminate":
            for item, partner in ((a, b), (b, a)):
                for house in range(1, houses + 1):
                    partner_possible = _possible_houses(state, partner["cat"], partner["val"])
                    if clue_type == "left_of":
                        rule = "left_of_eliminate_impossible_order"
                        if item is a:
                            if all(p <= house for p in partner_possible):
                                proposals.append(
                                    _step(
                                        "eliminate",
                                        item["cat"],
                                        item["val"],
                                        house,
                                        rule,
                                        clue_id,
                                    )
                                )
                                break
                        else:
                            if all(p >= house for p in partner_possible):
                                proposals.append(
                                    _step(
                                        "eliminate",
                                        item["cat"],
                                        item["val"],
                                        house,
                                        rule,
                                        clue_id,
                                    )
                                )
                                break
                    else:
                        rule = "right_of_eliminate_impossible_order"
                        if item is a:
                            if all(p >= house for p in partner_possible):
                                proposals.append(
                                    _step(
                                        "eliminate",
                                        item["cat"],
                                        item["val"],
                                        house,
                                        rule,
                                        clue_id,
                                    )
                                )
                                break
                        else:
                            if all(p <= house for p in partner_possible):
                                proposals.append(
                                    _step(
                                        "eliminate",
                                        item["cat"],
                                        item["val"],
                                        house,
                                        rule,
                                        clue_id,
                                    )
                                )
                                break
        return proposals
    if clue_type in {"one_between", "two_between"}:
        distance = 2 if clue_type == "one_between" else 3
        place_rule = (
            "one_between_place_from_fixed"
            if clue_type == "one_between"
            else "two_between_place_from_fixed"
        )
        eliminate_rule = (
            "one_between_eliminate_no_possible_partner"
            if clue_type == "one_between"
            else "two_between_eliminate_no_possible_partner"
        )
        if direction == "place":
            for item, partner in ((a, b), (b, a)):
                partner_house = _placed_house(state, partner["cat"], partner["val"])
                if partner_house is None:
                    continue
                target = _singleton_neighbor(
                    state, item["cat"], item["val"], partner_house, distance
                )
                if target is None:
                    continue
                proposals.append(
                    _step(
                        "place",
                        item["cat"],
                        item["val"],
                        target,
                        place_rule,
                        clue_id,
                    )
                )
        else:
            for item, partner in ((a, b), (b, a)):
                for house in range(1, houses + 1):
                    has_partner = any(
                        _attribute_possible(state, partner["cat"], partner["val"], other)
                        and abs(other - house) == distance
                        for other in range(1, houses + 1)
                    )
                    if not has_partner:
                        proposals.append(
                            _step(
                                "eliminate",
                                item["cat"],
                                item["val"],
                                house,
                                eliminate_rule,
                                clue_id,
                            )
                        )
                        break
    return proposals


def _is_already_applied(state: dict[str, Any], step: dict[str, Any]) -> bool:
    target = _cell(state, step["cat"], int(step["house"]))
    if step["op"] == "place":
        return bool(target["placed"]) and target["possible"] == [step["val"]]
    if step["op"] == "eliminate":
        if target["placed"] or len(target["possible"]) <= 1:
            return True
        return step["val"] not in target["possible"]
    return False


def _is_invalid_for_state(state: dict[str, Any], step: dict[str, Any]) -> bool:
    """A step is invalid for the state when the target cell has already been
    settled in a way that makes the operation a no-op or a contradiction at
    the static level. These are excluded from the differential denominator
    because the StepKernel deterministically rejects them with a static
    error code rather than a semantic ``not_forced``/``accept`` verdict."""
    target = _cell(state, step["cat"], int(step["house"]))
    if step["op"] == "place":
        if target["placed"]:
            return True
        return step["val"] not in target["possible"]
    if step["op"] == "eliminate":
        if target["placed"] or len(target["possible"]) <= 1:
            return True
        return step["val"] not in target["possible"]
    return False


def propose_steps(
    problem: dict[str, Any],
    state: dict[str, Any],
    *,
    seed: int,
    max_proposals: int,
) -> list[dict[str, Any]]:
    """Enumerate diverse step proposals. The seed deterministically orders and
    subsamples the proposals so two gates with the same inputs get the same
    step list. Already-applied or static-invalid steps are filtered out so the
    differential denominator compares semantic verdicts only."""
    rng = random.Random(seed)
    proposals: list[dict[str, Any]] = []
    proposals.extend(_propose_bijection_place(state, rng))
    proposals.extend(_propose_bijection_eliminate(state, rng))
    proposals.extend(_propose_clue_steps(state, problem, rng))
    filtered = [
        step for step in proposals
        if not _is_already_applied(state, step) and not _is_invalid_for_state(state, step)
    ]
    rng.shuffle(filtered)
    if max_proposals and len(filtered) > max_proposals:
        filtered = filtered[:max_proposals]
    return filtered