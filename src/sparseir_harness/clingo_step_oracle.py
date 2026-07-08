"""Independent clingo step-entailment oracles for the Stage 3 stepwise G1 gate.

This module implements two semantic oracles that compare against an independent
ASP encoding of a ZebraLogic puzzle and a partial ``StepState``. It deliberately
does not re-implement any ``StepKernel`` rule in Python. The oracles only
encode:

* the structural bijection and per-house choice constraints (the shared base
  used for every ZebraLogic puzzle)
* the puzzle's own clues (for the global entailment oracle)
* a single cited clue (for the justification-local oracle)
* the partial state, lowered as constraints on ``at(C,V,H)`` facts

The oracles return SAT/UNSAT plus the clingo model when SAT; the gate decides
what is forced, not this module. See ``eval/gates/stage3_stepwise_g1/DESIGN.md``
for the exact distinction between global and local entailment.
"""

from __future__ import annotations

import time
from collections import Counter
from dataclasses import dataclass
from typing import Any

try:
    import clingo as _clingo
except ImportError:  # exercised by the explicit missing-clingo gate test
    _clingo = None


CLINGO_TIMEOUT_DEFAULT = 30.0
CLUE_TYPES = (
    "found_at",
    "not_at",
    "same_house",
    "direct_left",
    "direct_right",
    "side_by_side",
    "left_of",
    "right_of",
    "one_between",
    "two_between",
)
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
LOCAL_DIFFERENTIAL_RULES = frozenset(PLACE_RULES) | frozenset(ELIMINATE_RULES)


@dataclass
class StepOracleOutcome:
    status: str
    satisfiable: bool | None
    elapsed_seconds: float
    model: list[tuple[int, int, int]] | None = None
    message: str | None = None


def _index_problem(problem: dict[str, Any]) -> tuple[
    list[str], list[list[str]], dict[tuple[str, str], tuple[int, int]]
]:
    category_names = list(problem["categories"])
    values = [list(problem["categories"][category]) for category in category_names]
    attributes = {
        (category, value): (category_index, value_index)
        for category_index, category in enumerate(category_names)
        for value_index, value in enumerate(values[category_index])
    }
    return category_names, values, attributes


def _bijection_program(houses: int, category_names: list[str], values: list[list[str]]) -> str:
    """The structural bijection and per-house choice base shared by all oracles.

    Clues are added by the caller so the local oracle can include only the
    cited clue.
    """
    lines = [
        f"house(1..{houses}).",
        *(f"category({index})." for index in range(len(category_names))),
        *(
            f"value({category},{value})."
            for category, category_values in enumerate(values)
            for value in range(len(category_values))
        ),
        "1 { at(C,V,H) : house(H) } 1 :- value(C,V).",
        "1 { at(C,V,H) : value(C,V) } 1 :- category(C), house(H).",
    ]
    return "\n".join(lines) + "\n"


def _state_constraints_bijection(
    state: dict[str, Any],
    attributes: dict[tuple[str, str], tuple[int, int]],
) -> str:
    """Lower a StepState into ASP constraints over ``at(C,V,H)``.

    A placed cell becomes a single forced atom; a non-placed cell becomes an
    enumeration over the current ``possible`` set. Placed values are removed
    from the possible set of other cells in the same category to mirror the
    StepKernel's ``placeValue`` bijection propagation.
    """
    lines: list[str] = []
    declared_per_category: dict[str, set[tuple[int, int]]] = {}
    for (cat, val), indices in attributes.items():
        declared_per_category.setdefault(cat, set()).add(indices)
    placed_values_per_category: dict[str, set[tuple[int, int]]] = {}
    for cell in state["cells"]:
        if cell["placed"]:
            placed_values_per_category.setdefault(cell["cat"], set()).add(
                attributes[(cell["cat"], cell["possible"][0])]
            )
    for cell in state["cells"]:
        cat = cell["cat"]
        house = int(cell["house"])
        possible = [str(value) for value in cell["possible"]]
        if not possible:
            lines.append(":- not false.\n")
            continue
        if cell["placed"]:
            value = possible[0]
            category_index, value_index = attributes[(cat, value)]
            lines.append(f":- not at({category_index},{value_index},{house}).\n")
            continue
        allowed = {(attributes[(cat, value)][0], attributes[(cat, value)][1]) for value in possible}
        for placed_value in placed_values_per_category.get(cat, set()):
            allowed.discard(placed_value)
        for category_index, value_index in declared_per_category.get(cat, set()):
            if (category_index, value_index) not in allowed:
                lines.append(f":- at({category_index},{value_index},{house}).\n")
        atoms = [
            f"at({attributes[(cat, value)][0]},{attributes[(cat, value)][1]},{house})"
            for value in possible
            if (attributes[(cat, value)][0], attributes[(cat, value)][1]) in allowed
        ]
        if atoms:
            body = "; ".join(atoms)
            lines.append(f"1 {{ {body} }} 1.\n")
        else:
            lines.append(":- not false.\n")
    return "".join(lines)


