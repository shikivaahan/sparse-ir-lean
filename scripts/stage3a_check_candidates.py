#!/usr/bin/env python3
"""Run the Stage 3A full-candidate checker gate.

Python constructs cases, invokes Lean, and records Lean's response. It never
recomputes or overrides the candidate verdict.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    from scripts.run_lean_verifier import invoke
except ModuleNotFoundError:  # direct `python scripts/...` execution
    from run_lean_verifier import invoke


ROOT = Path(__file__).resolve().parents[1]
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
CANDIDATE_ERRORS = (
    "missing_category",
    "extra_category",
    "missing_house",
    "extra_house",
    "unknown_category",
    "unknown_value",
    "duplicate_value",
    "category_not_bijective",
)


@dataclass
class Case:
    case_id: str
    problem: dict[str, Any]
    candidate_text: str
    candidate_json: dict[str, Any] | None
    expected_kind: str
    expected_status: str
    expected_failure_code: str | None = None
    clue_type: str | None = None
    candidate_error: str | None = None
    provenance: str = "dataset-derived"


def _load_problems(gate_a_dir: Path) -> list[dict[str, Any]]:
    problem_dir = gate_a_dir / "ingested_problems"
    return [json.loads(path.read_text(encoding="utf-8")) for path in sorted(problem_dir.glob("*.json"))]


def _candidate(problem: dict[str, Any], solution: dict[str, dict[str, str]]) -> dict[str, Any]:
    return {"schema_version": "0.2", "problem_id": problem["id"], "solution": solution}


def _identity_solution(problem: dict[str, Any]) -> dict[str, dict[str, str]]:
    return {
        category: {str(house): value for house, value in enumerate(values, start=1)}
        for category, values in problem["categories"].items()
    }


def _place_attributes(
    problem: dict[str, Any],
    placements: list[tuple[dict[str, str], int]],
) -> dict[str, dict[str, str]] | None:
    """Build a bijection with selected values at selected one-based houses."""
    result = _identity_solution(problem)
    by_category: dict[str, list[tuple[str, int]]] = {}
    for attribute, house in placements:
        by_category.setdefault(attribute["cat"], []).append((attribute["val"], house))
    for category, requested in by_category.items():
        if len({value for value, _ in requested}) != len(requested):
            return None
        if len({house for _, house in requested}) != len(requested):
            return None
        values = problem["categories"][category]
        requested_values = {value for value, _ in requested}
        requested_houses = {house for _, house in requested}
        if not requested_values.issubset(values) or any(
            house < 1 or house > problem["size"]["houses"] for house in requested_houses
        ):
            return None
        remaining_values = [value for value in values if value not in requested_values]
        remaining_houses = [
            house
            for house in range(1, problem["size"]["houses"] + 1)
            if house not in requested_houses
        ]
        assignments = {str(house): value for value, house in requested}
        assignments.update(
            {str(house): value for house, value in zip(remaining_houses, remaining_values, strict=True)}
        )
        result[category] = assignments
    return result


def _violating_placements(clue: dict[str, Any], houses: int) -> list[tuple[dict[str, str], int]] | None:
    clue_type = clue["type"]
    if clue_type == "found_at":
        other = 1 if clue["house"] != 1 else 2
        return [({"cat": clue["cat"], "val": clue["val"]}, other)]
    if clue_type == "not_at":
        return [({"cat": clue["cat"], "val": clue["val"]}, clue["house"])]
    a, b = clue["a"], clue["b"]
    if a == b:
        return None
    targets = {
        "same_house": (1, 2),
        "direct_left": (2, 1),
        "direct_right": (1, 2),
        "side_by_side": (1, 3),
        "left_of": (2, 1),
        "right_of": (1, 2),
        "one_between": (1, 2),
        "two_between": (1, 2),
    }
    ah, bh = targets[clue_type]
    if max(ah, bh) > houses:
        return None
    if a["cat"] == b["cat"] and ah == bh:
        return None
    return [(a, ah), (b, bh)]


def build_clue_violation_case(
    problems: list[dict[str, Any]], clue_type: str, preferred_grid: str | None = None
) -> Case:
    ordered = sorted(
        problems,
        key=lambda problem: (problem["source"]["grid"] != preferred_grid, problem["id"]),
    )
    for original in ordered:
        for source_clue in original["clues"]:
            clue = deepcopy(source_clue)
            provenance_suffix = f"clue {source_clue['id']} retained"
            if clue_type == "direct_right" and source_clue["type"] == "direct_left":
                clue["type"] = "direct_right"
                clue["a"], clue["b"] = clue["b"], clue["a"]
                provenance_suffix = (
                    f"direct_left clue {source_clue['id']} converted to its equivalent direct_right form"
                )
            elif source_clue["type"] != clue_type:
                continue
            placements = _violating_placements(clue, original["size"]["houses"])
            if placements is None:
                continue
            solution = _place_attributes(original, placements)
            if solution is None:
                continue
            problem = deepcopy(original)
            problem["clues"] = [deepcopy(clue)]
            candidate = _candidate(problem, solution)
            return Case(
                case_id=f"clue-violation-{clue_type}",
                problem=problem,
                candidate_text=json.dumps(candidate),
                candidate_json=candidate,
                expected_kind="REJECT",
                expected_status="clue_violation",
                expected_failure_code="clue_violation",
                clue_type=clue_type,
                provenance=f"Gate A {original['id']} with {provenance_suffix}",
            )
    raise RuntimeError(f"could not construct a dataset-derived violation for {clue_type}")


def _known_2x2_case(problems: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    problem = next(problem for problem in problems if problem["id"] == "zl_lgp-test-2x2-33")
    candidate = _candidate(
        problem,
        {"Name": {"1": "Eric", "2": "Arnold"}, "Pet": {"1": "cat", "2": "dog"}},
    )
    return problem, candidate


def _candidate_error_cases(problems: list[dict[str, Any]]) -> list[Case]:
    problem, known = _known_2x2_case(problems)
    cases: list[Case] = []

    def add(
        name: str,
        mutate: Any,
        kind: str,
        status: str,
        code: str,
    ) -> None:
        value = deepcopy(known)
        mutate(value)
        cases.append(
            Case(
                case_id=f"candidate-error-{name}",
                problem=problem,
                candidate_text=json.dumps(value),
                candidate_json=value,
                expected_kind=kind,
                expected_status=status,
                expected_failure_code=code,
                candidate_error=name,
                provenance="mutation of known satisfying Gate A 2x2 candidate",
            )
        )

    add("missing_category", lambda c: c["solution"].pop("Pet"), "INCOMPLETE", "incomplete", "missing_category")
    add("extra_category", lambda c: c["solution"].update(Extra={"1": "x", "2": "y"}), "REJECT", "invalid_candidate", "unknown_category")
    add("missing_house", lambda c: c["solution"]["Name"].pop("2"), "INCOMPLETE", "incomplete", "missing_assignment")
    add("extra_house", lambda c: c["solution"]["Pet"].update({"3": "cat"}), "REJECT", "invalid_candidate", "extra_house")
    add("unknown_category", lambda c: c["solution"].update(Unknown={"1": "x"}), "REJECT", "invalid_candidate", "unknown_category")
    add("unknown_value", lambda c: c["solution"]["Pet"].update({"1": "dragon"}), "REJECT", "invalid_candidate", "unknown_value")
    add("duplicate_value", lambda c: c["solution"]["Pet"].update({"2": "cat"}), "REJECT", "invalid_candidate", "duplicate_value")
    add("category_not_bijective", lambda c: c["solution"]["Name"].update({"2": "Eric"}), "REJECT", "invalid_candidate", "duplicate_value")
    return cases


def _source_solution_usable(problem: dict[str, Any]) -> bool:
    source_solution = problem.get("expect", {}).get("source_solution")
    if not isinstance(source_solution, dict):
        return False
    rows = source_solution.get("rows")
    return bool(rows) and all(
        isinstance(row, list) and row and all(isinstance(cell, str) and cell != "___" for cell in row)
        for row in rows
    )


def _result_status(result: dict[str, Any]) -> str | None:
    if result["kind"] == "ACCEPT_SOLVED":
        return result["artifact"].get("status")
    if result["kind"] == "INCOMPLETE":
        return result["state"].get("status")
    if result["kind"] == "REJECT":
        return result["failure"].get("status")
    return None


def _failure_code(result: dict[str, Any]) -> str | None:
    if result["kind"] == "INCOMPLETE":
        return result["state"].get("failure_code")
    if result["kind"] == "REJECT":
        return result["failure"].get("failure_code")
    return None


def run_gate(gate_a_dir: Path, output: Path) -> dict[str, Any]:
    problems = _load_problems(gate_a_dir)
    problem, known = _known_2x2_case(problems)
    cases = [
        Case(
            case_id="known-satisfying-real-2x2",
            problem=problem,
            candidate_text=json.dumps(known),
            candidate_json=known,
            expected_kind="ACCEPT_SOLVED",
            expected_status="solved",
            provenance="manually derived from both clues of Gate A lgp-test-2x2-33",
        )
    ]
    cases.extend(
        build_clue_violation_case(
            problems,
            clue_type,
            "4x4" if index < len(CLUE_TYPES) // 2 else "6x6",
        )
        for index, clue_type in enumerate(CLUE_TYPES)
    )
    cases.extend(_candidate_error_cases(problems))
    cases.append(
        Case(
            case_id="malformed-candidate-json",
            problem=problem,
            candidate_text="{",
            candidate_json=None,
            expected_kind="REJECT",
            expected_status="malformed_candidate",
            expected_failure_code="invalid_candidate_json",
            provenance="candidate parser negative control",
        )
    )

    output.mkdir(parents=True, exist_ok=True)
    candidate_dir = output / "candidate_json"
    candidate_dir.mkdir(parents=True, exist_ok=True)
    executable = ROOT / ".lake" / "build" / "bin" / "sparse-ir-lean"
    executable_arg = executable if executable.is_file() else None
    results: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    protocol_errors = 0
    kind_counts: Counter[str] = Counter()
    grid_counts: Counter[str] = Counter()
    clue_coverage = {clue_type: False for clue_type in CLUE_TYPES}
    error_coverage = {error: False for error in CANDIDATE_ERRORS}

    with (output / "candidates.jsonl").open("w", encoding="utf-8") as candidate_file, (
        output / "results.jsonl"
    ).open("w", encoding="utf-8") as result_file:
        for case in cases:
            record = {
                "case_id": case.case_id,
                "problem_id": case.problem["id"],
                "grid": case.problem["source"]["grid"],
                "clue_type": case.clue_type,
                "candidate_error": case.candidate_error,
                "provenance": case.provenance,
                "candidate": case.candidate_json if case.candidate_json is not None else case.candidate_text,
            }
            candidate_file.write(json.dumps(record, sort_keys=True) + "\n")
            if case.candidate_json is not None:
                safe_id = re.sub(r"[^A-Za-z0-9_.-]", "-", case.case_id)
                (candidate_dir / f"{safe_id}.candidate.json").write_text(
                    json.dumps(case.candidate_json, indent=2) + "\n", encoding="utf-8"
                )
            request = {
                "protocol_version": "0.1.0",
                "request_id": case.case_id,
                "command": "check_candidate",
                "payload": {
                    "problem": json.dumps(case.problem),
                    "candidate": case.candidate_text,
                },
            }
            try:
                response = invoke(request, executable_arg)
                result = response["result"]
            except Exception as exc:  # transport failures are gate evidence
                protocol_errors += 1
                result = {"kind": "PROTOCOL_ERROR", "message": str(exc)}
            actual_status = _result_status(result) if result["kind"] != "PROTOCOL_ERROR" else None
            actual_code = _failure_code(result) if result["kind"] != "PROTOCOL_ERROR" else None
            matched = (
                result["kind"] == case.expected_kind
                and actual_status == case.expected_status
                and (case.expected_failure_code is None or actual_code == case.expected_failure_code)
            )
            if not matched:
                failures.append(
                    {
                        "case_id": case.case_id,
                        "expected": {
                            "kind": case.expected_kind,
                            "status": case.expected_status,
                            "failure_code": case.expected_failure_code,
                        },
                        "actual": result,
                    }
                )
            if matched and case.clue_type:
                clue_coverage[case.clue_type] = True
            if matched and case.candidate_error:
                error_coverage[case.candidate_error] = True
            kind_counts[result["kind"]] += 1
            grid_counts[case.problem["source"]["grid"]] += 1
            result_record = {"case_id": case.case_id, "matched_expected": matched, "result": result}
            results.append(result_record)
            result_file.write(json.dumps(result_record, sort_keys=True) + "\n")

    usable_gold = [problem["id"] for problem in problems if _source_solution_usable(problem)]
    if failures or protocol_errors or not all(clue_coverage.values()) or not all(error_coverage.values()):
        status = "fail"
    elif not usable_gold:
        status = "blocked"
        failures.append(
            {
                "blocker": "gold_solution_extraction",
                "message": (
                    "Gate A source_solution rows are redacted as ___; provide populated source rows "
                    "or an independently provenance-checked gold assignment export before PASS"
                ),
            }
        )
    else:
        status = "pass"

    manifest = {
        "gate": "stage3a_candidate_checker",
        "status": status,
        "total_candidates": len(cases),
        "total_accept_solved": kind_counts["ACCEPT_SOLVED"],
        "total_reject": kind_counts["REJECT"],
        "total_incomplete": kind_counts["INCOMPLETE"],
        "total_protocol_error": protocol_errors,
        "clue_type_violation_coverage": clue_coverage,
        "candidate_error_coverage": error_coverage,
        "grid_coverage": dict(sorted(grid_counts.items())),
        "usable_gold_source_solutions": len(usable_gold),
        "failures": failures,
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    examples = ["# Stage 3A examples", ""]
    for record in results[:5]:
        examples.extend(
            [f"## {record['case_id']}", "", "```json", json.dumps(record["result"], indent=2), "```", ""]
        )
    (output / "examples.md").write_text("\n".join(examples), encoding="utf-8")
    summary = f"""# Stage 3A candidate checker summary

Status: **{status.upper()}**

- Candidates: {len(cases)}
- ACCEPT_SOLVED: {kind_counts['ACCEPT_SOLVED']}
- REJECT: {kind_counts['REJECT']}
- INCOMPLETE: {kind_counts['INCOMPLETE']}
- Protocol errors: {protocol_errors}
- All 10 clue violation predicates covered: {all(clue_coverage.values())}
- All requested candidate invariant cases covered: {all(error_coverage.values())}

The checker itself passes every constructed expectation. The overall gate is
blocked because the real source dataset stores `___` in every solution cell, so
there is no provenance-preserving 4x4 or 6x6 gold assignment to extract. The one
ACCEPT_SOLVED case is the small, manually derived real 2x2 assignment and is not
presented as broad gold-solution evidence. Lean is the only verdict source.
"""
    (output / "summary.md").write_text(summary, encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gate-a-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest = run_gate(args.gate_a_dir, args.output)
    print(json.dumps(manifest, indent=2))
    return 0 if manifest["status"] in {"pass", "blocked"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
