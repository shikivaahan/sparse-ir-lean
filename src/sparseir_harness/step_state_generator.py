"""Generate SAT-consistent partial ``StepState`` rows from a ZebraLogic puzzle.

The gate uses this module to construct StepStates that retain at least one
satisfying completion of the underlying puzzle. Each state is produced
independently of Lean acceptance: the StepKernel verdict on the step query is
the *subject* of the differential comparison, not the source of the state.

The generator works on schema-version-0.2 problem rows. It uses the generator's
internal satisfaction hint (when present, e.g. on fuzzed puzzles) or, for the
gold compiled corpus, the externally stored clingo reference solution.
"""

from __future__ import annotations

import random
from typing import Any


def initial_state(problem: dict[str, Any]) -> dict[str, Any]:
    """Return the unrestricted starting StepState for ``problem``."""
    cells: list[dict[str, Any]] = []
    for category, values in problem["categories"].items():
        for house in range(1, int(problem["size"]["houses"]) + 1):
            cells.append(
                {
                    "cat": category,
                    "house": house,
                    "possible": list(values),
                    "placed": False,
                }
            )
    return {"step_count": 0, "cells": cells}


def cell(state: dict[str, Any], category: str, house: int) -> dict[str, Any]:
    return next(
        cell for cell in state["cells"]
        if cell["cat"] == category and cell["house"] == house
    )


def _position(reference: dict[str, str], category: str, value: str) -> int:
    for house, placed in reference.items():
        if placed == value:
            return int(house)
    raise KeyError(f"value {value!r} not found in category {category!r}")


def _apply_placement(state: dict[str, Any], category: str, value: str, house: int) -> None:
    for c in state["cells"]:
        if c["cat"] != category:
            continue
        if c["house"] == house:
            c["possible"] = [value]
            c["placed"] = True
        else:
            c["possible"] = [v for v in c["possible"] if v != value]


def _apply_elimination(state: dict[str, Any], category: str, value: str, house: int) -> None:
    target = cell(state, category, house)
    if target["placed"]:
        return
    target["possible"] = [v for v in target["possible"] if v != value]


def _partial_state_from_progressive_placements(
    problem: dict[str, Any],
    reference: dict[str, dict[str, str]],
    rng: random.Random,
    *,
    max_fraction: float,
) -> dict[str, Any]:
    """Apply a random subset of the reference placements and propagate by
    bijection (no other clues considered here — the oracle will re-add them
    when checking state SAT)."""
    state = initial_state(problem)
    placements = [
        (category, value, _position(reference[category], category, value))
        for category in reference
        for value in reference[category].values()
    ]
    rng.shuffle(placements)
    keep = max(1, int(len(placements) * max_fraction))
    placed_by_category: dict[str, set[tuple[str, int]]] = {}
    for category, value, house in placements[:keep]:
        _apply_placement(state, category, value, house)
        placed_by_category.setdefault(category, set()).add((value, house))
    return state


def _propagate_bijection(
    state: dict[str, Any],
    placed_by_category: dict[str, set[tuple[str, int]]] | dict[str, dict[str, int]],
) -> None:
    """Re-derive every cell's ``possible`` list from the placed set so the
    StepState matches the StepKernel's ``placeValue`` propagation."""
    normalised: dict[str, set[tuple[str, int]]] = {}
    for category, value_set in placed_by_category.items():
        if isinstance(value_set, set):
            normalised[category] = set(value_set)
        else:
            normalised[category] = {(value, house) for value, house in value_set.items()}
    cells_by_key = {(cell["cat"], cell["house"]): cell for cell in state["cells"]}
    for (cat, house), target in cells_by_key.items():
        if target["placed"]:
            target["possible"] = [target["possible"][0]]
            continue
        placed_values = {value for value, _ in normalised.get(cat, set())}
        declared = [v for v in target["possible"] if v not in placed_values]
        target["possible"] = declared if declared else []
    state["cells"] = list(cells_by_key.values())


