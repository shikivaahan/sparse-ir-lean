"""Stage 3A reference-only clingo solution generation tests."""

from __future__ import annotations

import json
import shutil
from copy import deepcopy
from pathlib import Path
from typing import Any

import clingo
import pytest
from jsonschema import Draft202012Validator

from sparseir_harness.reference_solutions import (
    SolveOutcome,
    candidate_from_model,
    run_reference_gate,
    solve_problem,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = ROOT / "tests" / "problems" / "lgp-test-2x2-33.problem.json"
PROBLEM = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
CANDIDATE_SCHEMA = json.loads(
    (ROOT / "schemas" / "zebra-candidate.schema.json").read_text(encoding="utf-8")
)


def _gate_with_problem(root: Path) -> Path:
    gate = root / "gate-a"
    problem_dir = gate / "ingested_problems"
    problem_dir.mkdir(parents=True)
    shutil.copy2(FIXTURE_PATH, problem_dir / "lgp-test-2x2-33.problem.json")
    return gate


@pytest.fixture(scope="module")
def successful_gate(tmp_path_factory: pytest.TempPathFactory) -> tuple[dict[str, Any], Path]:
    root = tmp_path_factory.mktemp("reference-success")
    output = root / "output"
    manifest = run_reference_gate(
        _gate_with_problem(root),
        output,
        max_problems=None,
        timeout_seconds=30,
        store_reference_solutions=True,
    )
    return manifest, output


def test_tiny_puzzle_is_solved_by_clingo() -> None:
    outcome = solve_problem(PROBLEM, timeout_seconds=30, clingo_module=clingo)
    assert outcome.status == "unique"
    assert len(outcome.models) == 1
    assert len(outcome.models[0]) == 4


def test_clingo_model_converts_to_candidate_json_shape() -> None:
    outcome = solve_problem(PROBLEM, timeout_seconds=30, clingo_module=clingo)
    candidate = candidate_from_model(PROBLEM, outcome.models[0])
    Draft202012Validator(CANDIDATE_SCHEMA).validate(candidate)
    assert candidate["problem_id"] == PROBLEM["id"]
    assert set(candidate["solution"]) == {"Name", "Pet"}
    assert all(set(assignments) == {"1", "2"} for assignments in candidate["solution"].values())


def test_unique_and_nonunique_detection() -> None:
    unique = solve_problem(PROBLEM, timeout_seconds=30, clingo_module=clingo)
    nonunique_problem = deepcopy(PROBLEM)
    nonunique_problem["clues"] = []
    nonunique = solve_problem(nonunique_problem, timeout_seconds=30, clingo_module=clingo)
    assert unique.status == "unique"
    assert nonunique.status == "nonunique"
    assert len(nonunique.models) == 2


def test_lean_accepts_clingo_candidate(
    successful_gate: tuple[dict[str, Any], Path],
) -> None:
    manifest, output = successful_gate
    assert manifest["status"] == "pass"
    assert manifest["total_lean_accept_solved"] == 1
    result = json.loads((output / "results.jsonl").read_text(encoding="utf-8"))
    assert result["result"]["kind"] == "ACCEPT_SOLVED"


def test_reference_metadata_is_explicitly_untrusted(
    successful_gate: tuple[dict[str, Any], Path],
) -> None:
    _, output = successful_gate
    reference_path = next((output / "reference_solutions").glob("*.reference_solution.json"))
    reference = json.loads(reference_path.read_text(encoding="utf-8"))
    assert reference["generated_by"] == "clingo"
    assert reference["reference_only"] is True
    assert reference["trusted_for_runtime"] is False
    assert reference["source_problem_id"] == PROBLEM["id"]
    assert reference["source_sha256"]
    assert reference["clingo_version"] == clingo.__version__
    assert reference["lean_check_result"]["kind"] == "ACCEPT_SOLVED"


def test_missing_clingo_is_blocked(tmp_path: Path) -> None:
    output = tmp_path / "output"
    manifest = run_reference_gate(
        _gate_with_problem(tmp_path),
        output,
        max_problems=None,
        timeout_seconds=30,
        store_reference_solutions=True,
        clingo_module=None,
    )
    assert manifest["status"] == "blocked"
    failures = [json.loads(line) for line in (output / "failures.jsonl").read_text().splitlines()]
    assert failures == [{"failure_type": "missing_clingo", "message": "clingo is not installed"}]


def test_timeout_is_recorded(tmp_path: Path) -> None:
    def timeout_solver(_problem: dict[str, Any], seconds: float, _module: Any) -> SolveOutcome:
        return SolveOutcome("timeout", [], seconds)

    output = tmp_path / "output"
    manifest = run_reference_gate(
        _gate_with_problem(tmp_path),
        output,
        max_problems=None,
        timeout_seconds=0.01,
        store_reference_solutions=True,
        solver=timeout_solver,
    )
    assert manifest["status"] == "partial"
    assert manifest["total_clingo_timeout"] == 1
    uniqueness = json.loads((output / "uniqueness.jsonl").read_text(encoding="utf-8"))
    assert uniqueness["status"] == "timeout"
    failure = json.loads((output / "failures.jsonl").read_text(encoding="utf-8"))
    assert failure["failure_type"] == "clingo_timeout"


def test_all_required_artifacts_are_written(
    successful_gate: tuple[dict[str, Any], Path],
) -> None:
    manifest, output = successful_gate
    assert manifest["total_reference_solutions_stored"] == 1
    for name in (
        "manifest.json",
        "problems.jsonl",
        "reference_solutions.jsonl",
        "candidates.jsonl",
        "results.jsonl",
        "uniqueness.jsonl",
        "failures.jsonl",
        "examples.md",
        "summary.md",
    ):
        assert (output / name).is_file()
    assert len(list((output / "clingo_models").glob("*.json"))) == 1
    assert len(list((output / "candidate_json").glob("*.candidate.json"))) == 1
    assert len(list((output / "reference_solutions").glob("*.reference_solution.json"))) == 1
