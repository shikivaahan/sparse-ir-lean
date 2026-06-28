#!/usr/bin/env python3
"""Broaden Stage 2 static-compiler rejection fuzzing across real Gate A problems.

This gate is an *extension* of Gate B. It does NOT replace Gate A or Gate B. It
generates a much larger set of deterministic mutated variants from real audited
Gate A ingested ZebraLogic problems, compiles each through the Lean Stage 2
compiler, and records every result. It also generates valid-preserving control
problems that should still compile, so that an unexpected rejection of a
control surfaces a likely compiler bug.

The gate never tests solving, candidate checking, traces, or providers.
"""

from __future__ import annotations

import argparse
import json
import random
import shlex
import shutil
import subprocess
import sys
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any


PROTOCOL_VERSION = "0.1.0"

REQUIRED_ERROR_CODES = (
    "unsupported_schema_version",
    "invalid_domain",
    "size_mismatch",
    "category_size_mismatch",
    "duplicate_value",
    "duplicate_clue_id",
    "unknown_category",
    "unknown_value",
    "house_out_of_range",
)

PARSER_REJECTION_KINDS = {
    "invalid_json",
    "invalid_schema",
    "expected_object",
    "missing_field",
    "unknown_field",
    "invalid_field_type",
    "invalid_value",
    "invalid_house",
    "unknown_clue_type",
}

UNARY_TYPES = {"found_at", "not_at"}
BINARY_TYPES = {
    "same_house",
    "direct_left",
    "direct_right",
    "side_by_side",
    "left_of",
    "right_of",
    "one_between",
    "two_between",
}


@dataclass(frozen=True)
class SourceProblem:
    problem_id: str
    external_id: str
    grid: str
    path: str
    problem: dict[str, Any]


@dataclass(frozen=True)
class Mutation:
    mutation_id: str
    source: SourceProblem
    mutation_kind: str
    mutation_subtype: str
    expected_error_code: str
    expected_error_path: str
    description: str
    before_snippet: str
    after_snippet: str
    problem: dict[str, Any]
    parser_rejection_expected: bool = False


@dataclass(frozen=True)
class Control:
    control_id: str
    source: SourceProblem
    control_kind: str
    description: str
    problem: dict[str, Any]


