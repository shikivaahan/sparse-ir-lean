"""Stage 6 Mode-0 orchestration tests; Lean remains the verdict source."""

from __future__ import annotations

import json
from pathlib import Path

from sparseir_harness.stage6_mode0 import (
    ProviderResult,
    compute_metrics,
    generation_messages,
    load_sampled_problems,
    normalize_lean_result,
    parse_candidate,
    parse_confidence,
    problem_for_verifier,
    run_evaluation,
)


ROOT = Path(__file__).resolve().parents[1]
PROBLEMS = ROOT / "eval/gates/stage2_gate_a_compile_all/ingested_problems"
EXECUTABLE = ROOT / ".lake/build/bin/sparse-ir-lean"


def _provider(text: str) -> ProviderResult:
    return ProviderResult(
        text=text,
        response={"choices": [{"message": {"content": text}}]},
        tokens_in=10,
        tokens_out=5,
        cost_usd=0.0001,
    )


def test_prompt_excludes_expect_and_reference_solution() -> None:
    problem = json.loads((PROBLEMS / "lgp-test-2x2-33.problem.json").read_text())
    prompt = json.dumps(generation_messages(problem))
    assert "expect" not in prompt
    assert "source_solution" not in prompt
    assert problem["id"] in prompt
    verifier_problem = problem_for_verifier(problem)
    assert "expect" not in verifier_problem
    assert verifier_problem["source"] == problem["source"]


def test_sampling_prefix_is_balanced_and_stable() -> None:
    first = load_sampled_problems(PROBLEMS, 10, 20260630)
    second = load_sampled_problems(PROBLEMS, 200, 20260630)
    assert [problem["id"] for problem in first] == [problem["id"] for problem in second[:10]]
    assert {problem["size"]["houses"] for problem in first} == {2, 3, 4, 5, 6}
    assert {problem["size"]["categories"] for problem in first} == {2, 3, 4, 5, 6}
    breakdown: dict[str, int] = {}
    for problem in second:
        grid = problem["source"]["grid"]
        breakdown[grid] = breakdown.get(grid, 0) + 1
    assert set(breakdown.values()) == {8}
    assert len(breakdown) == 25


def test_parsing_is_transport_only_and_lean_mapping_is_fail_closed() -> None:
    assert parse_candidate('```json\n{"schema_version":"0.2"}\n```')[0]
    assert not parse_candidate("not json")[0]
    assert parse_confidence("0.75") == 0.75
    assert parse_confidence("probably 0.75") is None
    assert normalize_lean_result({"kind": "ACCEPT_SOLVED"}) == (
        "ACCEPT_SOLVED",
        "solved",
        True,
    )
    assert normalize_lean_result(
        {"kind": "REJECT", "failure": {"status": "malformed_candidate"}}
    ) == ("MALFORMED", "malformed", False)


def test_end_to_end_fake_provider_uses_lean_and_writes_exact_schema(tmp_path: Path) -> None:
    problem = load_sampled_problems(PROBLEMS, 1, 7)[0]
    # Use the retained reference only to provide a deterministic test fixture; runtime scoring
    # still goes through Lean and production prompts never read this file.
    references = ROOT / "eval/gates/stage3a_reference_solutions/reference_solutions.jsonl"
    candidate = next(
        json.loads(line)["candidate"]
        for line in references.read_text(encoding="utf-8").splitlines()
        if json.loads(line)["source_problem_id"] == problem["id"]
    )

    def fake_call(_messages: list[dict[str, str]], confidence: bool) -> ProviderResult:
        return _provider("0.8" if confidence else json.dumps(candidate))

    output = tmp_path / "stage6"
    manifest = run_evaluation(
        PROBLEMS,
        output,
        EXECUTABLE,
        n=1,
        seed=7,
        model="fixture/model",
        git_commit="fixture",
        provider_call=fake_call,
    )
    row = json.loads((output / "results.jsonl").read_text())
    assert row["correct"] is True
    assert row["lean_kind"] == "ACCEPT_SOLVED"
    assert set(row) == {
        "id", "grid_size", "houses", "categories", "candidate_parsed", "lean_kind",
        "lean_status", "correct", "confidence", "confidence_source", "tokens_in",
        "tokens_out", "raw_path",
    }
    raw = json.loads((output / "raw" / f"{problem['id']}.json").read_text())
    assert raw["generation"]["text"] == json.dumps(candidate)
    assert raw["lean_result"]["kind"] == "ACCEPT_SOLVED"
    assert manifest["n"] == 1


def test_metrics_reuse_one_verdict_across_all_three_arms() -> None:
    rows = [
        {"grid_size": "2x2", "correct": True, "lean_kind": "ACCEPT_SOLVED", "confidence": 0.9},
        {"grid_size": "2x2", "correct": False, "lean_kind": "REJECT", "confidence": 0.8},
    ]
    metrics = compute_metrics(rows)
    assert metrics["unchecked"]["confident_wrong_rate"] == 0.5
    assert metrics["mode0"] == {
        "coverage": 0.5,
        "selective_risk": 0.0,
        "catastrophic_rate": 0.0,
        "accuracy_committed": 1.0,
    }
    assert metrics["headline"]["H2_confident_wrong_drop"] == 0.5


def test_h3_does_not_overclaim_when_mode0_commits_nothing() -> None:
    metrics = compute_metrics(
        [{"grid_size": "4x5", "correct": False, "lean_kind": "REJECT", "confidence": 0.9}]
    )
    assert metrics["mode0"]["coverage"] == 0.0
    assert "uninformative" in metrics["headline"]["H3_lean_point_vs_ptrue_curve_note"]
