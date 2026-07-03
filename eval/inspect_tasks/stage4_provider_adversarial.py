"""Provider-free Inspect view for saved Stage 4 adversarial parser evidence."""

from __future__ import annotations

import json
from pathlib import Path

from inspect_ai import Task, task
from inspect_ai.dataset import Sample
from inspect_ai.scorer import CORRECT, INCORRECT, Score, Scorer, Target, accuracy, scorer
from inspect_ai.solver import Generate, TaskState, solver


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_DIR = (
    ROOT / "eval" / "gates" / "stage4_trace_parser" / "provider_adversarial"
)


def _rows(name: str) -> dict[str, dict]:
    return {
        row["sample_id"]: row
        for line in (ARTIFACT_DIR / name).read_text(encoding="utf-8").splitlines()
        if line
        for row in [json.loads(line)]
    }


@solver
def saved_result():
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        del generate
        return state

    return solve


@scorer(metrics=[accuracy()])
def expected_parser_result() -> Scorer:
    async def score(state: TaskState, target: Target) -> Score:
        del target
        metadata = state.metadata
        result = metadata["lean_result"]
        expected = metadata["expected_result"]
        if expected == "TRACE_PARSED":
            explanation = "Positive syntax sample: Lean must return TRACE_PARSED."
        else:
            explanation = (
                "Adversarial syntax sample: provider compliance is scored separately, "
                "and Lean must reject with the requested structured code and path."
            )
        return Score(
            value=CORRECT if metadata["passed"] else INCORRECT,
            answer=result.get("kind", "extraction_rejection"),
            explanation=explanation,
            metadata={
                "bucket": metadata["bucket"],
                "expected_result": expected,
                "model_complied": metadata["model_complied"],
                "error_code": metadata.get("error_code"),
                "path": metadata.get("path"),
                "lean_result": result,
                "raw_lean_output": metadata["raw_lean_output"],
            },
        )

    return score


@task
def stage4_provider_adversarial() -> Task:
    prompts = _rows("prompts.jsonl")
    outputs = _rows("raw_outputs.jsonl")
    extracted = _rows("extracted_json.jsonl")
    results = _rows("parse_results.jsonl")
    lean_outputs = _rows("lean_outputs.jsonl")
    samples = []
    for sample_id, result in results.items():
        prompt = prompts[sample_id]
        output = outputs[sample_id]
        extraction = extracted[sample_id]
        lean = lean_outputs[sample_id]
        score = result["score"]
        samples.append(
            Sample(
                id=sample_id,
                input=json.dumps(
                    {
                        "bucket": result["bucket"],
                        "expected_result": score["expected_result"],
                        "prompt": prompt["messages"],
                        "raw_provider_output": output.get("raw_output"),
                        "extracted_json": extraction.get("extracted_json"),
                        "lean_input": lean["lean_input"],
                        "lean_raw_output": lean["raw_lean_output"],
                        "lean_result": result["lean_result"],
                        "error_code": score.get("actual_code"),
                        "path": score.get("actual_path"),
                        "score": "PASS" if result["passed"] else "FAIL",
                    },
                    indent=2,
                ),
                metadata={
                    "bucket": result["bucket"],
                    "expected_result": score["expected_result"],
                    "passed": result["passed"],
                    "model_complied": result["model_complied"],
                    "lean_result": result["lean_result"],
                    "raw_lean_output": lean["raw_lean_output"],
                    "error_code": score.get("actual_code"),
                    "path": score.get("actual_path"),
                    "model": prompt["model"],
                },
            )
        )
    return Task(
        dataset=samples,
        solver=saved_result(),
        scorer=expected_parser_result(),
        model=None,
    )