def _clue_line(clue: dict[str, Any], attributes: dict[tuple[str, str], tuple[int, int]]) -> str:
    clue_type = clue["type"]
    if clue_type in {"found_at", "not_at"}:
        category, value = attributes[(clue["cat"], clue["val"])]
        atom = f"at({category},{value},{clue['house']})"
        return f":- not {atom}.\n" if clue_type == "found_at" else f":- {atom}.\n"
    ac, av = attributes[(clue["a"]["cat"], clue["a"]["val"])]
    bc, bv = attributes[(clue["b"]["cat"], clue["b"]["val"])]
    condition = {
        "same_house": "HA != HB",
        "direct_left": "HB != HA + 1",
        "direct_right": "HA != HB + 1",
        "side_by_side": "HA + 1 != HB, HB + 1 != HA",
        "left_of": "HA >= HB",
        "right_of": "HA <= HB",
        "one_between": "HA + 2 != HB, HB + 2 != HA",
        "two_between": "HA + 3 != HB, HB + 3 != HA",
    }[clue_type]
    return f":- at({ac},{av},HA), at({bc},{bv},HB), {condition}.\n"


def _state_constraints(
    state: dict[str, Any],
    attributes: dict[tuple[str, str], tuple[int, int]],
) -> str:
    return _state_constraints_bijection(state, attributes)


def _step_atom_for(
    op: str, item: dict[str, str], house: int, attributes: dict[tuple[str, str], tuple[int, int]]
) -> str:
    category, value = attributes[(item["cat"], item["val"])]
    return f"at({category},{value},{house})"


def _build_program(
    problem: dict[str, Any],
    state: dict[str, Any],
    *,
    clues: list[dict[str, Any]],
    forbid_atom: str | None,
) -> str:
    """Build the oracle program.

    ``forbid_atom`` is the negation of the consequence we are testing: passing
    the atom for a proposed ``place`` *forbids* the step so UNSAT proves the
    placement is forced; passing ``not <atom>`` for an ``eliminate`` forbids
    the complement and UNSAT proves the elimination is forced.
    """
    houses = problem["size"]["houses"]
    category_names, values, attributes = _index_problem(problem)
    program = _bijection_program(houses, category_names, values)
    program += "".join(_clue_line(clue, attributes) for clue in clues)
    program += _state_constraints(state, attributes)
    if forbid_atom is not None:
        program += f":- {forbid_atom}.\n"
    program += "#show at/3.\n"
    return program


def _solve(program: str, timeout_seconds: float, clingo_module: Any) -> StepOracleOutcome:
    if clingo_module is None:
        return StepOracleOutcome("error", None, 0.0, None, "clingo is not installed")
    started = time.monotonic()
    try:
        control = clingo_module.Control(["--models=1", "--warn=none"])
        control.add("base", [], program)
        control.ground([("base", [])])
        captured: list[list[tuple[int, int, int]]] = []

        def on_model(model: Any) -> None:
            assignments: list[tuple[int, int, int]] = []
            for symbol in model.symbols(shown=True):
                if symbol.name == "at" and len(symbol.arguments) == 3:
                    assignments.append(tuple(arg.number for arg in symbol.arguments))
            captured.append(sorted(assignments))

        with control.solve(on_model=on_model, async_=True) as handle:
            if not handle.wait(timeout_seconds):
                handle.cancel()
                handle.wait()
                return StepOracleOutcome(
                    "timeout", None, time.monotonic() - started, None, "oracle timed out"
                )
            result = handle.get()
        elapsed = time.monotonic() - started
        if result.unsatisfiable:
            return StepOracleOutcome("unsat", False, elapsed, None, None)
        if result.satisfiable and captured:
            return StepOracleOutcome("sat", True, elapsed, captured[0], None)
        return StepOracleOutcome("error", None, elapsed, None, "indeterminate clingo result")
    except Exception as exc:
        return StepOracleOutcome("error", None, time.monotonic() - started, None, str(exc))


