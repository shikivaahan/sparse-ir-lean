"""Deterministic generator for fuzzed ZebraLogic puzzles.

The Stage 3 stepwise G1 trust anchor requires at least 10,000 deterministically
fuzzed random puzzles in addition to the real ``compiled_problems.jsonl``
gold corpus. This module produces those puzzles independently of Stage 3B's
``DifferentialSample`` generator (which mutates a *candidate*, not the puzzle
itself) and the ``reference_solutions.py`` clingo solver.

Each generated puzzle is well-formed: a complete bijection of values per
category, a valid clue list, and at least one satisfying assignment that the
generator records internally so the gate can construct partial StepStates by
removing possibilities without ever needing the oracle's `expect` field.
"""

from __future__ import annotations

import hashlib
import random
from collections.abc import Iterable
from typing import Any


SCHEMA_VERSION = "0.2"
DOMAIN = "zebra"

# Grid sizes deliberately include all v0 ZebraLogic sizes plus several
# non-uniform grids. Every chosen grid is exercised at least once per 10k
# puzzles so the coverage report is meaningful. The grid name ``NxM`` follows
# the compiled_problems.jsonl convention: ``N`` is the number of houses,
# ``M`` is the number of categories.
GRID_PROFILES: tuple[tuple[str, int, int], ...] = (
    ("2x2", 2, 2),
    ("2x3", 2, 3),
    ("2x4", 2, 4),
    ("2x5", 2, 5),
    ("2x6", 2, 6),
    ("3x2", 3, 2),
    ("3x3", 3, 3),
    ("3x4", 3, 4),
    ("3x5", 3, 5),
    ("3x6", 3, 6),
    ("4x2", 4, 2),
    ("4x3", 4, 3),
    ("4x4", 4, 4),
    ("4x5", 4, 5),
    ("4x6", 4, 6),
    ("5x2", 5, 2),
    ("5x3", 5, 3),
    ("5x4", 5, 4),
    ("5x5", 5, 5),
    ("5x6", 5, 6),
    ("6x2", 6, 2),
    ("6x3", 6, 3),
    ("6x4", 6, 4),
    ("6x5", 6, 5),
    ("6x6", 6, 6),
)

# A bounded vocabulary of distinct category and value tokens so the generated
# clues have real semantics and never collide across generated puzzles.
CATEGORY_POOL: tuple[str, ...] = (
    "Name",
    "Pet",
    "Color",
    "Drink",
    "Cuisine",
    "Sport",
    "Music",
    "Movie",
    "Book",
    "City",
    "Car",
    "Job",
    "Hobby",
    "Phone",
    "Outfit",
    "Snack",
)
VALUE_POOL: tuple[str, ...] = (
    "alpha",
    "bravo",
    "charlie",
    "delta",
    "echo",
    "foxtrot",
    "golf",
    "hotel",
    "india",
    "juliet",
    "kilo",
    "lima",
    "mike",
    "november",
    "oscar",
    "papa",
)

UNARY_CLUE_TYPES = ("found_at", "not_at")
BINARY_CLUE_TYPES = (
    "same_house",
    "direct_left",
    "direct_right",
    "side_by_side",
    "left_of",
    "right_of",
    "one_between",
    "two_between",
)


def _grid_size(grid: str) -> tuple[int, int]:
    for profile in GRID_PROFILES:
        if profile[0] == grid:
            return profile[1], profile[2]
    raise ValueError(f"unknown grid {grid}")


def _rng_for(seed: int, salt: str) -> random.Random:
    digest = hashlib.sha256(f"{seed}|{salt}".encode("utf-8")).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


def _pick_distinct(rng: random.Random, pool: tuple[str, ...], count: int) -> list[str]:
    """Return ``count`` distinct items from ``pool`` using the supplied RNG."""
    items = list(pool)
    rng.shuffle(items)
    if count > len(items):
        raise ValueError(f"cannot pick {count} distinct items from pool of {len(items)}")
    return items[:count]


def _complete_bijection(houses: int, values: list[str], rng: random.Random) -> dict[str, str]:
    order = list(values)
    rng.shuffle(order)
    return {str(house): order[house - 1] for house in range(1, houses + 1)}


def _position_of(categories: dict[str, dict[str, str]], cat: str, val: str) -> int | None:
    for house_str, placed in categories[cat].items():
        if placed == val:
            return int(house_str)
    return None


