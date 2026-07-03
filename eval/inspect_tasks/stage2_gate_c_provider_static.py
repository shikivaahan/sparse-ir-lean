"""Inspect AI eval for Stage 2 Gate C provider-output static diagnostics."""

from __future__ import annotations

import asyncio
from pathlib import Path

from inspect_ai import Task, task
from inspect_ai.dataset import Sample
from inspect_ai.scorer import CORRECT, INCORRECT, Score, Scorer, Target, accuracy, scorer
from inspect_ai.solver import Generate, TaskState, solver

from sparseir_harness.stage2_gate_c import (
    DATASET_RELATIVE_PATH,
    generate_dataset,
    initialize_artifacts,
    invoke_lean,
    load_dataset,
    record_provider_result,
)


ROOT = Path(__file__).resolve().parents[1]
DATASET_PATH = ROOT / DATASET_RELATIVE_PATH
_artifact_lock = asyncio.Lock()
_dataset_rows: list[dict] = []
_rows_by_id: dict[str, dict] = {}


@scorer(metrics=[accuracy()])
def lean_compiles() -> Scorer:
    """Show Lean compilation success prominently in Inspect's score column."""

    async def score(state: TaskState, target: Target) -> Score:
        del target
        result = state.metadata.get("gate_c_classification")
        if not isinstance(result, dict):
            return Score.unscored(explanation="Lean classification is missing")
        classification = result.get("classification")
        compiled = classification == "compiled"
        if compiled:
            problem_id = result.get("compiled_problem_id_or_null")
            explanation = f"Lean COMPILED the provider output as {problem_id}."
            answer = "COMPILED"
        else:
            code = result.get("lean_error_code") or "unknown_error"
            path = result.get("lean_error_path") or "$"
            message = result.get("lean_error_message") or "No Lean error message"
            explanation = f"Lean rejected the provider output: {code} at {path}: {message}"
            answer = f"{result.get('lean_protocol_kind') or 'REJECTED'} / {code}"
        return Score(
            value=CORRECT if compiled else INCORRECT,
            answer=answer,
            explanation=explanation,
            metadata=result,
        )

    return score


@solver
def classify_provider_problem_json():
    """Generate once, preserve raw output, and classify it with Lean Stage 1/2."""

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        state = await generate(state)
        sample = _rows_by_id[str(state.sample_id)]
        async with _artifact_lock:
            classification = record_provider_result(
                ROOT,
                _dataset_rows,
                sample,
                state.output.completion,
                lambda request: invoke_lean(request, ROOT),
            )
        state.metadata["gate_c_classification"] = classification
        return state

    return solve


@task
def stage2_gate_c_provider_static() -> Task:
    global _dataset_rows, _rows_by_id
    if not DATASET_PATH.is_file():
        generate_dataset(ROOT, DATASET_PATH)
    _dataset_rows = load_dataset(DATASET_PATH)
    _rows_by_id = {row["sample_id"]: row for row in _dataset_rows}
    initialize_artifacts(ROOT, _dataset_rows)
    samples = [
        Sample(
            id=row["sample_id"],
            input=row["prompt"],
            metadata={
                "sample_id": row["sample_id"],
                "source_problem_id": row["source_problem_id"],
                "source_external_id": row["source_external_id"],
                "source_grid": row["source_grid"],
                "source_problem_path": row["source_problem_path"],
                "task_kind": row["task_kind"],
                "expected_behavior": row["expected_behavior"],
                "target_error_family_or_null": row["target_error_family_or_null"],
                **row["metadata"],
            },
        )
        for row in _dataset_rows
    ]
    return Task(
        dataset=samples,
        solver=classify_provider_problem_json(),
        scorer=lean_compiles(),
    )
