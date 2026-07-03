"""Inspect view adapter for saved Stage 4 provider-validation artifacts."""

from __future__ import annotations

import json
from pathlib import Path

from inspect_ai import Task, task
from inspect_ai.dataset import Sample
from inspect_ai.scorer import CORRECT, INCORRECT, Score, Scorer, Target, accuracy, scorer
from inspect_ai.solver import Generate, TaskState, solver


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_DIR = ROOT / "eval" / "gates" / "stage4_trace_parser" / "provider_validation"


def _rows(name: str) -> list[dict]:
    return [
        json.loads(line)
        for line in (ARTIFACT_DIR / name).read_text(encoding="utf-8").splitlines()
        if line
    ]


@solver
def saved_result():
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        del generate
        return state

    return solve


@scorer(metrics=[accuracy()])
def trace_parsed() -> Scorer:
    async def score(state: TaskState, target: Target) -> Score:
        del target
        passed = bool(state.metadata["passed"])
        result = state.metadata["lean_result"]
        return Score(
            value=CORRECT if passed else INCORRECT,
            answer=result.get("kind", "missing_result"),
            explanation="Stage 4 scores parseability only: Lean must return TRACE_PARSED.",
            metadata=result,
        )

    return score


@task
def stage4_provider_validation_view() -> Task:
    prompts = {row["sample_id"]: row for row in _rows("prompts.jsonl")}
    outputs = {row["sample_id"]: row for row in _rows("raw_outputs.jsonl")}
    results = {row["sample_id"]: row for row in _rows("parse_results.jsonl")}
    samples = []
    for sample_id, result in results.items():
        prompt = prompts[sample_id]
        output = outputs[sample_id]
        samples.append(
            Sample(
                id=sample_id,
                input=json.dumps(
                    {
                        "prompt_messages": prompt["messages"],
                        "raw_provider_output": output.get("raw_output"),
                    },
                    indent=2,
                ),
                metadata={
                    "feature": result["feature"],
                    "passed": result["passed"],
                    "lean_result": result["result"],
                    "model": prompt["model"],
                },
            )
        )
    return Task(dataset=samples, solver=saved_result(), scorer=trace_parsed(), model=None)