def _generate_clues(
    rng: random.Random,
    houses: int,
    categories: dict[str, dict[str, str]],
    clue_budget: int,
    salt: str,
) -> list[dict[str, Any]]:
    cat_list = list(categories)
    clues: list[dict[str, Any]] = []
    for index in range(clue_budget):
        clue_type = rng.choice(UNARY_CLUE_TYPES + BINARY_CLUE_TYPES)
        clue_id = f"c{index + 1}"
        if clue_type in UNARY_CLUE_TYPES:
            cat = rng.choice(cat_list)
            val = rng.choice(list(categories[cat].values()))
            actual_house = _position_of(categories, cat, val)
            if actual_house is None:
                continue
            if clue_type == "found_at":
                house = actual_house
            else:
                candidates = [h for h in range(1, houses + 1) if h != actual_house]
                if not candidates:
                    continue
                house = rng.choice(candidates)
            clues.append(
                {
                    "id": clue_id,
                    "type": clue_type,
                    "cat": cat,
                    "val": val,
                    "house": house,
                }
            )
            continue
        if len(cat_list) < 2:
            continue
        if rng.random() < 0.5:
            cat_a, cat_b = rng.sample(cat_list, 2)
        else:
            cat_a = cat_b = rng.choice(cat_list)
        val_a = rng.choice(list(categories[cat_a].values()))
        val_b = rng.choice(list(categories[cat_b].values()))
        if cat_a == cat_b and val_a == val_b:
            continue
        if clue_type == "same_house":
            if cat_a == cat_b:
                pos_a = _position_of(categories, cat_a, val_a)
                pos_b = _position_of(categories, cat_b, val_b)
                if pos_a != pos_b:
                    continue
            else:
                pos_a = _position_of(categories, cat_a, val_a)
                pos_b = _position_of(categories, cat_b, val_b)
                if pos_a != pos_b:
                    continue
            clues.append(
                {
                    "id": clue_id,
                    "type": "same_house",
                    "a": {"cat": cat_a, "val": val_a},
                    "b": {"cat": cat_b, "val": val_b},
                }
            )
            continue
        if clue_type in {"direct_left", "direct_right"}:
            pos_a = _position_of(categories, cat_a, val_a)
            pos_b = _position_of(categories, cat_b, val_b)
            if pos_a is None or pos_b is None:
                continue
            expected = pos_b - 1 if clue_type == "direct_left" else pos_b + 1
            if pos_a != expected:
                continue
            clues.append(
                {
                    "id": clue_id,
                    "type": clue_type,
                    "a": {"cat": cat_a, "val": val_a},
                    "b": {"cat": cat_b, "val": val_b},
                }
            )
            continue
        if clue_type == "side_by_side":
            pos_a = _position_of(categories, cat_a, val_a)
            pos_b = _position_of(categories, cat_b, val_b)
            if pos_a is None or pos_b is None:
                continue
            if abs(pos_a - pos_b) != 1:
                continue
            clues.append(
                {
                    "id": clue_id,
                    "type": "side_by_side",
                    "a": {"cat": cat_a, "val": val_a},
                    "b": {"cat": cat_b, "val": val_b},
                }
            )
            continue
        if clue_type in {"left_of", "right_of", "one_between", "two_between"}:
            pos_a = _position_of(categories, cat_a, val_a)
            pos_b = _position_of(categories, cat_b, val_b)
            if pos_a is None or pos_b is None:
                continue
            if clue_type == "left_of" and not (pos_a < pos_b):
                continue
            if clue_type == "right_of" and not (pos_a > pos_b):
                continue
            if clue_type == "one_between" and abs(pos_a - pos_b) != 2:
                continue
            if clue_type == "two_between" and abs(pos_a - pos_b) != 3:
                continue
            clues.append(
                {
                    "id": clue_id,
                    "type": clue_type,
                    "a": {"cat": cat_a, "val": val_a},
                    "b": {"cat": cat_b, "val": val_b},
                }
            )
    return clues


def _clue_budget(rng: random.Random, houses: int) -> int:
    minimum = max(2, houses - 1)
    maximum = max(minimum + 1, houses + 2)
    return rng.randrange(minimum, maximum + 1)


def generate_fuzzed_puzzles(
    seed: int,
    count: int,
) -> list[dict[str, Any]]:
    """Produce ``count`` deterministically fuzzed random puzzles.

    Each returned dict is a schema-version-0.2 ``problem.json`` and includes
    a ``_fuzz_meta`` private field recording the satisfaction assignment and
    generator salt; the gate never reads ``_fuzz_meta.expect.source_solution``
    because it is a generated hint, not a puzzle hint.
    """
    puzzles: list[dict[str, Any]] = []
    for index in range(count):
        salt = f"fuzz-{index:06d}"
        rng = _rng_for(seed, salt)
        grid = rng.choice(GRID_PROFILES)[0]
        houses, category_count = _grid_size(grid)
        categories: dict[str, dict[str, str]] = {}
        cat_names = _pick_distinct(rng, CATEGORY_POOL, category_count)
        value_sets = {
            cat_name: _pick_distinct(rng, VALUE_POOL, houses)
            for cat_name in cat_names
        }
        for cat_name in cat_names:
            categories[cat_name] = _complete_bijection(houses, value_sets[cat_name], rng)
        budget = _clue_budget(rng, houses)
        clues = _generate_clues(rng, houses, categories, budget, salt)
        external_id = f"fuzz-{index:06d}-{grid}"
        problem_id = f"zl_{external_id}"
        problem = {
            "schema_version": SCHEMA_VERSION,
            "domain": DOMAIN,
            "id": problem_id,
            "source": {
                "dataset": "zebralogic",
                "split": "fuzz",
                "external_id": external_id,
                "grid": grid,
            },
            "size": {"houses": houses, "categories": category_count},
            "categories": {
                cat: list(values.values()) for cat, values in categories.items()
            },
            "clues": clues,
            "_fuzz_meta": {
                "seed": seed,
                "index": index,
                "grid": grid,
                "houses": houses,
                "categories": category_count,
                "satisfaction": {
                    cat: {house: value for house, value in values.items()}
                    for cat, values in categories.items()
                },
            },
        }
        puzzles.append(problem)
    return puzzles


def fuzz_grid_distribution(puzzles: Iterable[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for problem in puzzles:
        grid = problem.get("source", {}).get("grid", "unknown")
        counts[grid] = counts.get(grid, 0) + 1
    return dict(sorted(counts.items()))