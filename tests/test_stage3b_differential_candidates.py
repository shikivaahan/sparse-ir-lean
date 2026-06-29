"""Focused Stage 3B full-candidate differential gate tests."""

from __future__ import annotations

import json
import random
import shutil
from copy import deepcopy
from pathlib import Path
from typing import Any

import clingo

from sparseir_harness.differential_candidates import (
    ClingoCandidateCheck,
    check_candidate_with_clingo,
    generate_samples,
    is_complete_bijective,
    random_complete_candidate,
    run_differential_gate,
    semantic_agreement,
)
from sparseir_harness.reference_solutions import ROOT, _invoke_lean


FIXTURE_PATH = ROOT / "tests" / "problems" / "lgp-test-2x2-33.problem.json"
PROBLEM = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
REFERENCE = {
    "schema_version": "0.2",
    "problem_id": PROBLEM["id"],
    "solution": {
        "Name": {"1": "Eric", "2": "Arnold"},
        "Pet": {"1": "cat", "2": "dog"},
    },
}


def _lean(candidate: dict[str, Any]) -> dict[str, Any]:
    executable = ROOT / ".lake" / "build" / "bin" / "sparse-ir-lean"
    request = {
        "protocol_version": "0.1.0",
        "request_id": "stage3b-test",
        "command": "check_candidate",
        "payload": {"problem": json.dumps(PROBLEM), "candidate": json.dumps(candidate)},
    }
    return _invoke_lean(request, executable)["result"]


def _tiny_gate(root: Path) -> tuple[Path, Path]:
    gate = root / "gate-a"
    problem_dir = gate / "ingested_problems"
    problem_dir.mkdir(parents=True)
    shutil.copy2(FIXTURE_PATH, problem_dir / "lgp-test-2x2-33.problem.json")
    reference_dir = root / "references"
    reference_dir.mkdir()
    row = {
        "source_problem_id": PROBLEM["id"],
        "source_external_id": PROBLEM["source"]["external_id"],
        "source_grid": PROBLEM["source"]["grid"],
        "candidate": REFERENCE,
        "reference_only": True,
        "trusted_for_runtime": False,
    }
    (reference_dir / "reference_solutions.jsonl").write_text(json.dumps(row) + "\n")
    return gate, reference_dir


def test_candidate_mutation_generation_is_deterministic_by_seed() -> None:
    first = generate_samples([PROBLEM], {PROBLEM["id"]: REFERENCE}, 20260629, 10)
    second = generate_samples([PROBLEM], {PROBLEM["id"]: REFERENCE}, 20260629, 10)
    assert [sample.candidate for sample in first] == [sample.candidate for sample in second]
    assert [sample.mutation_kind for sample in first] == [sample.mutation_kind for sample in second]


def test_reference_solution_samples_are_always_included() -> None:
    samples = generate_samples([PROBLEM], {PROBLEM["id"]: REFERENCE}, 7, 10)
    reference_samples = [sample for sample in samples if sample.sample_kind == "reference_solution"]
    assert len(reference_samples) == 1
    assert reference_samples[0].candidate == REFERENCE


def test_random_complete_candidates_are_bijective() -> None:
    rng = random.Random(20260629)
    for _ in range(20):
        candidate = random_complete_candidate(PROBLEM, REFERENCE, rng)
        assert is_complete_bijective(PROBLEM, candidate)
        assert candidate != REFERENCE


def test_lean_and_clingo_agree_on_tiny_solved_candidate() -> None:
    lean_result = _lean(REFERENCE)
    clingo_result = check_candidate_with_clingo(PROBLEM, REFERENCE, 30, clingo)
    assert lean_result["kind"] == "ACCEPT_SOLVED"
    assert clingo_result.satisfied is True
    assert semantic_agreement(lean_result, clingo_result)


def test_lean_and_clingo_agree_on_tiny_clue_violation() -> None:
    violating = deepcopy(REFERENCE)
    violating["solution"]["Pet"] = {"1": "dog", "2": "cat"}
    lean_result = _lean(violating)
    clingo_result = check_candidate_with_clingo(PROBLEM, violating, 30, clingo)
    assert lean_result["failure"]["status"] == "clue_violation"
    assert clingo_result.satisfied is False
    assert semantic_agreement(lean_result, clingo_result)


def test_disagreement_detection_fails_gate_and_writes_artifacts(tmp_path: Path) -> None:
    gate, references = _tiny_gate(tmp_path)

    def false_clingo(
        _problem: dict[str, Any],
        _candidate: dict[str, Any],
        _timeout: float,
        _module: Any,
    ) -> ClingoCandidateCheck:
        return ClingoCandidateCheck("violated", False, 0.0)

    output = tmp_path / "output"
    manifest = run_differential_gate(
        gate,
        references,
        output,
        seed=1,
        target_candidates=1,
        timeout_seconds=30,
        clingo_checker=false_clingo,
        workers=1,
    )
    assert manifest["status"] == "fail"
    assert manifest["total_disagreements"] == 1
    disagreement = json.loads((output / "disagreements.jsonl").read_text(encoding="utf-8"))
    assert disagreement["problem_id"] == PROBLEM["id"]
    assert disagreement["lean_result"]["kind"] == "ACCEPT_SOLVED"
    assert disagreement["clingo_result"]["satisfied"] is False

    for name in (
        "manifest.json",
        "samples.jsonl",
        "results.jsonl",
        "disagreements.jsonl",
        "candidate_validation.jsonl",
        "examples.md",
        "summary.md",
    ):
        assert (output / name).is_file()
    assert len(list((output / "candidate_json").glob("*.candidate.json"))) == 1
    assert len(list((output / "clingo_checks").glob("*.json"))) == 1
