from __future__ import annotations

import json
from pathlib import Path

from sparseir_harness.reference_solutions import candidate_from_model, solve_problem
from sparseir_harness.stage6_contamination import (
    extract_final_json,
    perturb_problem,
    remap_candidate_to_original,
)
from sparseir_harness.stage6_h5_cleanup import load_compiled_problems


ROOT = Path(__file__).resolve().parents[1]
COMPILED = ROOT / "eval/gates/stage2_gate_a_compile_all/compiled_problems.jsonl"


def test_perturbation_is_unique_natural_and_changes_house_layout() -> None:
    original = load_compiled_problems(COMPILED)[0]
    perturbed, mapping = perturb_problem(original)
    outcome = solve_problem(perturbed, 5.0)
    assert outcome.status == "unique"
    assert all(value.isalpha() for values in perturbed["categories"].values() for value in values)
    assert mapping["house_permutation"]["1"] == str(original["size"]["houses"])
    candidate = candidate_from_model(perturbed, outcome.models[0])
    remapped = remap_candidate_to_original(candidate, mapping)
    assert remapped is not None
    assert remapped["problem_id"] == original["id"]
    assert json.dumps(remapped) != json.dumps(candidate)


def test_think_is_stripped_only_as_parse_fallback() -> None:
    raw = '<think>{not json}</think>{"schema_version":"0.2","problem_id":"x","solution":{}}'
    parsed, candidate, _, stripped = extract_final_json(raw)
    assert parsed and candidate["problem_id"] == "x"
    assert not stripped
    raw = '<think>{"decoy":true}</think>final without json'
    parsed, _, _, stripped = extract_final_json(raw)
    assert not parsed and stripped