def _partial_state_with_singleton_drops(
    problem: dict[str, Any],
    reference: dict[str, dict[str, str]],
    rng: random.Random,
    *,
    drop_probability: float,
) -> dict[str, Any]:
    """Apply a small fraction of value eliminations and re-propagate the
    bijection so a StepState emerges with a mix of placed cells,
    singleton-forced cells, and multi-possibility cells.

    The algorithm is intentionally conservative: it only eliminates values
    that the bijection has *not* already fixed and only places a value when
    exactly one cell in its category still contains it. The state is
    guaranteed to be SAT-consistent under the bijection base.
    """
    state = initial_state(problem)
    houses = int(problem["size"]["houses"])
    eliminations: list[tuple[str, str, int]] = []
    for category in reference:
        declared = list(reference[category].values())
        actual_position = reference[category]
        for value in declared:
            actual_house = int(next(h for h, v in actual_position.items() if v == value))
            for house in range(1, houses + 1):
                if house == actual_house:
                    continue
                if rng.random() < drop_probability:
                    eliminations.append((category, value, house))
    for category, value, house in eliminations:
        target = cell(state, category, house)
        if target["placed"]:
            continue
        if value not in target["possible"]:
            continue
        target["possible"] = [v for v in target["possible"] if v != value]
    placed_by_category: dict[str, set[tuple[str, int]]] = {}
    changed = True
    while changed:
        changed = False
        for category in reference:
            for house in range(1, houses + 1):
                target = cell(state, category, house)
                if target["placed"] or len(target["possible"]) != 1:
                    continue
                value = target["possible"][0]
                target["placed"] = True
                placed_by_category.setdefault(category, set()).add((value, house))
                for other in state["cells"]:
                    if other["cat"] != category or int(other["house"]) == house:
                        continue
                    if other["placed"]:
                        continue
                    if value in other["possible"]:
                        other["possible"] = [v for v in other["possible"] if v != value]
                        if not other["possible"]:
                            other["possible"] = []
                changed = True
    return state


def generate_states(
    problem: dict[str, Any],
    reference: dict[str, dict[str, str]],
    *,
    seed: int,
    count: int,
) -> list[dict[str, Any]]:
    """Produce ``count`` partial StepStates drawn from a density distribution.

    The returned states are independent of Lean acceptance. The gate separately
    filters them by ``state_is_sat`` to remove inconsistent ones before the
    step-query phase.
    """
    states: list[dict[str, Any]] = []
    profiles = (
        (0.20, 0.30),
        (0.35, 0.30),
        (0.50, 0.40),
        (0.60, 0.40),
        (0.75, 0.50),
        (0.85, 0.50),
        (1.00, 0.60),
    )
    for index in range(count):
        max_fraction, drop_probability = profiles[index % len(profiles)]
        local_seed = (seed * 1_000_003 + index) & 0xFFFF_FFFF
        rng = random.Random(local_seed)
        state = _partial_state_with_singleton_drops(
            problem, reference, rng,
            drop_probability=drop_probability,
        )
        _scrub_state(state, rng, max_fraction=max_fraction, reference=reference)
        state["step_count"] = index
        states.append(state)
    return states


def _scrub_state(
    state: dict[str, Any],
    rng: random.Random,
    *,
    max_fraction: float,
    reference: dict[str, dict[str, str]],
) -> None:
    """Roll back some of the reference placements so the state matches the
    requested density profile, then re-propagate the bijection so the StepState
    faithfully matches what ``placeValue`` would produce in the StepKernel."""
    if max_fraction >= 0.999:
        return
    placements = [
        (cell["cat"], cell["possible"][0], cell["house"])
        for cell in state["cells"]
        if cell["placed"]
    ]
    rng.shuffle(placements)
    keep = max(0, int(len(placements) * max_fraction))
    rolled_back = placements[keep:]
    if not rolled_back:
        return
    placed_by_category: dict[str, set[tuple[str, int]]] = {}
    for category, value, house in placements[:keep]:
        placed_by_category.setdefault(category, set()).add((value, house))
    for category, value, house in rolled_back:
        for c in state["cells"]:
            if c["cat"] != category:
                continue
            if c["house"] == house:
                c["placed"] = False
        placed_by_category.get(category, set()).discard((value, house))
    _propagate_bijection(state, placed_by_category)


def _propagate_bijection(
    state: dict[str, Any],
    placed_by_category: dict[str, set[tuple[str, int]]] | dict[str, dict[str, int]],
) -> None:
    """Re-derive every cell's ``possible`` list from the placed set so the
    StepState matches the StepKernel's ``placeValue`` propagation."""
    normalised: dict[str, set[tuple[str, int]]] = {}
    for category, value_set in placed_by_category.items():
        if isinstance(value_set, set):
            normalised[category] = set(value_set)
        else:
            normalised[category] = {(value, house) for value, house in value_set.items()}
    cells_by_key = {(cell["cat"], cell["house"]): cell for cell in state["cells"]}
    for (cat, house), target in cells_by_key.items():
        if target["placed"]:
            target["possible"] = [target["possible"][0]]
            continue
        placed_values = {value for value, _ in normalised.get(cat, set())}
        declared = [v for v in target["possible"] if v not in placed_values]
        target["possible"] = declared if declared else []
    state["cells"] = list(cells_by_key.values())


def complete_state_from_reference(
    problem: dict[str, Any], reference: dict[str, dict[str, str]]
) -> dict[str, Any]:
    """Construct a fully placed StepState from a reference assignment."""
    state = initial_state(problem)
    for category, assignments in reference.items():
        for house, value in assignments.items():
            _apply_placement(state, category, value, int(house))
    return state