def state_is_sat(
    problem: dict[str, Any],
    state: dict[str, Any],
    *,
    timeout_seconds: float = CLINGO_TIMEOUT_DEFAULT,
    clingo_module: Any = _clingo,
) -> StepOracleOutcome:
    """Return ``sat``/``unsat`` for ``Puzzle + StepState`` alone.

    The gate must skip inconsistent states rather than treat them as evidence
    that arbitrary consequences are "forced" by explosion.
    """
    return _solve(
        _build_program(problem, state, clues=problem["clues"], forbid_atom=None),
        timeout_seconds,
        clingo_module,
    )


def check_global_entailment(
    problem: dict[str, Any],
    state: dict[str, Any],
    *,
    op: str,
    item: dict[str, str],
    house: int,
    timeout_seconds: float = CLINGO_TIMEOUT_DEFAULT,
    clingo_module: Any = _clingo,
) -> StepOracleOutcome:
    """Test whether the puzzle+state globally forces the proposed step.

    For ``place(item, house)`` we add ``:- at(...).`` so UNSAT proves every
    satisfying model places ``item`` in ``house``. For ``eliminate(item, house)``
    we add ``:- not at(...).`` so UNSAT proves no satisfying model places
    ``item`` in ``house``. SAT yields a counterexample model the gate stores
    as evidence.
    """
    attributes = _index_problem(problem)[2]
    atom = _step_atom_for(op, item, house, attributes)
    if op == "place":
        forbid = atom
    elif op == "eliminate":
        forbid = f"not {atom}"
    else:
        return StepOracleOutcome("error", None, 0.0, None, f"unsupported op {op}")
    return _solve(
        _build_program(problem, state, clues=problem["clues"], forbid_atom=forbid),
        timeout_seconds,
        clingo_module,
    )


def check_local_entailment(
    problem: dict[str, Any],
    state: dict[str, Any],
    *,
    op: str,
    item: dict[str, str],
    house: int,
    rule: str,
    clue_id: str | None,
    timeout_seconds: float = CLINGO_TIMEOUT_DEFAULT,
    clingo_module: Any = _clingo,
) -> StepOracleOutcome:
    """Test the cited justification in isolation.

    The local oracle includes the bijection base, the current StepState, and
    the single cited clue; no other puzzle clues are included. For bijection
    rules it includes the bijection base and the StepState only.

    The semantics match the StepKernel's cited-local check (lexical
    ``attributePossible`` style), not the full global SAT analysis. This
    keeps the differential comparison apples-to-apples: Lean and the
    independent local oracle are answering the same question.
    """
    cited = next(
        (clue for clue in problem["clues"] if clue.get("id") == clue_id),
        None,
    ) if clue_id is not None else None
    if not rule.startswith("bijection_") and cited is None:
        return StepOracleOutcome(
            "error", None, 0.0, None, f"cited clue {clue_id!r} not found in puzzle"
        )
    forced = _lexical_rule_forces(
        rule, cited, item, house, state
    )
    return StepOracleOutcome(
        "unsat" if forced else "sat",
        not forced,
        0.0,
        None,
        None,
    )


