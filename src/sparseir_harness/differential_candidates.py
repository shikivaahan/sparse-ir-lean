"""Stage 3B full-candidate differential testing against reference-only clingo."""

from __future__ import annotations

import json
import os
import random
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

try:
    import clingo as _clingo
except ImportError:
    _clingo = None

from .reference_solutions import ROOT, _invoke_lean, build_asp_program


MUTATION_FAMILIES = (
    "swap_two_house_values",
    "rotate_category_assignment",
    "targeted_clue_violation",
    "random_complete_assignment",
    "near_solution_1_swap",
    "near_solution_2_swaps",
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
class DifferentialSample:
    sample_id: str
    problem_id: str
    external_id: str
    grid: str
    candidate: dict[str, Any]
    sample_kind: str
    mutation_kind: str
    target_clue_id: str | None = None
    target_clue_type: str | None = None
    target_clue_source_type: str | None = None


@dataclass
class ClingoCandidateCheck:
    status: str
    satisfied: bool | None
    elapsed_seconds: float
    message: str | None = None


def _problem_indexes(problem: dict[str, Any]) -> tuple[list[str], list[list[str]], dict[tuple[str, str], tuple[int, int]]]:
    categories = list(problem["categories"])
    values = [problem["categories"][category] for category in categories]
    attributes = {
        (category, value): (category_index, value_index)
        for category_index, category in enumerate(categories)
        for value_index, value in enumerate(values[category_index])
    }
    return categories, values, attributes


def check_candidate_with_clingo(
    problem: dict[str, Any],
    candidate: dict[str, Any],
    timeout_seconds: float,
    clingo_module: Any = _clingo,
) -> ClingoCandidateCheck:
    if clingo_module is None:
        return ClingoCandidateCheck("error", None, 0.0, "clingo is not installed")
    started = time.monotonic()
    try:
        categories, _, attributes = _problem_indexes(problem)
        constraints = []
        for category in categories:
            for house_key, value in candidate["solution"][category].items():
                category_index, value_index = attributes[(category, value)]
                constraints.append(f":- not at({category_index},{value_index},{int(house_key)}).")
        program = build_asp_program(problem) + "\n".join(constraints) + "\n"
        control = clingo_module.Control(["--models=1", "--warn=none"])
        control.add("base", [], program)
        control.ground([("base", [])])
        with control.solve(async_=True) as handle:
            if not handle.wait(timeout_seconds):
                handle.cancel()
                handle.wait()
                return ClingoCandidateCheck(
                    "timeout", None, time.monotonic() - started, "candidate check timed out"
                )
            result = handle.get()
        elapsed = time.monotonic() - started
        if result.satisfiable:
            return ClingoCandidateCheck("satisfied", True, elapsed)
        if result.unsatisfiable:
            return ClingoCandidateCheck("violated", False, elapsed)
        return ClingoCandidateCheck("error", None, elapsed, "clingo returned indeterminate")
    except Exception as exc:
        return ClingoCandidateCheck("error", None, time.monotonic() - started, str(exc))


def is_complete_bijective(problem: dict[str, Any], candidate: dict[str, Any]) -> bool:
    solution = candidate.get("solution")
    if not isinstance(solution, dict) or set(solution) != set(problem["categories"]):
        return False
    expected_houses = {str(house) for house in range(1, problem["size"]["houses"] + 1)}
    for category, declared_values in problem["categories"].items():
        assignments = solution.get(category)
        if not isinstance(assignments, dict) or set(assignments) != expected_houses:
            return False
        if sorted(assignments.values()) != sorted(declared_values):
            return False
    return True


def _swap(candidate: dict[str, Any], category: str, a: int, b: int) -> None:
    assignments = candidate["solution"][category]
    assignments[str(a)], assignments[str(b)] = assignments[str(b)], assignments[str(a)]


def random_complete_candidate(
    problem: dict[str, Any], reference: dict[str, Any], rng: random.Random
) -> dict[str, Any]:
    candidate = deepcopy(reference)
    changed = False
    for category, assignments in candidate["solution"].items():
        houses = sorted(assignments, key=int)
        before = [assignments[house] for house in houses]
        after = before[:]
        rng.shuffle(after)
        if after != before:
            changed = True
        candidate["solution"][category] = dict(zip(houses, after, strict=True))
    if not changed:
        category = rng.choice(list(problem["categories"]))
        _swap(candidate, category, 1, 2)
    return candidate


def _place_attributes(
    reference: dict[str, Any], placements: list[tuple[dict[str, str], int]]
) -> dict[str, Any] | None:
    candidate = deepcopy(reference)
    by_category: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for attribute, house in placements:
        by_category[attribute["cat"]].append((attribute["val"], house))
    for category, requested in by_category.items():
        if len({value for value, _ in requested}) != len(requested):
            return None
        if len({house for _, house in requested}) != len(requested):
            return None
        original = reference["solution"][category]
        requested_values = {value for value, _ in requested}
        requested_houses = {house for _, house in requested}
        remaining_values = [
            original[house]
            for house in sorted(original, key=int)
            if original[house] not in requested_values
        ]
        remaining_houses = [
            int(house) for house in sorted(original, key=int) if int(house) not in requested_houses
        ]
        assignments = {str(house): value for value, house in requested}
        assignments.update(
            {
                str(house): value
                for house, value in zip(remaining_houses, remaining_values, strict=True)
            }
        )
        candidate["solution"][category] = dict(
            sorted(assignments.items(), key=lambda item: int(item[0]))
        )
    return candidate


def _target_clue(
    problem: dict[str, Any], reference: dict[str, Any], requested_type: str | None, rng: random.Random
) -> tuple[dict[str, Any], str, str, str] | None:
    candidates: list[tuple[dict[str, Any], str, str]] = []
    for clue in problem["clues"]:
        if requested_type is None or clue["type"] == requested_type:
            candidates.append((clue, clue["type"], clue["type"]))
        if requested_type == "direct_right" and clue["type"] == "direct_left":
            inverse = deepcopy(clue)
            inverse["a"], inverse["b"] = inverse["b"], inverse["a"]
            inverse["type"] = "direct_right"
            candidates.append((inverse, "direct_right", "direct_left"))
    if not candidates:
        if requested_type is not None:
            return None
        clue = rng.choice(problem["clues"])
        candidates = [(clue, clue["type"], clue["type"])]
    rng.shuffle(candidates)
    houses = problem["size"]["houses"]
    for clue, target_type, source_type in candidates:
        if target_type == "found_at":
            other = 1 if clue["house"] != 1 else 2
            placements = [({"cat": clue["cat"], "val": clue["val"]}, other)]
        elif target_type == "not_at":
            placements = [({"cat": clue["cat"], "val": clue["val"]}, clue["house"])]
        else:
            targets = {
                "same_house": (1, 2),
                "direct_left": (2, 1),
                "direct_right": (1, 2),
                "left_of": (2, 1),
                "right_of": (1, 2),
                "one_between": (1, 2),
                "two_between": (1, 2),
            }
            if target_type == "side_by_side":
                if houses >= 3:
                    ah, bh = 1, 3
                elif clue["a"]["cat"] != clue["b"]["cat"]:
                    ah, bh = 1, 1
                else:
                    continue
            else:
                ah, bh = targets[target_type]
            if max(ah, bh) > houses:
                continue
            placements = [(clue["a"], ah), (clue["b"], bh)]
        candidate = _place_attributes(reference, placements)
        if candidate is not None and candidate != reference:
            return candidate, clue["id"], target_type, source_type
    return None


def _forced_target_assignments(problems: list[dict[str, Any]]) -> dict[str, list[str]]:
    assignments: dict[str, list[str]] = defaultdict(list)
    for target_type in CLUE_TYPES:
        for problem in problems:
            source_type = "direct_left" if target_type == "direct_right" else target_type
            if len(assignments[problem["id"]]) < 2 and any(
                clue["type"] == source_type for clue in problem["clues"]
            ):
                assignments[problem["id"]].append(target_type)
                break
    return assignments


def generate_samples(
    problems: list[dict[str, Any]],
    references: dict[str, dict[str, Any]],
    seed: int,
    target_candidates: int,
) -> list[DifferentialSample]:
    if target_candidates < len(problems):
        raise ValueError("target candidates cannot omit reference solutions")
    rng = random.Random(seed)
    forced_targets = _forced_target_assignments(problems)
    samples: list[DifferentialSample] = []

    def append(
        problem: dict[str, Any],
        candidate: dict[str, Any],
        sample_kind: str,
        mutation_kind: str,
        target: tuple[str, str, str] | None = None,
    ) -> None:
        sample_id = f"sample-{len(samples):05d}"
        samples.append(
            DifferentialSample(
                sample_id=sample_id,
                problem_id=problem["id"],
                external_id=problem["source"]["external_id"],
                grid=problem["source"]["grid"],
                candidate=candidate,
                sample_kind=sample_kind,
                mutation_kind=mutation_kind,
                target_clue_id=target[0] if target else None,
                target_clue_type=target[1] if target else None,
                target_clue_source_type=target[2] if target else None,
            )
        )

    for problem in problems:
        append(problem, deepcopy(references[problem["id"]]), "reference_solution", "reference_solution")

    schedule = (
        "swap_two_house_values",
        "rotate_category_assignment",
        "targeted_clue_violation",
        "random_complete_assignment",
        "near_solution_1_swap",
        "near_solution_2_swaps",
        "swap_two_house_values",
        "random_complete_assignment",
        "targeted_clue_violation",
    )
    forced_offsets: Counter[str] = Counter()
    while len(samples) < target_candidates:
        mutation_index = len(samples) - len(problems)
        problem = problems[mutation_index % len(problems)]
        reference = references[problem["id"]]
        family = schedule[(mutation_index // len(problems)) % len(schedule)]
        candidate = deepcopy(reference)
        target: tuple[str, str, str] | None = None
        categories = list(problem["categories"])
        houses = problem["size"]["houses"]
        if family == "swap_two_house_values":
            category = rng.choice(categories)
            a, b = rng.sample(range(1, houses + 1), 2)
            _swap(candidate, category, a, b)
        elif family == "rotate_category_assignment":
            category = rng.choice(categories)
            assignments = candidate["solution"][category]
            keys = sorted(assignments, key=int)
            values = [assignments[key] for key in keys]
            offset = rng.randrange(1, houses)
            rotated = values[offset:] + values[:offset]
            candidate["solution"][category] = dict(zip(keys, rotated, strict=True))
        elif family == "targeted_clue_violation":
            forced = forced_targets.get(problem["id"], [])
            offset = forced_offsets[problem["id"]]
            requested = forced[offset] if offset < len(forced) else None
            targeted = _target_clue(problem, reference, requested, rng)
            if targeted is None:
                targeted = _target_clue(problem, reference, None, rng)
            if targeted is None:
                raise RuntimeError(f"could not target a clue for {problem['id']}")
            candidate, clue_id, clue_type, source_type = targeted
            target = (clue_id, clue_type, source_type)
            if requested is not None:
                forced_offsets[problem["id"]] += 1
        elif family == "random_complete_assignment":
            candidate = random_complete_candidate(problem, reference, rng)
        elif family == "near_solution_1_swap":
            category = rng.choice(categories)
            a, b = rng.sample(range(1, houses + 1), 2)
            _swap(candidate, category, a, b)
        elif family == "near_solution_2_swaps":
            first, second = rng.sample(categories, 2)
            for category in (first, second):
                a, b = rng.sample(range(1, houses + 1), 2)
                _swap(candidate, category, a, b)
        if candidate == reference or not is_complete_bijective(problem, candidate):
            raise RuntimeError(f"mutation {family} did not produce a distinct complete bijection")
        append(problem, candidate, "mutated", family, target)
    return samples


def _lean_fields(result: dict[str, Any]) -> tuple[str | None, str | None, str | None]:
    kind = result.get("kind")
    if kind == "ACCEPT_SOLVED":
        return result.get("artifact", {}).get("status"), None, None
    if kind == "REJECT":
        failure = result.get("failure", {})
        return failure.get("status"), failure.get("failure_code"), failure.get("clue_id")
    if kind == "INCOMPLETE":
        state = result.get("state", {})
        return state.get("status"), state.get("failure_code"), None
    return None, None, None


def semantic_agreement(lean_result: dict[str, Any], clingo: ClingoCandidateCheck) -> bool:
    lean_status, _, _ = _lean_fields(lean_result)
    return (lean_result.get("kind") == "ACCEPT_SOLVED" and clingo.satisfied is True) or (
        lean_result.get("kind") == "REJECT"
        and lean_status == "clue_violation"
        and clingo.satisfied is False
    )


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def _path_label(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def _validation_checks(
    problem: dict[str, Any],
    reference: dict[str, Any],
    lean_invoke: Callable[[dict[str, Any], Path | None], dict[str, Any]],
    executable: Path | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    cases: list[tuple[str, dict[str, Any] | str, str]] = []
    missing_category = deepcopy(reference)
    missing_category["solution"].pop(next(iter(problem["categories"])))
    cases.append(("missing_category", missing_category, "INCOMPLETE"))
    missing_house = deepcopy(reference)
    category = next(iter(problem["categories"]))
    missing_house["solution"][category].pop("1")
    cases.append(("missing_house", missing_house, "INCOMPLETE"))
    unknown_value = deepcopy(reference)
    unknown_value["solution"][category]["1"] = "__stage3b_unknown__"
    cases.append(("unknown_value", unknown_value, "REJECT"))
    duplicate_value = deepcopy(reference)
    duplicate_value["solution"][category]["2"] = duplicate_value["solution"][category]["1"]
    cases.append(("duplicate_value", duplicate_value, "REJECT"))
    cases.append(("malformed_json", "{", "REJECT"))
    rows, failures = [], []
    for index, (kind, candidate, expected_kind) in enumerate(cases):
        text = candidate if isinstance(candidate, str) else json.dumps(candidate)
        request = {
            "protocol_version": "0.1.0",
            "request_id": f"validation-{index}",
            "command": "check_candidate",
            "payload": {"problem": json.dumps(problem), "candidate": text},
        }
        try:
            result = lean_invoke(request, executable)["result"]
        except Exception as exc:
            result = {"kind": "PROTOCOL_ERROR", "message": str(exc)}
        matched = result.get("kind") == expected_kind
        row = {
            "validation_id": f"validation-{index}",
            "validation_kind": kind,
            "expected_lean_kind": expected_kind,
            "matched_expected": matched,
            "lean_result": result,
        }
        rows.append(row)
        if not matched:
            failures.append({"failure_type": "candidate_validation", **row})
    return rows, failures


def run_differential_gate(
    gate_a_dir: Path,
    reference_dir: Path,
    output: Path,
    seed: int,
    target_candidates: int,
    timeout_seconds: float,
    *,
    clingo_module: Any = _clingo,
    clingo_checker: Callable[[dict[str, Any], dict[str, Any], float, Any], ClingoCandidateCheck] = check_candidate_with_clingo,
    lean_invoke: Callable[[dict[str, Any], Path | None], dict[str, Any]] = _invoke_lean,
    workers: int | None = None,
) -> dict[str, Any]:
    problem_paths = sorted((gate_a_dir / "ingested_problems").glob("*.problem.json"))
    problems = [json.loads(path.read_text(encoding="utf-8")) for path in problem_paths]
    problem_by_id = {problem["id"]: problem for problem in problems}
    references_list = [
        json.loads(line)
        for line in (reference_dir / "reference_solutions.jsonl").read_text(encoding="utf-8").splitlines()
        if line
    ]
    references = {row["source_problem_id"]: row["candidate"] for row in references_list}
    missing = sorted(set(problem_by_id) - set(references))
    failures: list[dict[str, Any]] = []
    if missing:
        failures.append({"failure_type": "missing_reference_solutions", "problem_ids": missing})
    if clingo_module is None:
        failures.append({"failure_type": "missing_clingo", "message": "clingo is not installed"})

    output.mkdir(parents=True, exist_ok=True)
    candidate_dir = output / "candidate_json"
    clingo_dir = output / "clingo_checks"
    for directory in (candidate_dir, clingo_dir):
        directory.mkdir(parents=True, exist_ok=True)
        for stale in directory.glob("*.json"):
            stale.unlink()

    samples = generate_samples(problems, references, seed, target_candidates) if not failures else []
    executable_path = ROOT / ".lake" / "build" / "bin" / "sparse-ir-lean"
    executable = executable_path if executable_path.is_file() else None
    sample_rows: list[dict[str, Any]] = []
    for sample in samples:
        candidate_path = candidate_dir / f"{sample.sample_id}.candidate.json"
        candidate_path.write_text(json.dumps(sample.candidate, indent=2) + "\n", encoding="utf-8")
        sample_rows.append(
            {
                "sample_id": sample.sample_id,
                "problem_id": sample.problem_id,
                "external_id": sample.external_id,
                "grid": sample.grid,
                "candidate_path": _path_label(candidate_path),
                "sample_kind": sample.sample_kind,
                "mutation_kind": sample.mutation_kind,
                "target_clue_id": sample.target_clue_id,
                "target_clue_type": sample.target_clue_type,
                "target_clue_source_type": sample.target_clue_source_type,
            }
        )

    def evaluate(pair: tuple[DifferentialSample, dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any] | None]:
        sample, row = pair
        problem = problem_by_id[sample.problem_id]
        request = {
            "protocol_version": "0.1.0",
            "request_id": sample.sample_id,
            "command": "check_candidate",
            "payload": {"problem": json.dumps(problem), "candidate": json.dumps(sample.candidate)},
        }
        try:
            lean_result = lean_invoke(request, executable)["result"]
            protocol_error = False
        except Exception as exc:
            lean_result = {"kind": "PROTOCOL_ERROR", "message": str(exc)}
            protocol_error = True
        clingo_result = clingo_checker(problem, sample.candidate, timeout_seconds, clingo_module)
        lean_status, failure_code, lean_clue_id = _lean_fields(lean_result)
        agreement = semantic_agreement(lean_result, clingo_result)
        result_row = {
            **row,
            "lean_kind": lean_result.get("kind"),
            "lean_status": lean_status,
            "lean_failure_code": failure_code,
            "lean_clue_id": lean_clue_id,
            "clingo_status": clingo_result.status,
            "clingo_satisfied": clingo_result.satisfied,
            "agreement": agreement,
            "protocol_error": protocol_error,
        }
        check_row = {
            "sample_id": sample.sample_id,
            "status": clingo_result.status,
            "satisfied": clingo_result.satisfied,
            "elapsed_seconds": round(clingo_result.elapsed_seconds, 6),
            "message": clingo_result.message,
        }
        disagreement = None
        if not agreement and not protocol_error and clingo_result.satisfied is not None:
            disagreement = {
                "sample_id": sample.sample_id,
                "problem_id": sample.problem_id,
                "grid": sample.grid,
                "candidate_path": row["candidate_path"],
                "lean_result": lean_result,
                "clingo_result": check_row,
                "target_clue_id": sample.target_clue_id,
                "target_clue_type": sample.target_clue_type,
                "message": "Lean and clingo disagree on this complete bijective assignment",
            }
        return result_row, check_row, disagreement

    workers = workers or min(8, os.cpu_count() or 1)
    results: list[dict[str, Any]] = []
    disagreements: list[dict[str, Any]] = []
    if samples:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            for index, (result, check, disagreement) in enumerate(
                executor.map(evaluate, zip(samples, sample_rows, strict=True)), start=1
            ):
                results.append(result)
                (clingo_dir / f"{result['sample_id']}.json").write_text(
                    json.dumps(check, indent=2) + "\n", encoding="utf-8"
                )
                if disagreement is not None:
                    disagreements.append(disagreement)
                if index % 250 == 0 or index == len(samples):
                    print(f"checked {index}/{len(samples)} differential candidates", flush=True)

    validation_rows: list[dict[str, Any]] = []
    if problems and references:
        first = problems[0]
        validation_rows, validation_failures = _validation_checks(
            first, references[first["id"]], lean_invoke, executable
        )
        failures.extend(validation_failures)

    mutation_coverage = Counter(row["mutation_kind"] for row in sample_rows)
    clue_coverage = Counter(
        row["target_clue_type"] for row in sample_rows if row["target_clue_type"] is not None
    )
    grid_coverage: dict[str, Counter[str]] = defaultdict(Counter)
    for row in sample_rows:
        coverage = grid_coverage[row["grid"]]
        coverage["total"] += 1
        coverage[row["sample_kind"]] += 1
    protocol_errors = sum(bool(row["protocol_error"]) for row in results)
    clingo_errors = [
        row for row in results if row["clingo_status"] not in {"satisfied", "violated"}
    ]
    if clingo_errors:
        failures.append(
            {"failure_type": "clingo_check_errors", "sample_ids": [row["sample_id"] for row in clingo_errors]}
        )
    if protocol_errors:
        failures.append({"failure_type": "protocol_errors", "count": protocol_errors})
    if disagreements:
        failures.append({"failure_type": "semantic_disagreements", "count": len(disagreements)})

    reference_results = [row for row in results if row["sample_kind"] == "reference_solution"]
    reference_all_accepted = len(reference_results) == len(problems) and all(
        row["lean_kind"] == "ACCEPT_SOLVED" and row["clingo_satisfied"] is True
        for row in reference_results
    )
    all_grids = set(grid_coverage) == {problem["source"]["grid"] for problem in problems}
    all_clues = all(clue_coverage[clue_type] > 0 for clue_type in CLUE_TYPES)
    pass_conditions = (
        len(samples) >= 10000
        and len(disagreements) == 0
        and protocol_errors == 0
        and not clingo_errors
        and all_grids
        and all_clues
        and reference_all_accepted
        and not failures
    )
    if clingo_module is None or missing:
        status = "blocked"
    else:
        status = "pass" if pass_conditions else "fail"

    _write_jsonl(output / "samples.jsonl", sample_rows)
    _write_jsonl(output / "results.jsonl", results)
    _write_jsonl(output / "disagreements.jsonl", disagreements)
    _write_jsonl(output / "candidate_validation.jsonl", validation_rows)
    manifest = {
        "gate": "stage3b_differential_candidates",
        "status": status,
        "seed": seed,
        "total_samples": len(samples),
        "total_complete_bijective_samples": len(samples),
        "total_reference_solution_samples": len(reference_results),
        "total_mutated_samples": sum(
            row["sample_kind"] == "mutated" and row["mutation_kind"] != "random_complete_assignment"
            for row in sample_rows
        ),
        "total_random_samples": mutation_coverage["random_complete_assignment"],
        "total_lean_accept_solved": sum(row["lean_kind"] == "ACCEPT_SOLVED" for row in results),
        "total_lean_clue_violation": sum(row["lean_status"] == "clue_violation" for row in results),
        "total_clingo_satisfied": sum(row["clingo_satisfied"] is True for row in results),
        "total_clingo_violated": sum(row["clingo_satisfied"] is False for row in results),
        "total_disagreements": len(disagreements),
        "total_protocol_error": protocol_errors,
        "total_candidate_validation_checks": len(validation_rows),
        "grid_coverage": {grid: dict(counts) for grid, counts in sorted(grid_coverage.items())},
        "mutation_coverage": dict(sorted(mutation_coverage.items())),
        "clue_type_target_coverage": {
            clue_type: clue_coverage[clue_type] for clue_type in CLUE_TYPES
        },
        "failures": failures,
        "reference_only": True,
        "trusted_for_runtime": False,
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    examples = ["# Stage 3B differential examples", ""]
    for row in results[:5]:
        examples.extend(["```json", json.dumps(row, indent=2), "```", ""])
    (output / "examples.md").write_text("\n".join(examples), encoding="utf-8")
    summary = f"""# Stage 3B full-candidate differential gate

Status: **{status.upper()}**

- Complete bijective samples: {len(samples)}
- Reference solutions: {len(reference_results)}
- Lean ACCEPT_SOLVED: {sum(row['lean_kind'] == 'ACCEPT_SOLVED' for row in results)}
- Lean clue violations: {sum(row['lean_status'] == 'clue_violation' for row in results)}
- Clingo satisfied: {sum(row['clingo_satisfied'] is True for row in results)}
- Clingo violated: {sum(row['clingo_satisfied'] is False for row in results)}
- Semantic disagreements: {len(disagreements)}
- Protocol errors: {protocol_errors}
- Grids covered: {len(grid_coverage)}
- Target clue types covered: {sum(clue_coverage[t] > 0 for t in CLUE_TYPES)}/10

Clingo is used only as a development-time reference for the exact supplied
assignment. Lean remains the trusted runtime verdict source. The `direct_right`
target uses the exact inverse view of a real `direct_left` clue because Gate A has
no native `direct_right` rows; the underlying puzzle and candidate are unchanged.
"""
    (output / "summary.md").write_text(summary, encoding="utf-8")
    return manifest
