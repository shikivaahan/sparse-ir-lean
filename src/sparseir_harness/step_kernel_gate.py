"""Deterministic Stage 3C evidence over real puzzle-derived single steps."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .reference_solutions import ROOT, _invoke_lean


SUPPORTED_RULES = (
    "given_found_at_place",
    "given_not_at_eliminate",
    "bijection_place_eliminates_same_value_other_houses",
    "bijection_place_eliminates_other_values_same_house",
    "bijection_cell_singleton_forces_place",
    "bijection_value_singleton_forces_place",
    "same_house_place_from_placed",
    "same_house_eliminate_no_possible_match",
    "direct_left_place_from_fixed",
    "direct_left_eliminate_no_possible_partner",
    "direct_right_place_from_fixed",
    "direct_right_eliminate_no_possible_partner",
    "side_by_side_place_from_single_neighbor",
    "side_by_side_eliminate_no_possible_neighbor",
    "left_of_eliminate_impossible_order",
    "right_of_eliminate_impossible_order",
    "one_between_place_from_fixed",
    "one_between_eliminate_no_possible_partner",
    "two_between_place_from_fixed",
    "two_between_eliminate_no_possible_partner",
    "solved_conclusion",
    "contradiction_detection",
)
REJECTION_CODES = (
    "malformed_step",
    "unknown_category",
    "unknown_value",
    "house_out_of_range",
    "unknown_clue_ref",
    "rule_clue_mismatch",
    "contradicts_state",
    "placement_conflict",
    "not_forced",
    "unsupported_rule",
    "invalid_conclusion",
    "incomplete_final",
    "clue_violation_final",
    "max_steps_exceeded",
)
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


@dataclass
class StepCase:
    case_id: str
    problem: dict[str, Any]
    state: dict[str, Any] | None
    step: dict[str, Any] | str | None
    command: str
    expected_kind: str
    expected_failure_code: str | None = None
    supported_rule: str | None = None
    clue_type: str | None = None
    rejection_code: str | None = None


def initial_state(problem: dict[str, Any]) -> dict[str, Any]:
    cells = []
    for category, values in problem["categories"].items():
        for house in range(1, problem["size"]["houses"] + 1):
            cells.append(
                {
                    "cat": category,
                    "house": house,
                    "possible": list(values),
                    "placed": False,
                }
            )
    return {"step_count": 0, "cells": cells}


def _cell(state: dict[str, Any], category: str, house: int) -> dict[str, Any]:
    return next(
        cell for cell in state["cells"] if cell["cat"] == category and cell["house"] == house
    )


def _set_placed(state: dict[str, Any], attribute: dict[str, str], house: int) -> None:
    cell = _cell(state, attribute["cat"], house)
    cell["possible"] = [attribute["val"]]
    cell["placed"] = True


def _remove(state: dict[str, Any], attribute: dict[str, str], house: int) -> None:
    cell = _cell(state, attribute["cat"], house)
    cell["possible"] = [value for value in cell["possible"] if value != attribute["val"]]


def _position(candidate: dict[str, Any], attribute: dict[str, str]) -> int:
    return next(
        int(house)
        for house, value in candidate["solution"][attribute["cat"]].items()
        if value == attribute["val"]
    )


def complete_state(problem: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    state = initial_state(problem)
    for category, assignments in candidate["solution"].items():
        for house, value in assignments.items():
            cell = _cell(state, category, int(house))
            cell["possible"] = [value]
            cell["placed"] = True
    return state


def _step(
    op: str,
    attribute: dict[str, str],
    house: int,
    rule: str,
    clue_id: str | None = None,
) -> dict[str, Any]:
    justify: dict[str, Any] = {"rule": rule}
    if clue_id is not None:
        justify["clue_id"] = clue_id
    return {
        "op": op,
        "cat": attribute["cat"],
        "house": house,
        "val": attribute["val"],
        "justify": justify,
    }


def _unary_attribute(clue: dict[str, Any]) -> dict[str, str]:
    return {"cat": clue["cat"], "val": clue["val"]}


def _find_problem(
    problems: list[dict[str, Any]], clue_type: str, min_houses: int = 2
) -> tuple[dict[str, Any], dict[str, Any]]:
    for problem in problems:
        if problem["size"]["houses"] < min_houses:
            continue
        for clue in problem["clues"]:
            if clue["type"] == clue_type:
                return problem, clue
    raise RuntimeError(f"no real clue available for {clue_type}")


def _derived_direct_right(
    problems: list[dict[str, Any]], references: dict[str, dict[str, Any]]
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    original, source = _find_problem(problems, "direct_left")
    problem = deepcopy(original)
    clue = next(clue for clue in problem["clues"] if clue["id"] == source["id"])
    clue["type"] = "direct_right"
    clue["a"], clue["b"] = clue["b"], clue["a"]
    return problem, clue, references[problem["id"]]


def build_cases(
    problems: list[dict[str, Any]], references: dict[str, dict[str, Any]]
) -> list[StepCase]:
    cases: list[StepCase] = []

    def add(
        case_id: str,
        problem: dict[str, Any],
        state: dict[str, Any] | None,
        step: dict[str, Any] | str | None,
        expected_kind: str,
        *,
        command: str = "apply_step",
        failure: str | None = None,
        rule: str | None = None,
        clue_type: str | None = None,
    ) -> None:
        cases.append(
            StepCase(
                case_id,
                problem,
                state,
                step,
                command,
                expected_kind,
                failure,
                rule,
                clue_type,
                failure,
            )
        )

    base = problems[0]
    base_ref = references[base["id"]]
    add("init-state-full-grid", base, None, None, "STATE_INITIALIZED", command="init_state")

    found_problem, found = _find_problem(problems, "found_at")
    found_item = _unary_attribute(found)
    add(
        "rule-given-found-at",
        found_problem,
        initial_state(found_problem),
        _step("place", found_item, found["house"], "given_found_at_place", found["id"]),
        "ACCEPT_STEP",
        rule="given_found_at_place",
        clue_type="found_at",
    )

    not_problem, not_clue = _find_problem(problems, "not_at")
    not_item = _unary_attribute(not_clue)
    add(
        "rule-given-not-at",
        not_problem,
        initial_state(not_problem),
        _step(
            "eliminate",
            not_item,
            not_clue["house"],
            "given_not_at_eliminate",
            not_clue["id"],
        ),
        "ACCEPT_STEP",
        rule="given_not_at_eliminate",
        clue_type="not_at",
    )

    category = next(iter(base["categories"]))
    values = base["categories"][category]
    attribute = {"cat": category, "val": values[0]}
    other_value = {"cat": category, "val": values[1]}
    placed_state = initial_state(base)
    _set_placed(placed_state, attribute, 1)
    add(
        "rule-bijection-same-value",
        base,
        placed_state,
        _step(
            "eliminate",
            attribute,
            2,
            "bijection_place_eliminates_same_value_other_houses",
        ),
        "ACCEPT_STEP",
        rule="bijection_place_eliminates_same_value_other_houses",
    )
    add(
        "rule-bijection-other-value",
        base,
        deepcopy(placed_state),
        _step(
            "eliminate",
            other_value,
            1,
            "bijection_place_eliminates_other_values_same_house",
        ),
        "ACCEPT_STEP",
        rule="bijection_place_eliminates_other_values_same_house",
    )
    singleton_state = initial_state(base)
    _cell(singleton_state, category, 1)["possible"] = [values[0]]
    add(
        "rule-cell-singleton",
        base,
        singleton_state,
        _step("place", attribute, 1, "bijection_cell_singleton_forces_place"),
        "ACCEPT_STEP",
        rule="bijection_cell_singleton_forces_place",
    )
    value_singleton_state = initial_state(base)
    for house in range(2, base["size"]["houses"] + 1):
        _remove(value_singleton_state, attribute, house)
    add(
        "rule-value-singleton",
        base,
        value_singleton_state,
        _step("place", attribute, 1, "bijection_value_singleton_forces_place"),
        "ACCEPT_STEP",
        rule="bijection_value_singleton_forces_place",
    )

    same_problem, same = _find_problem(problems, "same_house")
    same_ref = references[same_problem["id"]]
    same_house = _position(same_ref, same["a"])
    same_state = initial_state(same_problem)
    _set_placed(same_state, same["b"], same_house)
    add(
        "rule-same-house-place",
        same_problem,
        same_state,
        _step("place", same["a"], same_house, "same_house_place_from_placed", same["id"]),
        "ACCEPT_STEP",
        rule="same_house_place_from_placed",
        clue_type="same_house",
    )
    same_elim_state = initial_state(same_problem)
    _remove(same_elim_state, same["b"], 1)
    add(
        "rule-same-house-eliminate",
        same_problem,
        same_elim_state,
        _step(
            "eliminate",
            same["a"],
            1,
            "same_house_eliminate_no_possible_match",
            same["id"],
        ),
        "ACCEPT_STEP",
        rule="same_house_eliminate_no_possible_match",
        clue_type="same_house",
    )

    left_problem, direct_left = _find_problem(problems, "direct_left")
    left_ref = references[left_problem["id"]]
    ah = _position(left_ref, direct_left["a"])
    bh = _position(left_ref, direct_left["b"])
    direct_state = initial_state(left_problem)
    _set_placed(direct_state, direct_left["b"], bh)
    add(
        "rule-direct-left-place",
        left_problem,
        direct_state,
        _step(
            "place",
            direct_left["a"],
            ah,
            "direct_left_place_from_fixed",
            direct_left["id"],
        ),
        "ACCEPT_STEP",
        rule="direct_left_place_from_fixed",
        clue_type="direct_left",
    )
    add(
        "rule-direct-left-eliminate",
        left_problem,
        initial_state(left_problem),
        _step(
            "eliminate",
            direct_left["a"],
            left_problem["size"]["houses"],
            "direct_left_eliminate_no_possible_partner",
            direct_left["id"],
        ),
        "ACCEPT_STEP",
        rule="direct_left_eliminate_no_possible_partner",
        clue_type="direct_left",
    )

    right_problem, direct_right, right_ref = _derived_direct_right(problems, references)
    rah = _position(right_ref, direct_right["a"])
    rbh = _position(right_ref, direct_right["b"])
    right_state = initial_state(right_problem)
    _set_placed(right_state, direct_right["b"], rbh)
    add(
        "rule-direct-right-place",
        right_problem,
        right_state,
        _step(
            "place",
            direct_right["a"],
            rah,
            "direct_right_place_from_fixed",
            direct_right["id"],
        ),
        "ACCEPT_STEP",
        rule="direct_right_place_from_fixed",
        clue_type="direct_right",
    )
    add(
        "rule-direct-right-eliminate",
        right_problem,
        initial_state(right_problem),
        _step(
            "eliminate",
            direct_right["a"],
            1,
            "direct_right_eliminate_no_possible_partner",
            direct_right["id"],
        ),
        "ACCEPT_STEP",
        rule="direct_right_eliminate_no_possible_partner",
        clue_type="direct_right",
    )

    def distance_rules(
        clue_type: str,
        distance: int,
        place_rule: str,
        eliminate_rule: str,
    ) -> None:
        problem, clue = _find_problem(problems, clue_type, distance + 1)
        reference = references[problem["id"]]
        target_house = _position(reference, clue["a"])
        fixed_house = _position(reference, clue["b"])
        state = initial_state(problem)
        _set_placed(state, clue["b"], fixed_house)
        for house in range(1, problem["size"]["houses"] + 1):
            if abs(house - fixed_house) == distance and house != target_house:
                _remove(state, clue["a"], house)
        add(
            f"rule-{clue_type}-place",
            problem,
            state,
            _step("place", clue["a"], target_house, place_rule, clue["id"]),
            "ACCEPT_STEP",
            rule=place_rule,
            clue_type=clue_type,
        )
        eliminate_state = initial_state(problem)
        target = 1
        for house in range(1, problem["size"]["houses"] + 1):
            if abs(house - target) == distance:
                _remove(eliminate_state, clue["b"], house)
        add(
            f"rule-{clue_type}-eliminate",
            problem,
            eliminate_state,
            _step("eliminate", clue["a"], target, eliminate_rule, clue["id"]),
            "ACCEPT_STEP",
            rule=eliminate_rule,
            clue_type=clue_type,
        )

    distance_rules(
        "side_by_side",
        1,
        "side_by_side_place_from_single_neighbor",
        "side_by_side_eliminate_no_possible_neighbor",
    )

    left_of_problem, left_of = _find_problem(problems, "left_of")
    add(
        "rule-left-of-eliminate",
        left_of_problem,
        initial_state(left_of_problem),
        _step(
            "eliminate",
            left_of["a"],
            left_of_problem["size"]["houses"],
            "left_of_eliminate_impossible_order",
            left_of["id"],
        ),
        "ACCEPT_STEP",
        rule="left_of_eliminate_impossible_order",
        clue_type="left_of",
    )
    right_of_problem, right_of = _find_problem(problems, "right_of")
    add(
        "rule-right-of-eliminate",
        right_of_problem,
        initial_state(right_of_problem),
        _step(
            "eliminate",
            right_of["a"],
            1,
            "right_of_eliminate_impossible_order",
            right_of["id"],
        ),
        "ACCEPT_STEP",
        rule="right_of_eliminate_impossible_order",
        clue_type="right_of",
    )
    distance_rules(
        "one_between",
        2,
        "one_between_place_from_fixed",
        "one_between_eliminate_no_possible_partner",
    )
    distance_rules(
        "two_between",
        3,
        "two_between_place_from_fixed",
        "two_between_eliminate_no_possible_partner",
    )

    solved_state = complete_state(base, base_ref)
    add(
        "rule-solved-conclusion",
        base,
        solved_state,
        {"op": "conclude", "status": "solved"},
        "ACCEPT_SOLVED",
        rule="solved_conclusion",
    )
    contradiction_state = initial_state(base)
    contradiction_state["cells"][0]["possible"] = []
    add(
        "rule-contradiction-detection",
        base,
        contradiction_state,
        _step("place", attribute, 1, "bijection_cell_singleton_forces_place"),
        "REJECT",
        failure="contradicts_state",
        rule="contradiction_detection",
    )

    add(
        "reject-malformed-step",
        base,
        initial_state(base),
        "{",
        "REJECT",
        failure="malformed_step",
    )
    unknown_category = _step("place", attribute, 1, "bijection_cell_singleton_forces_place")
    unknown_category["cat"] = "__unknown_category__"
    add(
        "reject-unknown-category",
        base,
        initial_state(base),
        unknown_category,
        "REJECT",
        failure="unknown_category",
    )
    unknown_value = _step("place", attribute, 1, "bijection_cell_singleton_forces_place")
    unknown_value["val"] = "__unknown_value__"
    add(
        "reject-unknown-value",
        base,
        initial_state(base),
        unknown_value,
        "REJECT",
        failure="unknown_value",
    )
    bad_house = _step("place", attribute, base["size"]["houses"] + 1, "bijection_cell_singleton_forces_place")
    add(
        "reject-house-out-of-range",
        base,
        initial_state(base),
        bad_house,
        "REJECT",
        failure="house_out_of_range",
    )
    add(
        "reject-unknown-clue-ref",
        found_problem,
        initial_state(found_problem),
        _step("place", found_item, found["house"], "given_found_at_place", "missing"),
        "REJECT",
        failure="unknown_clue_ref",
    )
    add(
        "reject-rule-clue-mismatch",
        found_problem,
        initial_state(found_problem),
        _step(
            "eliminate",
            found_item,
            found["house"],
            "given_not_at_eliminate",
            found["id"],
        ),
        "REJECT",
        failure="rule_clue_mismatch",
    )
    duplicate_state = initial_state(found_problem)
    _set_placed(duplicate_state, found_item, found["house"])
    add(
        "reject-duplicate-place",
        found_problem,
        duplicate_state,
        _step("place", found_item, found["house"], "given_found_at_place", found["id"]),
        "REJECT",
        failure="contradicts_state",
    )
    conflict_state = initial_state(found_problem)
    found_values = found_problem["categories"][found_item["cat"]]
    conflict_value = next(value for value in found_values if value != found_item["val"])
    _set_placed(conflict_state, {"cat": found_item["cat"], "val": conflict_value}, found["house"])
    add(
        "reject-placement-conflict",
        found_problem,
        conflict_state,
        _step("place", found_item, found["house"], "given_found_at_place", found["id"]),
        "REJECT",
        failure="placement_conflict",
    )
    correct_house = _position(base_ref, attribute)
    add(
        "reject-true-unforced-guess",
        base,
        initial_state(base),
        _step("place", attribute, correct_house, "bijection_cell_singleton_forces_place"),
        "REJECT",
        failure="not_forced",
    )
    add(
        "reject-unsupported-true-guess",
        base,
        initial_state(base),
        _step("place", attribute, correct_house, "unchecked_guess"),
        "REJECT",
        failure="unsupported_rule",
    )
    add(
        "reject-invalid-conclusion",
        base,
        initial_state(base),
        {"op": "conclude", "status": "unknown"},
        "REJECT",
        failure="invalid_conclusion",
    )
    add(
        "reject-incomplete-final",
        base,
        initial_state(base),
        {"op": "conclude", "status": "solved"},
        "REJECT",
        failure="incomplete_final",
    )
    violating = deepcopy(base_ref)
    first_category = next(iter(violating["solution"]))
    assignments = violating["solution"][first_category]
    assignments["1"], assignments["2"] = assignments["2"], assignments["1"]
    add(
        "reject-clue-violation-final",
        base,
        complete_state(base, violating),
        {"op": "conclude", "status": "solved"},
        "REJECT",
        failure="clue_violation_final",
    )
    max_state = initial_state(not_problem)
    max_state["step_count"] = 10000
    add(
        "reject-max-steps",
        not_problem,
        max_state,
        _step(
            "eliminate",
            not_item,
            not_clue["house"],
            "given_not_at_eliminate",
            not_clue["id"],
        ),
        "REJECT",
        failure="max_steps_exceeded",
    )
    return cases


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def _path_label(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def run_step_gate(
    gate_a_dir: Path,
    reference_dir: Path,
    output: Path,
    seed: int,
) -> dict[str, Any]:
    problems = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted((gate_a_dir / "ingested_problems").glob("*.problem.json"))
    ]
    reference_rows = [
        json.loads(line)
        for line in (reference_dir / "reference_solutions.jsonl").read_text(encoding="utf-8").splitlines()
        if line
    ]
    references = {row["source_problem_id"]: row["candidate"] for row in reference_rows}
    cases = build_cases(problems, references)
    output.mkdir(parents=True, exist_ok=True)
    state_dir = output / "state_json"
    step_dir = output / "step_json"
    for directory in (state_dir, step_dir):
        directory.mkdir(parents=True, exist_ok=True)
        for stale in directory.glob("*.json"):
            stale.unlink()
    executable_path = ROOT / ".lake" / "build" / "bin" / "sparse-ir-lean"
    executable = executable_path if executable_path.is_file() else None
    step_rows: list[dict[str, Any]] = []
    result_rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    protocol_errors = 0
    rule_coverage = {rule: False for rule in SUPPORTED_RULES}
    rejection_coverage = {code: 0 for code in REJECTION_CODES}
    clue_coverage = {clue_type: 0 for clue_type in CLUE_TYPES}

    for case in cases:
        state_path = None
        step_path = None
        if case.state is not None:
            state_path = state_dir / f"{case.case_id}.state.json"
            state_path.write_text(json.dumps(case.state, indent=2) + "\n", encoding="utf-8")
        if case.step is not None:
            step_path = step_dir / f"{case.case_id}.step.json"
            if isinstance(case.step, str):
                step_path.write_text(case.step, encoding="utf-8")
                step_text = case.step
            else:
                step_path.write_text(json.dumps(case.step, indent=2) + "\n", encoding="utf-8")
                step_text = json.dumps(case.step)
        else:
            step_text = ""
        payload = {"problem": json.dumps(case.problem)}
        if case.command != "init_state":
            payload.update({"state": json.dumps(case.state), "step": step_text})
        request = {
            "protocol_version": "0.1.0",
            "request_id": case.case_id,
            "command": case.command,
            "payload": payload,
        }
        try:
            result = _invoke_lean(request, executable)["result"]
        except Exception as exc:
            protocol_errors += 1
            result = {"kind": "PROTOCOL_ERROR", "message": str(exc)}
        actual_code = result.get("failure", {}).get("failure_code")
        matched = result.get("kind") == case.expected_kind and (
            case.expected_failure_code is None or actual_code == case.expected_failure_code
        )
        if case.command == "init_state" and matched:
            matched = len(result["state"]["cells"]) == (
                case.problem["size"]["houses"] * case.problem["size"]["categories"]
            )
        if matched and case.supported_rule:
            rule_coverage[case.supported_rule] = True
        if matched and case.rejection_code:
            rejection_coverage[case.rejection_code] += 1
        if matched and case.clue_type:
            clue_coverage[case.clue_type] += 1
        row = {
            "case_id": case.case_id,
            "problem_id": case.problem["id"],
            "grid": case.problem["source"]["grid"],
            "command": case.command,
            "state_path": _path_label(state_path) if state_path else None,
            "step_path": _path_label(step_path) if step_path else None,
            "supported_rule": case.supported_rule,
            "clue_type": case.clue_type,
            "expected_kind": case.expected_kind,
            "expected_failure_code": case.expected_failure_code,
        }
        step_rows.append(row)
        result_rows.append({**row, "matched_expected": matched, "result": result})
        if not matched:
            failures.append(
                {
                    "case_id": case.case_id,
                    "expected_kind": case.expected_kind,
                    "expected_failure_code": case.expected_failure_code,
                    "actual": result,
                }
            )

    pass_conditions = (
        not failures
        and protocol_errors == 0
        and all(rule_coverage.values())
        and all(rejection_coverage.values())
        and all(clue_coverage.values())
    )
    status = "pass" if pass_conditions else "fail"
    _write_jsonl(output / "steps.jsonl", step_rows)
    _write_jsonl(output / "results.jsonl", result_rows)
    _write_jsonl(output / "failures.jsonl", failures)
    manifest = {
        "gate": "stage3c_step_kernel",
        "status": status,
        "seed": seed,
        "total_cases": len(cases),
        "total_protocol_error": protocol_errors,
        "supported_rule_coverage": rule_coverage,
        "deferred_rules": [],
        "rejection_code_coverage": rejection_coverage,
        "deferred_rejection_codes": [],
        "clue_type_coverage": clue_coverage,
        "failures": failures,
        "lean_solver_search": False,
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    examples = ["# Stage 3C step-kernel examples", ""]
    for row in result_rows[:6]:
        examples.extend(["```json", json.dumps(row, indent=2), "```", ""])
    (output / "examples.md").write_text("\n".join(examples), encoding="utf-8")
    summary = f"""# Stage 3C stepwise kernel gate

Status: **{status.upper()}**

- Cases: {len(cases)}
- Supported rules covered: {sum(rule_coverage.values())}/{len(rule_coverage)}
- Rejection codes covered: {sum(bool(value) for value in rejection_coverage.values())}/{len(rejection_coverage)}
- Clue types covered: {sum(bool(value) for value in clue_coverage.values())}/{len(clue_coverage)}
- Protocol errors: {protocol_errors}
- Failures: {len(failures)}

Every accepted operation is a deterministic local consequence of its cited rule
and current candidate state. Unsupported guesses fail closed. No search, trace
parser, trace replay, provider call, or scored evaluation harness is included.
"""
    (output / "summary.md").write_text(summary, encoding="utf-8")
    return manifest