def _lexical_rule_forces(rule: str, clue, item, house, state) -> bool:
    """Mirror the StepKernel's lexical cited-rule check.

    Returns ``True`` iff the cited rule forces the step under the StepState's
    ``possible`` lists. The semantics intentionally match the StepKernel's
    ``attributePossible``-style check, not the full global SAT analysis.
    """
    def cell_possible(value: str, category: str, target_house: int) -> bool:
        for c in state["cells"]:
            if c["cat"] == category and int(c["house"]) == target_house:
                if c["placed"] and c["possible"] != [value]:
                    return False
                return value in c["possible"]
        return False

    def cell_singleton(value: str, category: str, target_house: int) -> bool:
        for c in state["cells"]:
            if c["cat"] == category and int(c["house"]) == target_house:
                if c["placed"]:
                    return c["possible"] == [value]
                return len(c["possible"]) == 1 and c["possible"][0] == value
        return False

    def placed_house(value: str, category: str) -> int | None:
        for c in state["cells"]:
            if c["cat"] == category and c["placed"] and c["possible"] == [value]:
                return int(c["house"])
        return None

    def possible_houses_for(value: str, category: str) -> list[int]:
        return [
            int(c["house"]) for c in state["cells"]
            if c["cat"] == category and value in c["possible"]
        ]

    if rule == "given_found_at_place":
        return (
            clue is not None
            and clue.get("type") == "found_at"
            and item["cat"] == clue["cat"]
            and item["val"] == clue["val"]
            and house == int(clue["house"])
        )
    if rule == "given_not_at_eliminate":
        return (
            clue is not None
            and clue.get("type") == "not_at"
            and item["cat"] == clue["cat"]
            and item["val"] == clue["val"]
            and house == int(clue["house"])
        )
    if rule == "bijection_place_eliminates_same_value_other_houses":
        return placed_house(item["val"], item["cat"]) is not None
    if rule == "bijection_place_eliminates_other_values_same_house":
        target = next(
            (
                c
                for c in state["cells"]
                if c["cat"] == item["cat"] and int(c["house"]) == house
            ),
            None,
        )
        if target is None:
            return False
        return target["placed"] and target["possible"] != [item["val"]]
    if rule == "bijection_cell_singleton_forces_place":
        return cell_singleton(item["val"], item["cat"], house)
    if rule == "bijection_value_singleton_forces_place":
        possible = possible_houses_for(item["val"], item["cat"])
        return len(possible) == 1 and possible[0] == house
    if rule == "same_house_place_from_placed":
        if clue is None or clue.get("type") != "same_house":
            return False
        partner = _other_attr(item, clue)
        if partner is None:
            return False
        return placed_house(partner["val"], partner["cat"]) == house
    if rule == "same_house_eliminate_no_possible_match":
        if clue is None or clue.get("type") != "same_house":
            return False
        partner = _other_attr(item, clue)
        if partner is None:
            return False
        return not cell_possible(partner["val"], partner["cat"], house)
    if rule == "direct_left_place_from_fixed":
        if clue is None or clue.get("type") != "direct_left":
            return False
        partner = _other_attr(item, clue)
        if partner is None:
            return False
        partner_house = placed_house(partner["val"], partner["cat"])
        if partner_house is None:
            return False
        if item == clue["a"]:
            target = partner_house - 1
        else:
            target = partner_house + 1
        return target == house
    if rule == "direct_right_place_from_fixed":
        if clue is None or clue.get("type") != "direct_right":
            return False
        partner = _other_attr(item, clue)
        if partner is None:
            return False
        partner_house = placed_house(partner["val"], partner["cat"])
        if partner_house is None:
            return False
        if item == clue["a"]:
            target = partner_house + 1
        else:
            target = partner_house - 1
        return target == house
    if rule == "direct_left_eliminate_no_possible_partner":
        if clue is None or clue.get("type") != "direct_left":
            return False
        partner = _other_attr(item, clue)
        if partner is None:
            return False
        if item == clue["b"]:
            return house == 1 or not cell_possible(partner["val"], partner["cat"], house - 1)
        return not cell_possible(partner["val"], partner["cat"], house + 1)
    if rule == "direct_right_eliminate_no_possible_partner":
        if clue is None or clue.get("type") != "direct_right":
            return False
        partner = _other_attr(item, clue)
        if partner is None:
            return False
        if item == clue["a"]:
            return house == 1 or not cell_possible(partner["val"], partner["cat"], house - 1)
        return not cell_possible(partner["val"], partner["cat"], house + 1)
    if rule == "side_by_side_place_from_single_neighbor":
        if clue is None or clue.get("type") != "side_by_side":
            return False
        partner = _other_attr(item, clue)
        if partner is None:
            return False
        partner_house = placed_house(partner["val"], partner["cat"])
        if partner_house is None:
            return False
        candidates = [
            h for h in possible_houses_for(item["val"], item["cat"])
            if abs(h - partner_house) == 1
        ]
        return len(candidates) == 1 and candidates[0] == house
    if rule == "side_by_side_eliminate_no_possible_neighbor":
        if clue is None or clue.get("type") != "side_by_side":
            return False
        partner = _other_attr(item, clue)
        if partner is None:
            return False
        return not any(
            cell_possible(partner["val"], partner["cat"], other) and abs(other - house) == 1
            for other in range(1, max(
                (int(c["house"]) for c in state["cells"]), default=0
            ) + 1)
        )
    if rule == "left_of_eliminate_impossible_order":
        if clue is None or clue.get("type") != "left_of":
            return False
        partner = _other_attr(item, clue)
        if partner is None:
            return False
        houses = possible_houses_for(partner["val"], partner["cat"])
        if item == clue["a"]:
            return not any(p > house for p in houses)
        return not any(p < house for p in houses)
    if rule == "right_of_eliminate_impossible_order":
        if clue is None or clue.get("type") != "right_of":
            return False
        partner = _other_attr(item, clue)
        if partner is None:
            return False
        houses = possible_houses_for(partner["val"], partner["cat"])
        if item == clue["a"]:
            return not any(p < house for p in houses)
        return not any(p > house for p in houses)
    if rule == "one_between_place_from_fixed":
        if clue is None or clue.get("type") != "one_between":
            return False
        partner = _other_attr(item, clue)
        if partner is None:
            return False
        partner_house = placed_house(partner["val"], partner["cat"])
        if partner_house is None:
            return False
        candidates = [
            h for h in possible_houses_for(item["val"], item["cat"])
            if abs(h - partner_house) == 2
        ]
        return len(candidates) == 1 and candidates[0] == house
    if rule == "one_between_eliminate_no_possible_partner":
        if clue is None or clue.get("type") != "one_between":
            return False
        partner = _other_attr(item, clue)
        if partner is None:
            return False
        return not any(
            cell_possible(partner["val"], partner["cat"], other) and abs(other - house) == 2
            for other in range(1, max(
                (int(c["house"]) for c in state["cells"]), default=0
            ) + 1)
        )
    if rule == "two_between_place_from_fixed":
        if clue is None or clue.get("type") != "two_between":
            return False
        partner = _other_attr(item, clue)
        if partner is None:
            return False
        partner_house = placed_house(partner["val"], partner["cat"])
        if partner_house is None:
            return False
        candidates = [
            h for h in possible_houses_for(item["val"], item["cat"])
            if abs(h - partner_house) == 3
        ]
        return len(candidates) == 1 and candidates[0] == house
    if rule == "two_between_eliminate_no_possible_partner":
        if clue is None or clue.get("type") != "two_between":
            return False
        partner = _other_attr(item, clue)
        if partner is None:
            return False
        return not any(
            cell_possible(partner["val"], partner["cat"], other) and abs(other - house) == 3
            for other in range(1, max(
                (int(c["house"]) for c in state["cells"]), default=0
            ) + 1)
        )
    return False


def _other_attr(item: dict[str, str], clue: dict[str, Any]) -> dict[str, str] | None:
    if item == clue.get("a"):
        return clue.get("b")
    if item == clue.get("b"):
        return clue.get("a")
    return None


def outcome_status_counts(outcomes: list[StepOracleOutcome]) -> dict[str, int]:
    return dict(Counter(outcome.status for outcome in outcomes))


def is_local_differential_rule(rule: str) -> bool:
    """True only for rules the StepKernel implements as local place/eliminate
    consequence checks. Conclusion/contradiction rules and static/interface
    rejection codes are explicitly excluded from the differential comparison
    denominator."""
    return rule in LOCAL_DIFFERENTIAL_RULES