# ---------------------------------------------------------------------------
# I/O helpers


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"{path}:{line_number} is not a JSON object")
        rows.append(value)
    return rows


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _resolve(repo_root: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else repo_root / path


def _display(path: Path, repo_root: Path) -> str:
    root = repo_root.resolve()
    resolved = path.resolve()
    return (
        resolved.relative_to(root).as_posix()
        if resolved.is_relative_to(root)
        else resolved.as_posix()
    )


def _json_snippet(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


# ---------------------------------------------------------------------------
# Source loading


def load_gate_a_problems(repo_root: Path, gate_a_dir: Path) -> list[SourceProblem]:
    manifest = json.loads((gate_a_dir / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("gate") != "stage2_gate_a_compile_all" or manifest.get("status") != "pass":
        raise ValueError("Gate A manifest is missing or not passing")
    audit_manifest = gate_a_dir.parent / f"{gate_a_dir.name}_audit" / "manifest.json"
    if not audit_manifest.is_file():
        raise ValueError("passing Gate A dataset audit manifest is required")
    audit = json.loads(audit_manifest.read_text(encoding="utf-8"))
    if audit.get("status") != "pass" or audit.get("total_errors") != 0:
        raise ValueError("Gate A dataset audit is not passing with zero errors")
    rows = _read_jsonl(gate_a_dir / "source_manifest.jsonl")
    ingested = [row for row in rows if row.get("status") == "ingested"]
    if not ingested:
        raise ValueError("Gate A has no ingested real problems")
    problems: list[SourceProblem] = []
    for row in ingested:
        path_value = row.get("ingested_problem_path")
        if not isinstance(path_value, str):
            raise ValueError(
                f"Gate A source row has no ingested path: {row.get('problem_id')}"
            )
        path = _resolve(repo_root, path_value)
        problem = json.loads(path.read_text(encoding="utf-8"))
        source = problem.get("source") if isinstance(problem, dict) else None
        if (
            not isinstance(source, dict)
            or problem.get("id") != row.get("problem_id")
            or source.get("external_id") != row.get("external_id")
            or source.get("grid") != row.get("grid")
        ):
            raise ValueError(f"Gate A problem provenance mismatch: {path_value}")
        problems.append(
            SourceProblem(
                problem_id=row["problem_id"],
                external_id=row["external_id"],
                grid=row["grid"],
                path=path_value,
                problem=problem,
            )
        )
    if len(problems) != manifest.get("total_ingested"):
        raise ValueError("Gate A manifest/source problem count mismatch")
    return sorted(problems, key=lambda item: (item.grid, item.external_id))


def select_sources(
    problems: list[SourceProblem], max_per_grid: int, rng: random.Random
) -> list[SourceProblem]:
    selected: list[SourceProblem] = []
    for grid in sorted({problem.grid for problem in problems}):
        pool = sorted(
            [problem for problem in problems if problem.grid == grid],
            key=lambda item: item.external_id,
        )
        rng.shuffle(pool)
        selected.extend(pool[:max_per_grid])
    return sorted(selected, key=lambda item: (item.grid, item.external_id))


# ---------------------------------------------------------------------------
# Clue utilities


def _find_unary_clue(problem: dict[str, Any]) -> tuple[int, dict[str, Any]] | None:
    clues = problem.get("clues", [])
    for index, clue in enumerate(clues):
        if clue.get("type") in UNARY_TYPES:
            return index, clue
    return None


def _find_binary_clue(problem: dict[str, Any]) -> tuple[int, dict[str, Any]] | None:
    clues = problem.get("clues", [])
    for index, clue in enumerate(clues):
        if clue.get("type") in BINARY_TYPES:
            return index, clue
    return None


# ---------------------------------------------------------------------------
# Mutation factories


def _mutate_unsupported_schema_version(
    source: SourceProblem, value: str, subtype: str
) -> Mutation:
    problem = deepcopy(source.problem)
    before = problem["schema_version"]
    problem["schema_version"] = value
    parser_expected = value == ""
    return Mutation(
        mutation_id=f"unsupported_schema_version--{subtype}--{source.external_id}",
        source=source,
        mutation_kind="unsupported_schema_version",
        mutation_subtype=subtype,
        expected_error_code=(
            "invalid_value" if parser_expected else "unsupported_schema_version"
        ),
        expected_error_path="$.schema_version",
        description=f"Set schema_version to {value!r}.",
        before_snippet=_json_snippet(before),
        after_snippet=_json_snippet(problem["schema_version"]),
        problem=problem,
        parser_rejection_expected=parser_expected,
    )


def _mutate_invalid_domain(
    source: SourceProblem, value: str, subtype: str
) -> Mutation:
    problem = deepcopy(source.problem)
    before = problem["domain"]
    problem["domain"] = value
    parser_expected = value == ""
    return Mutation(
        mutation_id=f"invalid_domain--{subtype}--{source.external_id}",
        source=source,
        mutation_kind="invalid_domain",
        mutation_subtype=subtype,
        expected_error_code=(
            "invalid_value" if parser_expected else "invalid_domain"
        ),
        expected_error_path="$.domain",
        description=f"Set domain to {value!r}.",
        before_snippet=_json_snippet(before),
        after_snippet=_json_snippet(problem["domain"]),
        problem=problem,
        parser_rejection_expected=parser_expected,
    )


def _mutate_size_mismatch(
    source: SourceProblem, field_name: str, delta: int, subtype: str
) -> Mutation:
    problem = deepcopy(source.problem)
    before = problem["size"][field_name]
    problem["size"][field_name] = before + delta
    if field_name == "categories":
        expected_code = "size_mismatch"
        expected_path = "$.size.categories"
    else:
        # Mutating declared `houses` keeps the category values intact, so the
        # compiler falls through to the per-category size check on the first
        # category it inspects. The Stage 1 parser builds the category list
        # via `object.toList` on a `Std.TreeMap.Raw compare`, which yields
        # alphabetically-sorted keys. We pin the expected path to the first
        # alphabetically-sorted category name to match the compiler output.
        expected_code = "category_size_mismatch"
        categories = problem.get("categories", {})
        first_name = (
            sorted(name for name in categories.keys() if isinstance(name, str))[0]
            if categories
            else None
        )
        expected_path = (
            f"$.categories.{first_name}" if isinstance(first_name, str) else "$.categories["
        )
    return Mutation(
        mutation_id=f"size_mismatch--{subtype}--{source.external_id}",
        source=source,
        mutation_kind="size_mismatch",
        mutation_subtype=subtype,
        expected_error_code=expected_code,
        expected_error_path=expected_path,
        description=f"Adjusted declared {field_name} by {delta}.",
        before_snippet=_json_snippet(before),
        after_snippet=_json_snippet(problem["size"][field_name]),
        problem=problem,
    )


def _mutate_category_size_mismatch(
    source: SourceProblem, action: str, subtype: str
) -> Mutation | None:
    problem = deepcopy(source.problem)
    categories = problem.get("categories")
    if not isinstance(categories, dict) or not categories:
        return None
    name, values = next(
        (
            (n, list(v))
            for n, v in categories.items()
            if isinstance(v, list) and v
        ),
        (None, None),
    )
    if name is None or values is None:
        return None
    before = deepcopy(values)
    if action == "remove_first":
        values.pop(0)
        description = f"Removed first value from category {name}."
    elif action == "remove_last":
        values.pop()
        description = f"Removed last value from category {name}."
    elif action == "append":
        values.append(f"__gate_b_plus_extra_{name}")
        description = f"Appended a sentinel value to category {name}."
    elif action == "empty":
        values.clear()
        description = f"Emptied category {name}."
    else:
        raise ValueError(f"unsupported category_size_mismatch action: {action}")
    categories[name] = values
    parser_expected = action == "empty" and len(values) == 0
    return Mutation(
        mutation_id=f"category_size_mismatch--{subtype}--{source.external_id}",
        source=source,
        mutation_kind="category_size_mismatch",
        mutation_subtype=subtype,
        expected_error_code=(
            "invalid_value" if parser_expected else "category_size_mismatch"
        ),
        expected_error_path=f"$.categories.{name}",
        description=description,
        before_snippet=_json_snippet(before),
        after_snippet=_json_snippet(values),
        problem=problem,
        parser_rejection_expected=parser_expected,
    )


def _mutate_duplicate_value(
    source: SourceProblem, target: str, subtype: str
) -> Mutation | None:
    problem = deepcopy(source.problem)
    categories = problem.get("categories")
    if not isinstance(categories, dict):
        return None
    if target == "every_category":
        mutated = 0
        first_path: str | None = None
        # The Stage 1 parser emits categories in alphabetical order (via
        # `Std.TreeMap.Raw compare`), so the compiler reports the first
        # alphabetically-ordered category it finds with a duplicate value.
        for name in sorted(categories.keys()):
            values = categories.get(name)
            if isinstance(values, list) and len(values) >= 2:
                values[1] = values[0]
                categories[name] = values
                mutated += 1
                if first_path is None:
                    first_path = f"$.categories.{name}[1]"
        if mutated == 0 or first_path is None:
            return None
        description = "Duplicated a value inside every category that had >=2 values."
        before_snippet = "multiple categories"
        after_snippet = f"first values duplicated across {mutated} categories"
        expected_path = first_path
    else:
        name, values = next(
            (
                (n, list(v))
                for n, v in categories.items()
                if isinstance(v, list) and len(v) >= 2
            ),
            (None, None),
        )
        if name is None:
            return None
        before = deepcopy(values)
        if target == "first":
            values[1] = values[0]
            description = f"Duplicated the first value inside category {name}."
            expected_path = f"$.categories.{name}[1]"
        elif target == "last":
            dup_index = len(values) - 1
            values[dup_index] = values[dup_index - 1]
            description = f"Duplicated the last value inside category {name}."
            expected_path = f"$.categories.{name}[{dup_index}]"
        else:
            raise ValueError(f"unsupported duplicate_value target: {target}")
        categories[name] = values
        before_snippet = _json_snippet(before)
        after_snippet = _json_snippet(values)
    return Mutation(
        mutation_id=f"duplicate_value--{subtype}--{source.external_id}",
        source=source,
        mutation_kind="duplicate_value",
        mutation_subtype=subtype,
        expected_error_code="duplicate_value",
        expected_error_path=expected_path,
        description=description,
        before_snippet=before_snippet,
        after_snippet=after_snippet,
        problem=problem,
    )


def _mutate_duplicate_clue_id(
    source: SourceProblem, action: str, subtype: str
) -> Mutation | None:
    problem = deepcopy(source.problem)
    clues = problem.get("clues")
    if not isinstance(clues, list) or len(clues) < 2:
        return None
    before_id = clues[0]["id"]
    dup_index = 1
    if action == "first_to_second":
        clues[1]["id"] = clues[0]["id"]
        description = "Reused the first clue id on the second clue."
        dup_index = 1
    elif action == "last_to_first":
        clues[0]["id"] = clues[-1]["id"]
        description = "Reused the last clue id on the first clue."
        dup_index = len(clues) - 1
    elif action == "non_adjacent":
        if len(clues) >= 3:
            clues[2]["id"] = clues[1]["id"]
            description = "Reused a non-adjacent clue id."
            dup_index = 2
        else:
            clues[1]["id"] = clues[0]["id"]
            description = "Reused the first clue id on the second clue."
            dup_index = 1
    elif action == "three_clues":
        if len(clues) >= 3:
            shared = clues[0]["id"]
            clues[1]["id"] = shared
            clues[2]["id"] = shared
            description = "Reused the same id across three clues."
            dup_index = 1
        else:
            clues[1]["id"] = clues[0]["id"]
            description = "Reused the first clue id on the second clue."
            dup_index = 1
    else:
        raise ValueError(f"unsupported duplicate_clue_id action: {action}")
    return Mutation(
        mutation_id=f"duplicate_clue_id--{subtype}--{source.external_id}",
        source=source,
        mutation_kind="duplicate_clue_id",
        mutation_subtype=subtype,
        expected_error_code="duplicate_clue_id",
        expected_error_path=f"$.clues[{dup_index}].id",
        description=description,
        before_snippet=_json_snippet(before_id),
        after_snippet=_json_snippet(problem["clues"][0]["id"]),
        problem=problem,
    )


def _mutate_unknown_category(
    source: SourceProblem, target: str, subtype: str
) -> Mutation | None:
    problem = deepcopy(source.problem)
    clues = problem.get("clues")
    if not isinstance(clues, list):
        return None
    if target == "unary":
        found = _find_unary_clue(problem)
        if found is None:
            return None
        index, clue = found
        before = clue["cat"]
        clue["cat"] = f"__gate_b_plus_unknown_category_{subtype}__"
        path = f"$.clues[{index}].cat"
        description = f"Changed clue {clue['id']} cat to an undeclared name."
        after_value = problem["clues"][index]["cat"]
    else:
        found = _find_binary_clue(problem)
        if found is None:
            return None
        index, clue = found
        side = "a" if target == "binary_a" else "b"
        before = clue[side]["cat"]
        clue[side]["cat"] = f"__gate_b_plus_unknown_category_{subtype}__"
        path = f"$.clues[{index}].{side}.cat"
        description = (
            f"Changed clue {clue['id']} operand {side}.cat to an undeclared name."
        )
        after_value = problem["clues"][index][side]["cat"]
    return Mutation(
        mutation_id=f"unknown_category--{subtype}--{source.external_id}",
        source=source,
        mutation_kind="unknown_category",
        mutation_subtype=subtype,
        expected_error_code="unknown_category",
        expected_error_path=path,
        description=description,
        before_snippet=_json_snippet(before),
        after_snippet=_json_snippet(after_value),
        problem=problem,
    )


def _mutate_unknown_value(
    source: SourceProblem, target: str, subtype: str
) -> Mutation | None:
    problem = deepcopy(source.problem)
    clues = problem.get("clues")
    if not isinstance(clues, list):
        return None
    if target == "unary":
        found = _find_unary_clue(problem)
        if found is None:
            return None
        index, clue = found
        before = clue["val"]
        clue["val"] = f"__gate_b_plus_unknown_value_{subtype}__"
        path = f"$.clues[{index}].val"
        description = f"Changed clue {clue['id']} val to an undeclared value."
        after_value = problem["clues"][index]["val"]
    elif target in {"binary_a", "binary_b"}:
        found = _find_binary_clue(problem)
        if found is None:
            return None
        index, clue = found
        side = "a" if target == "binary_a" else "b"
        before = clue[side]["val"]
        clue[side]["val"] = f"__gate_b_plus_unknown_value_{subtype}__"
        path = f"$.clues[{index}].{side}.val"
        description = (
            f"Changed clue {clue['id']} operand {side}.val to an undeclared value."
        )
        after_value = problem["clues"][index][side]["val"]
    elif target == "wrong_category":
        # Use a known value (declared somewhere) but attribute it to a
        # category that does NOT list that value. The compiler checks the
        # category index first, then whether the value is declared in that
        # category, so a value from another category is "unknown" in the
        # chosen target category.
        found = _find_binary_clue(problem)
        if found is None:
            return None
        index, clue = found
        categories = problem.get("categories", {})
        original_cat = clue["a"]["cat"]
        original_val = clue["a"]["val"]
        # Pick an alternate category.
        alt_cats = [c for c in categories.keys() if c != original_cat]
        if not alt_cats:
            return None
        target_cat = alt_cats[0]
        # Pick a value declared in the original category but NOT in the
        # target category.
        original_values = categories.get(original_cat, [])
        target_values = set(categories.get(target_cat, []))
        alt_val = next(
            (v for v in original_values if v not in target_values),
            None,
        )
        if alt_val is None:
            # Fallback: pick any value from the original category.
            if not original_values:
                return None
            alt_val = original_values[0]
        before = {"cat": original_cat, "val": original_val}
        clue["a"] = {"cat": target_cat, "val": alt_val}
        description = (
            f"Moved clue {clue['id']} operand a to category {target_cat}"
            f" with value {alt_val!r} (which is not declared in {target_cat})."
        )
        path = f"$.clues[{index}].a.val"
        return Mutation(
            mutation_id=f"unknown_value--{subtype}--{source.external_id}",
            source=source,
            mutation_kind="unknown_value",
            mutation_subtype=subtype,
            expected_error_code="unknown_value",
            expected_error_path=path,
            description=description,
            before_snippet=_json_snippet(before),
            after_snippet=_json_snippet(clue["a"]),
            problem=problem,
        )
    else:
        raise ValueError(f"unsupported unknown_value target: {target}")
    return Mutation(
        mutation_id=f"unknown_value--{subtype}--{source.external_id}",
        source=source,
        mutation_kind="unknown_value",
        mutation_subtype=subtype,
        expected_error_code="unknown_value",
        expected_error_path=path,
        description=description,
        before_snippet=_json_snippet(before),
        after_snippet=_json_snippet(after_value),
        problem=problem,
    )


def _mutate_house_out_of_range(
    source: SourceProblem, target_house: int, subtype: str
) -> Mutation | None:
    problem = deepcopy(source.problem)
    found = _find_unary_clue(problem)
    if found is None:
        return None
    index, clue = found
    before = clue["house"]
    clue["house"] = target_house
    return Mutation(
        mutation_id=f"house_out_of_range--{subtype}--{source.external_id}",
        source=source,
        mutation_kind="house_out_of_range",
        mutation_subtype=subtype,
        expected_error_code="house_out_of_range",
        expected_error_path=f"$.clues[{index}].house",
        description=(
            f"Moved clue {clue['id']} to house {target_house} (out of range)."
        ),
        before_snippet=_json_snippet(before),
        after_snippet=_json_snippet(problem["clues"][index]["house"]),
        problem=problem,
    )


# ---------------------------------------------------------------------------
# Mutation plan


SCHEMA_VERSION_SUBTYPES = (
    ("version_0_1", "0.1"),
    ("version_0_3", "0.3"),
    ("version_1_0", "1.0"),
    ("version_empty", ""),
    ("version_label", "gate-b-plus"),
)

DOMAIN_SUBTYPES = (
    ("domain_empty", ""),
    ("domain_logic_grid", "logic_grid"),
    ("domain_zebra_logic", "zebra_logic"),
    ("domain_capitalized", "Zebra"),
    ("domain_label", "gate-b-plus-invalid"),
)

SIZE_MISMATCH_SUBTYPES = (
    ("categories_too_small", "categories", -1),
    ("categories_too_large", "categories", +1),
    ("houses_too_small", "houses", -1),
    ("houses_too_large", "houses", +1),
)

CATEGORY_SIZE_MISMATCH_SUBTYPES = (
    ("remove_first", "remove_first"),
    ("remove_last", "remove_last"),
    ("append_extra", "append"),
    ("empty_category", "empty"),
)

DUPLICATE_VALUE_SUBTYPES = (
    ("duplicate_first", "first"),
    ("duplicate_last", "last"),
    ("duplicate_every_category", "every_category"),
)

DUPLICATE_CLUE_ID_SUBTYPES = (
    ("first_to_second", "first_to_second"),
    ("last_to_first", "last_to_first"),
    ("non_adjacent", "non_adjacent"),
    ("three_clues", "three_clues"),
)

UNKNOWN_CATEGORY_SUBTYPES = (
    ("unary_cat", "unary"),
    ("binary_a_cat", "binary_a"),
    ("binary_b_cat", "binary_b"),
)

UNKNOWN_VALUE_SUBTYPES = (
    ("unary_val", "unary"),
    ("binary_a_val", "binary_a"),
    ("binary_b_val", "binary_b"),
    ("known_value_wrong_category", "wrong_category"),
    ("totally_unknown_value", "unary"),
)


def build_mutation_plan(source: SourceProblem) -> list[Mutation]:
    plan: list[Mutation] = []
    houses = source.problem["size"]["houses"]
    for subtype, value in SCHEMA_VERSION_SUBTYPES:
        plan.append(_mutate_unsupported_schema_version(source, value, subtype))
    for subtype, value in DOMAIN_SUBTYPES:
        plan.append(_mutate_invalid_domain(source, value, subtype))
    for subtype, field_name, delta in SIZE_MISMATCH_SUBTYPES:
        plan.append(_mutate_size_mismatch(source, field_name, delta, subtype))
    for subtype, action in CATEGORY_SIZE_MISMATCH_SUBTYPES:
        mutation = _mutate_category_size_mismatch(source, action, subtype)
        if mutation is not None:
            plan.append(mutation)
    for subtype, target in DUPLICATE_VALUE_SUBTYPES:
        mutation = _mutate_duplicate_value(source, target, subtype)
        if mutation is not None:
            plan.append(mutation)
    for subtype, action in DUPLICATE_CLUE_ID_SUBTYPES:
        mutation = _mutate_duplicate_clue_id(source, action, subtype)
        if mutation is not None:
            plan.append(mutation)
    for subtype, target in UNKNOWN_CATEGORY_SUBTYPES:
        mutation = _mutate_unknown_category(source, target, subtype)
        if mutation is not None:
            plan.append(mutation)
    for subtype, target in UNKNOWN_VALUE_SUBTYPES:
        if subtype == "totally_unknown_value":
            mutation = _mutate_unknown_value(source, "unary", subtype)
        else:
            mutation = _mutate_unknown_value(source, target, subtype)
        if mutation is not None:
            plan.append(mutation)
    plan.append(_mutate_house_out_of_range(source, 0, "house_zero"))
    plan.append(_mutate_house_out_of_range(source, houses + 1, "house_one_past_end"))
    plan.append(_mutate_house_out_of_range(source, houses + 100, "house_hundred_past_end"))
    return [item for item in plan if item is not None]


# ---------------------------------------------------------------------------
# Controls (valid-preserving)


def _control_reorder_categories(source: SourceProblem) -> Control:
    problem = deepcopy(source.problem)
    cats = problem["categories"]
    items = list(cats.items())
    cats.clear()
    for name, values in reversed(items):
        cats[name] = values
    return Control(
        control_id=f"control_reorder_categories--{source.external_id}",
        source=source,
        control_kind="reorder_categories",
        description="Reversed category key order without changing contents.",
        problem=problem,
    )


def _control_reorder_clues(source: SourceProblem) -> Control | None:
    problem = deepcopy(source.problem)
    clues = problem.get("clues")
    if not isinstance(clues, list) or len(clues) < 2:
        return None
    if len({clue["id"] for clue in clues}) != len(clues):
        return None
    problem["clues"] = list(reversed(clues))
    return Control(
        control_id=f"control_reorder_clues--{source.external_id}",
        source=source,
        control_kind="reorder_clues",
        description="Reversed the order of clues without changing contents.",
        problem=problem,
    )


def _control_reorder_values_within_category(source: SourceProblem) -> Control | None:
    problem = deepcopy(source.problem)
    cats = problem.get("categories")
    if not isinstance(cats, dict) or not cats:
        return None
    name, values = next(
        (
            (n, v)
            for n, v in cats.items()
            if isinstance(v, list) and len(v) >= 2
        ),
        (None, None),
    )
    if name is None or values is None:
        return None
    cats[name] = list(reversed(values))
    return Control(
        control_id=f"control_reorder_values--{source.external_id}",
        source=source,
        control_kind="reorder_values_within_category",
        description=f"Reversed the value order inside category {name}.",
        problem=problem,
    )


def _control_cross_category_duplicate(source: SourceProblem) -> Control | None:
    problem = deepcopy(source.problem)
    cats = problem.get("categories")
    if not isinstance(cats, dict) or len(cats) < 2:
        return None
    names = list(cats.keys())
    src_name = names[0]
    tgt_name = names[1]
    src_values = cats.get(src_name, [])
    if not src_values:
        return None
    duplicate_value = src_values[0]
    tgt_values = list(cats.get(tgt_name, []))
    if duplicate_value in tgt_values:
        return None
    tgt_values.append(duplicate_value)
    cats[tgt_name] = tgt_values
    new_houses = max(problem["size"]["houses"], len(tgt_values))
    problem["size"]["houses"] = new_houses
    for name, values in cats.items():
        if name == tgt_name:
            continue
        if isinstance(values, list) and len(values) < new_houses:
            padding = new_houses - len(values)
            values.extend(
                [f"__ctrl_padding_{name}_{i}__" for i in range(padding)]
            )
            cats[name] = values
    return Control(
        control_id=f"control_cross_category_duplicate--{source.external_id}",
        source=source,
        control_kind="cross_category_duplicate_value",
        description=(
            "Added a duplicate display string across two distinct categories"
            " without duplicating within either category."
        ),
        problem=problem,
    )


def build_controls(sources: list[SourceProblem]) -> list[Control]:
    controls: list[Control] = []
    for source in sources:
        controls.append(_control_reorder_categories(source))
        reorder_clues = _control_reorder_clues(source)
        if reorder_clues is not None:
            controls.append(reorder_clues)
        reorder_values = _control_reorder_values_within_category(source)
        if reorder_values is not None:
            controls.append(reorder_values)
        cross = _control_cross_category_duplicate(source)
        if cross is not None:
            controls.append(cross)
    return controls


# ---------------------------------------------------------------------------
# Compile / result handling


def _path_matches(expected: str, actual: Any) -> bool:
    if not isinstance(actual, str) or not actual:
        return False
    return actual.startswith(expected) if expected.endswith("[") else actual == expected


def invoke_lean(request: dict[str, Any], *, executable: Path) -> dict[str, Any]:
    completed = subprocess.run(
        [str(executable)],
        input=json.dumps(request),
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"Lean verifier exited with {completed.returncode}:"
            f" {completed.stderr.strip()}"
        )
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Lean verifier returned invalid JSON") from exc


def _compile_mutation(
    mutation: Mutation,
    mutated_path: str,
    invoke_fn: Callable[[dict[str, Any]], dict[str, Any]],
) -> dict[str, Any]:
    request = {
        "protocol_version": PROTOCOL_VERSION,
        "request_id": mutation.mutation_id,
        "command": "compile",
        "payload": {"problem": json.dumps(mutation.problem, ensure_ascii=False)},
    }
    base = {
        "mutation_id": mutation.mutation_id,
        "mutation_kind": mutation.mutation_kind,
        "mutation_subtype": mutation.mutation_subtype,
        "mutated_problem_path": mutated_path,
        "source_problem_id": mutation.source.problem_id,
        "expected_error_code": mutation.expected_error_code,
    }
    try:
        response = invoke_fn(request)
    except Exception as exc:  # noqa: BLE001
        return {
            **base,
            "actual_protocol_kind": None,
            "actual_error_code": None,
            "actual_error_path": None,
            "actual_error_message": str(exc),
            "status": "protocol_error",
        }
    if (
        not isinstance(response, dict)
        or response.get("protocol_version") != PROTOCOL_VERSION
        or response.get("request_id") != mutation.mutation_id
        or not isinstance(response.get("result"), dict)
    ):
        return {
            **base,
            "actual_protocol_kind": None,
            "actual_error_code": None,
            "actual_error_path": None,
            "actual_error_message": "malformed or mismatched verifier response",
            "status": "protocol_error",
        }
    result = response["result"]
    kind = result.get("kind")
    code = result.get("error_code")
    path = result.get("error_path")
    message = result.get("message")
    if kind == "COMPILED":
        status = "unexpected_compile"
    elif kind != "STATIC_ERROR" or not isinstance(code, str) or not isinstance(message, str):
        status = "protocol_error"
    elif mutation.parser_rejection_expected:
        status = (
            "parser_rejection_expected"
            if code in PARSER_REJECTION_KINDS
            else "wrong_error_code"
        )
    elif code != mutation.expected_error_code:
        status = "wrong_error_code"
    elif not _path_matches(mutation.expected_error_path, path):
        status = "missing_error_path"
    else:
        status = "expected_rejection"
    return {
        **base,
        "actual_protocol_kind": kind if isinstance(kind, str) else None,
        "actual_error_code": code if isinstance(code, str) else None,
        "actual_error_path": path if isinstance(path, str) else None,
        "actual_error_message": message if isinstance(message, str) else None,
        "status": status,
    }


def _compile_control(
    control: Control,
    control_path: str,
    invoke_fn: Callable[[dict[str, Any]], dict[str, Any]],
) -> dict[str, Any]:
    request = {
        "protocol_version": PROTOCOL_VERSION,
        "request_id": control.control_id,
        "command": "compile",
        "payload": {"problem": json.dumps(control.problem, ensure_ascii=False)},
    }
    base = {
        "control_id": control.control_id,
        "control_kind": control.control_kind,
        "control_problem_path": control_path,
        "source_problem_id": control.source.problem_id,
    }
    try:
        response = invoke_fn(request)
    except Exception as exc:  # noqa: BLE001
        return {
            **base,
            "actual_protocol_kind": None,
            "actual_error_code": None,
            "actual_error_path": None,
            "actual_error_message": str(exc),
            "status": "protocol_error",
        }
    if (
        not isinstance(response, dict)
        or response.get("protocol_version") != PROTOCOL_VERSION
        or response.get("request_id") != control.control_id
        or not isinstance(response.get("result"), dict)
    ):
        return {
            **base,
            "actual_protocol_kind": None,
            "actual_error_code": None,
            "actual_error_path": None,
            "actual_error_message": "malformed or mismatched verifier response",
            "status": "protocol_error",
        }
    result = response["result"]
    kind = result.get("kind")
    code = result.get("error_code")
    path = result.get("error_path")
    message = result.get("message")
    if kind == "COMPILED":
        status = "compiled"
    elif kind == "STATIC_ERROR":
        status = "unexpected_rejection"
    else:
        status = "protocol_error"
    return {
        **base,
        "actual_protocol_kind": kind if isinstance(kind, str) else None,
        "actual_error_code": code if isinstance(code, str) else None,
        "actual_error_path": path if isinstance(path, str) else None,
        "actual_error_message": message if isinstance(message, str) else None,
        "status": status,
    }


def _default_invoke(repo_root: Path) -> Callable[[dict[str, Any]], dict[str, Any]]:
    lake = shutil.which("lake")
    if lake is None:
        raise RuntimeError("lake is required to build the Stage 2 compiler")
    subprocess.run([lake, "build", "sparse-ir-lean"], cwd=repo_root, check=True)
    executable = repo_root / ".lake/build/bin/sparse-ir-lean"
    if not executable.is_file():
        raise RuntimeError(f"Lean compiler executable was not built: {executable}")
    return partial(invoke_lean, executable=executable)


# ---------------------------------------------------------------------------
# Row builders


def _mutation_row(mutation: Mutation, mutated_path: str) -> dict[str, Any]:
    return {
        "mutation_id": mutation.mutation_id,
        "source_problem_id": mutation.source.problem_id,
        "source_external_id": mutation.source.external_id,
        "source_grid": mutation.source.grid,
        "source_problem_path": mutation.source.path,
        "mutated_problem_path": mutated_path,
        "mutation_kind": mutation.mutation_kind,
        "mutation_subtype": mutation.mutation_subtype,
        "expected_error_code": mutation.expected_error_code,
        "expected_error_path_prefix_or_exact": mutation.expected_error_path,
        "description": mutation.description,
        "before_snippet": mutation.before_snippet,
        "after_snippet": mutation.after_snippet,
        "parser_rejection_expected": mutation.parser_rejection_expected,
    }


def _control_row(control: Control, control_path: str) -> dict[str, Any]:
    return {
        "control_id": control.control_id,
        "source_problem_id": control.source.problem_id,
        "source_external_id": control.source.external_id,
        "source_grid": control.source.grid,
        "source_problem_path": control.source.path,
        "control_problem_path": control_path,
        "control_kind": control.control_kind,
        "description": control.description,
    }


# ---------------------------------------------------------------------------
# Reporting


def _mutation_examples_md(
    mutations: list[dict[str, Any]], results: list[dict[str, Any]]
) -> str:
    results_by_id = {row["mutation_id"]: row for row in results}
    lines: list[str] = ["# Stage 2 Gate B+ mutation examples", ""]
    by_code: dict[str, list[dict[str, Any]]] = {}
    for row in mutations:
        by_code.setdefault(row["mutation_kind"], []).append(row)
    for error_code in REQUIRED_ERROR_CODES:
        rows = by_code.get(error_code, [])
        if not rows:
            lines.append(f"## `{error_code}`\n\nNo mutations generated for this code.\n")
            continue
        lines.append(f"## `{error_code}`\n")
        seen_subtypes: set[str] = set()
        for row in rows:
            if row["mutation_subtype"] in seen_subtypes:
                continue
            seen_subtypes.add(row["mutation_subtype"])
            result = results_by_id.get(row["mutation_id"], {})
            lines.extend(
                [
                    f"### subtype `{row['mutation_subtype']}`",
                    "",
                    (
                        "- Source problem: `"
                        f"{row['source_problem_id']}`"
                        f" (grid `{row['source_grid']}`)"
                    ),
                    f"- Mutation: {row['description']}",
                    f"- Expected error code: `{row['expected_error_code']}`",
                    f"- Actual error code: `{result.get('actual_error_code')}`",
                    f"- Actual error path: `{result.get('actual_error_path')}`",
                    f"- Status: `{result.get('status')}`",
                    f"- Before: `{row['before_snippet']}`",
                    f"- After: `{row['after_snippet']}`",
                    "",
                ]
            )
    return "\n".join(lines)


def _summary_md(
    command: str,
    seed: int,
    manifest: dict[str, Any],
    findings: list[dict[str, Any]],
) -> str:
    lines: list[str] = [
        "# Stage 2 Gate B+: broader fuzzing",
        "",
        f"- Exact command run: `{command}`",
        f"- Seed: `{seed}`",
        f"- Status: **{manifest['status'].upper()}**",
        f"- Total source problems available: {manifest['total_source_problems_available']}",
        f"- Total source problems used: {manifest['total_source_problems_used']}",
        f"- Total mutations generated: {manifest['total_mutations_generated']}",
        f"- Total rejected: {manifest['total_rejected']}",
        f"- Total unexpected compiled: {manifest['total_unexpected_compiled']}",
        f"- Total wrong error code: {manifest['total_wrong_error_code']}",
        f"- Total missing error path: {manifest['total_missing_error_path']}",
        f"- Total controls generated: {manifest['total_controls_generated']}",
        f"- Total controls compiled: {manifest['total_controls_compiled']}",
        f"- Total controls rejected: {manifest['total_controls_rejected']}",
        "",
        "## Error-code coverage",
        "",
        "| Error code | Mutations |",
        "|---|---:|",
    ]
    for code in REQUIRED_ERROR_CODES:
        lines.append(f"| `{code}` | {manifest['error_code_coverage'].get(code, 0)} |")
    lines.extend(
        [
            "",
            "## Mutation-subtype coverage",
            "",
            "| Mutation kind | Subtype | Count |",
            "|---|---|---:|",
        ]
    )
    for kind, subtypes in manifest["mutation_subtype_coverage"].items():
        for subtype, count in sorted(subtypes.items()):
            lines.append(f"| `{kind}` | `{subtype}` | {count} |")
    grids = sorted(
        set(manifest["grid_coverage"].keys())
        | set(manifest.get("grid_control_coverage", {}).keys())
    )
    lines.extend(
        ["", "## Grid coverage", "", "| Grid | Mutations | Controls |", "|---|---:|---:|"]
    )
    for grid in grids:
        lines.append(
            "| `{grid}` | {muts} | {ctrls} |".format(
                grid=grid,
                muts=manifest["grid_coverage"].get(grid, 0),
                ctrls=manifest.get("grid_control_coverage", {}).get(grid, 0),
            )
        )
    lines.extend(
        [
            "",
            "## Findings (error-severity only shown above pass threshold)",
            "",
            f"- Total findings: {len(findings)}",
            f"- Error-severity findings:"
            f" {sum(1 for f in findings if f.get('severity') == 'error')}",
            "",
            "## Artifacts",
            "",
            "- `eval/gates/stage2_gate_b_plus_fuzz/manifest.json`",
            "- `eval/gates/stage2_gate_b_plus_fuzz/mutations.jsonl`",
            "- `eval/gates/stage2_gate_b_plus_fuzz/results.jsonl`",
            "- `eval/gates/stage2_gate_b_plus_fuzz/controls.jsonl`",
            "- `eval/gates/stage2_gate_b_plus_fuzz/control_results.jsonl`",
            "- `eval/gates/stage2_gate_b_plus_fuzz/findings.jsonl`",
            "- `eval/gates/stage2_gate_b_plus_fuzz/mutation_examples.md`",
            "",
            "## Rerun Gate B+",
            "",
            f"```bash\n{command}\n```",
            "",
            "## Outcome",
            "",
            f"- Gate B+ **{'PASSED' if manifest['status'] == 'pass' else 'FAILED'}**",
            "",
        ]
    )
    return "\n".join(lines)


def _build_findings(
    results: list[dict[str, Any]],
    control_results: list[dict[str, Any]],
    parse_rejections_unexpected: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for row in results:
        status = row["status"]
        if status in {"expected_rejection", "parser_rejection_expected"}:
            continue
        findings.append(
            {
                "severity": "error",
                "kind": status,
                "problem_id": row.get("source_problem_id"),
                "mutation_id_or_control_id": row.get("mutation_id"),
                "message": (
                    f"{row['mutation_kind']}/{row['mutation_subtype']} on"
                    f" {row['mutated_problem_path']} returned status {status};"
                    f" actual={row.get('actual_error_code')!r} at"
                    f" {row.get('actual_error_path')!r}"
                ),
                "path": row.get("actual_error_path"),
            }
        )
    for row in control_results:
        if row["status"] == "compiled":
            continue
        findings.append(
            {
                "severity": "error",
                "kind": row["status"],
                "problem_id": row.get("source_problem_id"),
                "mutation_id_or_control_id": row.get("control_id"),
                "message": (
                    f"control {row['control_kind']} on"
                    f" {row['control_problem_path']} returned status"
                    f" {row['status']}; actual={row.get('actual_error_code')!r} at"
                    f" {row.get('actual_error_path')!r}"
                ),
                "path": row.get("actual_error_path"),
            }
        )
    findings.extend(parse_rejections_unexpected)
    return findings


# ---------------------------------------------------------------------------
# Gate driver


def run_gate(
    repo_root: Path,
    gate_a_dir: Path,
    output_dir: Path,
    seed: int,
    max_per_grid: int,
    command: str,
    *,
    invoke_fn: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    sources: list[SourceProblem] | None = None,
) -> tuple[int, dict[str, Any]]:
    repo_root = repo_root.resolve()
    gate_a_dir = gate_a_dir.resolve()
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    mutated_dir = output_dir / "mutated_problems"
    if mutated_dir.exists():
        shutil.rmtree(mutated_dir)
    mutated_dir.mkdir()
    control_dir = output_dir / "control_problems"
    if control_dir.exists():
        shutil.rmtree(control_dir)
    control_dir.mkdir()

    rng = random.Random(seed)
    setup_failure: dict[str, Any] | None = None
    parse_rejections_unexpected: list[dict[str, Any]] = []
    available: list[SourceProblem] = []
    selected: list[SourceProblem] = []
    mutations: list[Mutation] = []
    controls: list[Control] = []

    try:
        available = (
            sources if sources is not None else load_gate_a_problems(repo_root, gate_a_dir)
        )
        selected = select_sources(available, max_per_grid, rng)
        if not selected:
            raise ValueError("no source problems selected for fuzzing")
        for source in selected:
            mutations.extend(build_mutation_plan(source))
        controls = build_controls(selected)
    except Exception as exc:  # noqa: BLE001
        setup_failure = {
            "severity": "error",
            "kind": "setup_error",
            "message": str(exc),
        }

    error_code_coverage = {
        code: sum(
            mutation.expected_error_code == code and not mutation.parser_rejection_expected
            for mutation in mutations
        )
        for code in REQUIRED_ERROR_CODES
    }
    mutation_subtype_coverage: dict[str, dict[str, int]] = {}
    for mutation in mutations:
        if mutation.parser_rejection_expected:
            continue
        mutation_subtype_coverage.setdefault(mutation.mutation_kind, {})
        mutation_subtype_coverage[mutation.mutation_kind][mutation.mutation_subtype] = (
            mutation_subtype_coverage[mutation.mutation_kind].get(
                mutation_subtype_coverage[mutation.mutation_kind].get(mutation.mutation_subtype, 0) if False else mutation.mutation_subtype,
                0,
            )
            + 1
        )

    if invoke_fn is None and mutations and setup_failure is None:
        try:
            invoke_fn = _default_invoke(repo_root)
        except Exception as exc:  # noqa: BLE001
            invoke_fn = None
            setup_failure = {
                "severity": "error",
                "kind": "verifier_unavailable",
                "message": str(exc),
            }

    mutation_rows: list[dict[str, Any]] = []
    result_rows: list[dict[str, Any]] = []
    for mutation in mutations:
        target = mutated_dir / f"{mutation.mutation_id}.problem.json"
        _write_text(
            target, json.dumps(mutation.problem, ensure_ascii=False, indent=2) + "\n"
        )
        display_path = _display(target, repo_root)
        mutation_rows.append(_mutation_row(mutation, display_path))
        if invoke_fn is not None:
            result_rows.append(_compile_mutation(mutation, display_path, invoke_fn))

    control_rows: list[dict[str, Any]] = []
    control_result_rows: list[dict[str, Any]] = []
    for control in controls:
        target = control_dir / f"{control.control_id}.problem.json"
        _write_text(
            target, json.dumps(control.problem, ensure_ascii=False, indent=2) + "\n"
        )
        display_path = _display(target, repo_root)
        control_rows.append(_control_row(control, display_path))
        if invoke_fn is not None:
            control_result_rows.append(
                _compile_control(control, display_path, invoke_fn)
            )

    findings = _build_findings(
        result_rows, control_result_rows, parse_rejections_unexpected
    )
    if setup_failure is not None:
        findings.append(setup_failure)

    rejected = sum(
        1
        for row in result_rows
        if row["status"] in {"expected_rejection", "parser_rejection_expected"}
    )
    unexpected = sum(row["status"] == "unexpected_compile" for row in result_rows)
    wrong = sum(row["status"] == "wrong_error_code" for row in result_rows)
    missing = sum(row["status"] == "missing_error_path" for row in result_rows)
    controls_compiled = sum(row["status"] == "compiled" for row in control_result_rows)
    controls_rejected = sum(
        row["status"] == "unexpected_rejection" for row in control_result_rows
    )
    grid_coverage = {
        grid: sum(mutation.source.grid == grid for mutation in mutations)
        for grid in sorted({mutation.source.grid for mutation in mutations})
    }
    grid_control_coverage = {
        grid: sum(control.source.grid == grid for control in controls)
        for grid in sorted({control.source.grid for control in controls})
    }

    grids_present = {problem.grid for problem in selected}
    missing_required_grids = sorted(
        grid
        for grid in ("2x2", "4x4", "6x6")
        if grid in grids_present and grid_coverage.get(grid, 0) == 0
    )

    error_severity_count = sum(1 for finding in findings if finding.get("severity") == "error")
    passed = (
        setup_failure is None
        and bool(mutations)
        and len(mutations) >= 300
        and len(result_rows) == len(mutations)
        and rejected == len(mutations)
        and unexpected == 0
        and wrong == 0
        and missing == 0
        and bool(controls)
        and controls_compiled == len(controls)
        and controls_rejected == 0
        and all(count > 0 for count in error_code_coverage.values())
        and not missing_required_grids
        and error_severity_count == 0
    )

    manifest = {
        "gate": "stage2_gate_b_plus_fuzz",
        "status": "pass" if passed else "fail",
        "seed": seed,
        "total_source_problems_available": len(available),
        "total_source_problems_used": len(selected),
        "total_mutations_generated": len(mutations),
        "total_rejected": rejected,
        "total_unexpected_compiled": unexpected,
        "total_wrong_error_code": wrong,
        "total_missing_error_path": missing,
        "total_controls_generated": len(controls),
        "total_controls_compiled": controls_compiled,
        "total_controls_rejected": controls_rejected,
        "error_code_coverage": error_code_coverage,
        "mutation_subtype_coverage": mutation_subtype_coverage,
        "grid_coverage": grid_coverage,
        "grid_control_coverage": grid_control_coverage,
        "missing_required_grids": missing_required_grids,
        "findings": findings,
    }
    _write_jsonl(output_dir / "mutations.jsonl", mutation_rows)
    _write_jsonl(output_dir / "results.jsonl", result_rows)
    _write_jsonl(output_dir / "controls.jsonl", control_rows)
    _write_jsonl(output_dir / "control_results.jsonl", control_result_rows)
    _write_jsonl(output_dir / "findings.jsonl", findings)
    _write_text(
        output_dir / "mutation_examples.md",
        _mutation_examples_md(mutation_rows, result_rows),
    )
    _write_text(output_dir / "summary.md", _summary_md(command, seed, manifest, findings))
    _write_text(
        output_dir / "manifest.json",
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
    )
    return (0 if passed else 1), manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gate-a-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--seed", required=True, type=int)
    parser.add_argument("--max-problems-per-grid", required=True, type=int)
    args = parser.parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    gate_a_dir = (
        args.gate_a_dir
        if args.gate_a_dir.is_absolute()
        else repo_root / args.gate_a_dir
    )
    output_dir = args.output if args.output.is_absolute() else repo_root / args.output
    command = shlex.join(
        ["uv", "run", "python", "scripts/stage2_gate_b_plus_fuzz.py", *sys.argv[1:]]
    )
    exit_code, manifest = run_gate(
        repo_root,
        gate_a_dir,
        output_dir,
        args.seed,
        args.max_problems_per_grid,
        command,
    )
    print(
        "Stage 2 Gate B+: {status} ({rejected}/{total} rejected,"
        " controls {ctrls}/{ctrl_total})".format(
            status=manifest["status"].upper(),
            rejected=manifest["total_rejected"],
            total=manifest["total_mutations_generated"],
            ctrls=manifest["total_controls_compiled"],
            ctrl_total=manifest["total_controls_generated"],
        )
    )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
