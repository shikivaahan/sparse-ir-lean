"""Stage 3C stepwise kernel protocol and evidence tests."""

from __future__ import annotations

import json
import subprocess
from copy import deepcopy
from pathlib import Path
from typing import Any

from sparseir_harness.step_kernel_gate import (
    CLUE_TYPES,
    REJECTION_CODES,
    SUPPORTED_RULES,
    complete_state,
    run_step_gate,
)

from tests._dataset_prereq import require_ingested_problems


require_ingested_problems()


ROOT = Path(__file__).resolve().parents[1]
EXECUTABLE = ROOT / ".lake" / "build" / "bin" / "sparse-ir-lean"
PROBLEM = json.loads(
    (ROOT / "tests" / "problems" / "lgp-test-4x4-27.problem.json").read_text(encoding="utf-8")
)
PROBLEM_2X2 = json.loads(
    (ROOT / "tests" / "problems" / "lgp-test-2x2-33.problem.json").read_text(encoding="utf-8")
)
REFERENCE_2X2 = {
    "schema_version": "0.2",
    "problem_id": PROBLEM_2X2["id"],
    "solution": {
        "Name": {"1": "Eric", "2": "Arnold"},
        "Pet": {"1": "cat", "2": "dog"},
    },
}


def _call(command: str, payload: dict[str, Any]) -> dict[str, Any]:
    completed = subprocess.run(
        [str(EXECUTABLE)],
        cwd=ROOT,
        input=json.dumps(
            {
                "protocol_version": "0.1.0",
                "request_id": "stage3c-test",
                "command": command,
                "payload": payload,
            }
        ),
        text=True,
        capture_output=True,
        check=True,
    )
    return json.loads(completed.stdout)["result"]


def _init(problem: dict[str, Any] = PROBLEM) -> dict[str, Any]:
    result = _call("init_state", {"problem": json.dumps(problem)})
    assert result["kind"] == "STATE_INITIALIZED"
    return result["state"]


def _apply(
    problem: dict[str, Any], state: dict[str, Any], step: dict[str, Any], command: str = "apply_step"
) -> dict[str, Any]:
    return _call(
        command,
        {"problem": json.dumps(problem), "state": json.dumps(state), "step": json.dumps(step)},
    )


def _cell(state: dict[str, Any], category: str, house: int) -> dict[str, Any]:
    return next(
        cell for cell in state["cells"] if cell["cat"] == category and cell["house"] == house
    )


def test_init_state_contains_full_candidate_grid() -> None:
    state = _init()
    assert state["step_count"] == 0
    assert len(state["cells"]) == 16
    assert all(len(cell["possible"]) == 4 and cell["placed"] is False for cell in state["cells"])


def test_place_updates_cell_and_propagates_bijection() -> None:
    state = _init()
    step = {
        "op": "place",
        "cat": "BookGenre",
        "house": 2,
        "val": "fantasy",
        "justify": {"rule": "given_found_at_place", "clue_id": "c2"},
    }
    result = _apply(PROBLEM, state, step)
    assert result["kind"] == "ACCEPT_STEP"
    updated = result["state"]
    assert _cell(updated, "BookGenre", 2) == {
        "cat": "BookGenre",
        "house": 2,
        "possible": ["fantasy"],
        "placed": True,
    }
    assert all(
        "fantasy" not in _cell(updated, "BookGenre", house)["possible"]
        for house in (1, 3, 4)
    )


def test_eliminate_updates_only_the_target_candidate() -> None:
    state = _init()
    step = {
        "op": "eliminate",
        "cat": "Name",
        "house": 2,
        "val": "Alice",
        "justify": {"rule": "given_not_at_eliminate", "clue_id": "c3"},
    }
    result = _apply(PROBLEM, state, step)
    assert result["kind"] == "ACCEPT_STEP"
    assert "Alice" not in _cell(result["state"], "Name", 2)["possible"]
    assert "Alice" in _cell(result["state"], "Name", 1)["possible"]


def test_duplicate_and_conflicting_places_are_rejected() -> None:
    state = _init()
    step = {
        "op": "place",
        "cat": "BookGenre",
        "house": 2,
        "val": "fantasy",
        "justify": {"rule": "given_found_at_place", "clue_id": "c2"},
    }
    placed = _apply(PROBLEM, state, step)["state"]
    duplicate = _apply(PROBLEM, placed, step)
    assert duplicate["failure"]["failure_code"] == "contradicts_state"

    conflict_state = deepcopy(state)
    cell = _cell(conflict_state, "BookGenre", 2)
    cell["possible"] = ["mystery"]
    cell["placed"] = True
    conflict = _apply(PROBLEM, conflict_state, step)
    assert conflict["failure"]["failure_code"] == "placement_conflict"


def test_true_but_unsupported_step_is_rejected() -> None:
    state = _init(PROBLEM_2X2)
    step = {
        "op": "place",
        "cat": "Name",
        "house": 1,
        "val": "Eric",
        "justify": {"rule": "unchecked_guess"},
    }
    result = _apply(PROBLEM_2X2, state, step, command="check_step")
    assert result["kind"] == "REJECT"
    assert result["failure"]["failure_code"] == "unsupported_rule"


def test_solved_conclusion_requires_complete_satisfying_state() -> None:
    solved_state = complete_state(PROBLEM_2X2, REFERENCE_2X2)
    solved = _apply(PROBLEM_2X2, solved_state, {"op": "conclude", "status": "solved"})
    assert solved["kind"] == "ACCEPT_SOLVED"

    incomplete = _apply(PROBLEM_2X2, _init(PROBLEM_2X2), {"op": "conclude", "status": "solved"})
    assert incomplete["failure"]["failure_code"] == "incomplete_final"

    violating = deepcopy(REFERENCE_2X2)
    violating["solution"]["Pet"] = {"1": "dog", "2": "cat"}
    invalid = _apply(
        PROBLEM_2X2,
        complete_state(PROBLEM_2X2, violating),
        {"op": "conclude", "status": "solved"},
    )
    assert invalid["failure"]["failure_code"] == "clue_violation_final"


def test_stage3c_gate_covers_rules_rejections_clues_and_artifacts(tmp_path: Path) -> None:
    output = tmp_path / "stage3c"
    manifest = run_step_gate(
        ROOT / "eval" / "gates" / "stage2_gate_a_compile_all",
        ROOT / "eval" / "gates" / "stage3a_reference_solutions",
        output,
        20260629,
    )
    assert manifest["status"] == "pass"
    assert set(manifest["supported_rule_coverage"]) == set(SUPPORTED_RULES)
    assert all(manifest["supported_rule_coverage"].values())
    assert set(manifest["rejection_code_coverage"]) == set(REJECTION_CODES)
    assert all(manifest["rejection_code_coverage"].values())
    assert set(manifest["clue_type_coverage"]) == set(CLUE_TYPES)
    assert all(manifest["clue_type_coverage"].values())
    assert manifest["total_protocol_error"] == 0
    for name in ("manifest.json", "steps.jsonl", "results.jsonl", "failures.jsonl", "examples.md", "summary.md"):
        assert (output / name).is_file()
    assert list((output / "state_json").glob("*.state.json"))
    assert list((output / "step_json").glob("*.step.json"))
