"""Stage 3A candidate checker protocol and gate tests.

Lean supplies every verdict. Python validates transport and retained evidence.
"""

from __future__ import annotations

import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from tests._dataset_prereq import require_ingested_problems


require_ingested_problems()


ROOT = Path(__file__).resolve().parents[1]
GATE_A = ROOT / "eval" / "gates" / "stage2_gate_a_compile_all"
PROBLEM = json.loads(
    (GATE_A / "ingested_problems" / "lgp-test-2x2-33.problem.json").read_text(encoding="utf-8")
)
CANDIDATE_SCHEMA = json.loads(
    (ROOT / "schemas" / "zebra-candidate.schema.json").read_text(encoding="utf-8")
)
EXECUTABLE = ROOT / ".lake" / "build" / "bin" / "sparse-ir-lean"


def _known_candidate() -> dict[str, Any]:
    return {
        "schema_version": "0.2",
        "problem_id": PROBLEM["id"],
        "solution": {
            "Name": {"1": "Eric", "2": "Arnold"},
            "Pet": {"1": "cat", "2": "dog"},
        },
    }


def _check(candidate: dict[str, Any] | str, problem: dict[str, Any] = PROBLEM) -> dict[str, Any]:
    candidate_text = candidate if isinstance(candidate, str) else json.dumps(candidate)
    completed = subprocess.run(
        [str(EXECUTABLE)],
        cwd=ROOT,
        input=json.dumps({
            "protocol_version": "0.1.0",
            "request_id": "stage3a-test",
            "command": "check_candidate",
            "payload": {"problem": json.dumps(problem), "candidate": candidate_text},
        }),
        text=True,
        capture_output=True,
        check=True,
    )
    response = json.loads(completed.stdout)
    return response["result"]


def test_candidate_schema_accepts_minimal_one_based_format() -> None:
    Draft202012Validator(CANDIDATE_SCHEMA).validate(_known_candidate())


def test_known_satisfying_real_2x2_is_accepted_by_lean() -> None:
    result = _check(_known_candidate())
    assert result == {
        "kind": "ACCEPT_SOLVED",
        "artifact": {
            "problem_id": PROBLEM["id"],
            "status": "solved",
            "claim": "assignment satisfies all clues of the puzzle",
        },
    }


def test_expect_is_not_a_checker_premise() -> None:
    problem = deepcopy(PROBLEM)
    problem["expect"] = {"source_solution": "deliberately false and ignored"}
    assert _check(_known_candidate(), problem)["kind"] == "ACCEPT_SOLVED"


def test_complete_bijective_candidate_localizes_first_clue_violation() -> None:
    candidate = _known_candidate()
    candidate["solution"]["Pet"] = {"1": "dog", "2": "cat"}
    result = _check(candidate)
    assert result["kind"] == "REJECT"
    assert result["failure"] == {
        "status": "clue_violation",
        "failure_code": "clue_violation",
        "clue_id": "c2",
        "path": "$.clues[1]",
        "message": "candidate violates clue c2",
    }


def test_partial_candidate_is_incomplete_without_support_search() -> None:
    candidate = _known_candidate()
    candidate["solution"]["Name"].pop("2")
    result = _check(candidate)
    assert result["kind"] == "INCOMPLETE"
    assert result["state"]["status"] == "incomplete"
    assert result["state"]["failure_code"] == "missing_assignment"
    assert result["state"]["path"] == "$.solution.Name.2"


def test_invalid_and_malformed_candidates_are_separate() -> None:
    candidate = _known_candidate()
    candidate["solution"]["Pet"]["1"] = "dragon"
    invalid = _check(candidate)
    assert invalid["kind"] == "REJECT"
    assert invalid["failure"]["status"] == "invalid_candidate"
    assert invalid["failure"]["failure_code"] == "unknown_value"

    malformed = _check("{")
    assert malformed["kind"] == "REJECT"
    assert malformed["failure"]["status"] == "malformed_candidate"
    assert malformed["failure"]["failure_code"] == "invalid_candidate_json"


def test_stage3a_gate_covers_all_clues_and_candidate_invariants(tmp_path: Path) -> None:
    output = tmp_path / "stage3a"
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "stage3a_check_candidates.py"),
            "--gate-a-dir",
            str(GATE_A),
            "--output",
            str(output),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))

    assert manifest["status"] == "blocked"
    assert manifest["total_candidates"] == 20
    assert manifest["total_accept_solved"] == 1
    assert manifest["total_reject"] == 17
    assert manifest["total_incomplete"] == 2
    assert manifest["total_protocol_error"] == 0
    assert all(manifest["clue_type_violation_coverage"].values())
    assert all(manifest["candidate_error_coverage"].values())
    assert {"2x2", "4x4", "6x6"}.issubset(manifest["grid_coverage"])
    assert manifest["usable_gold_source_solutions"] == 0
    assert manifest["failures"] == [
        {
            "blocker": "gold_solution_extraction",
            "message": (
                "Gate A source_solution rows are redacted as ___; provide populated source rows "
                "or an independently provenance-checked gold assignment export before PASS"
            ),
        }
    ]
    for name in ("manifest.json", "candidates.jsonl", "results.jsonl", "examples.md", "summary.md"):
        assert (output / name).is_file()
    assert len(list((output / "candidate_json").glob("*.candidate.json"))) == 19
