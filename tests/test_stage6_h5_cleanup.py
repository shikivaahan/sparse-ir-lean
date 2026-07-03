"""Focused contracts for the Stage 6 Mode-0 cleanup harness."""

from __future__ import annotations

import json
from pathlib import Path

from sparseir_harness.stage6_h5_cleanup import (
    RESULT_KEYS,
    cheap_working_set,
    extract_candidate,
    frontier_subset,
    generation_messages,
    load_compiled_problems,
    opus_probe_set,
    prompt_template_hash,
    reconstruct_problem,
    wilson,
)


ROOT = Path(__file__).resolve().parents[1]
COMPILED = ROOT / "eval/gates/stage2_gate_a_compile_all/compiled_problems.jsonl"


def test_reconstructed_problem_is_spec_shape_without_gold() -> None:
    row = json.loads(COMPILED.read_text(encoding="utf-8").splitlines()[0])
    problem = reconstruct_problem(row)
    assert problem["id"] == row["problem_id"]
    assert problem["source"]["external_id"] == row["external_id"]
    assert problem["categories"] == {
        category["name"]: category["values"] for category in row["compiled_categories"]
    }
    assert "expect" not in problem
    prompt = json.dumps(generation_messages(problem))
    assert "expect" not in prompt
    assert "source_solution" not in prompt


def test_cleanup_prompt_hash_is_stable_and_differs_from_prior_run() -> None:
    assert prompt_template_hash() == prompt_template_hash()
    prior = json.loads(
        (ROOT / "eval/gates/stage6_mode0_h2_h3/manifest.json").read_text(encoding="utf-8")
    )
    assert prompt_template_hash() != prior["prompt_template_hash"]


def test_extractor_prefers_last_valid_fenced_or_top_level_object() -> None:
    raw = 'reason {"old":true}\n```json\n{"schema_version":"0.2","problem_id":"x","solution":{}}\n```'
    parsed, candidate = extract_candidate(raw)
    assert parsed
    assert json.loads(candidate)["problem_id"] == "x"
    trailing = '{"old":true}\nnotes\n{"schema_version":"0.2","problem_id":"last","solution":{}}'
    assert json.loads(extract_candidate(trailing)[1])["problem_id"] == "last"


def test_full_cheap_order_is_40_per_grid_and_smoke_spans_all_grids() -> None:
    problems = load_compiled_problems(COMPILED)
    full = cheap_working_set(problems, 1000, 20260630)
    counts: dict[str, int] = {}
    for problem in full:
        grid = problem["source"]["grid"]
        counts[grid] = counts.get(grid, 0) + 1
    assert len(counts) == 25
    assert set(counts.values()) == {40}
    assert len({problem["source"]["grid"] for problem in full[:25]}) == 25


def test_frontier_subset_is_balanced_and_contains_probe() -> None:
    problems = load_compiled_problems(COMPILED)
    probe = opus_probe_set(problems, 20260630)
    subset = frontier_subset(problems, 25, 20260630, {problem["id"] for problem in probe})
    counts: dict[int, int] = {}
    for problem in subset:
        houses = problem["size"]["houses"]
        counts[houses] = counts.get(houses, 0) + 1
    assert counts == {2: 5, 3: 5, 4: 5, 5: 5, 6: 5}
    assert {problem["id"] for problem in probe} <= {problem["id"] for problem in subset}


def test_wilson_and_result_schema_contract() -> None:
    interval = wilson(50, 100)
    assert interval["estimate"] == 0.5
    assert interval["low"] < 0.5 < interval["high"]
    assert RESULT_KEYS == {
        "id", "grid_size", "houses", "categories", "model", "arm", "seed",
        "candidate_parsed", "lean_kind", "lean_status", "correct", "confidence",
        "confidence_source", "tokens_in", "tokens_out", "reasoning_tokens",
        "cost_usd", "raw_path",
    }
