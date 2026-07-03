"""Offline Inspect AI replay for the committed Stage 6 H5 cleanup run."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from inspect_ai import Task, task
from inspect_ai.dataset import Sample
from inspect_ai.model import ChatMessageAssistant, ChatMessageSystem, ChatMessageUser, ModelOutput
from inspect_ai.scorer import Score, Scorer, Target, accuracy, scorer, stderr
from inspect_ai.solver import Generate, Solver, TaskState, solver

from sparseir_harness.stage6_h5_cleanup import (
    SYSTEM_PROMPT,
    USER_TEMPLATE,
    check_candidate,
    extract_candidate,
    load_compiled_problems,
)


ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "eval/gates/stage6_mode0_h5_cleanup"
COMPILED = ROOT / "eval/gates/stage2_gate_a_compile_all/compiled_problems.jsonl"
EXECUTABLE = ROOT / ".lake/build/bin/sparse-ir-lean"


@solver
def replay_raw() -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        del generate
        raw = json.loads((ROOT / state.metadata["raw_path"]).read_text(encoding="utf-8"))
        generation = raw["generation"]
        if generation is None:
            text = ""
            model = str(state.metadata["model"])
            stop_reason = "unknown"
        else:
            text = str(generation["text"])
            response = generation["response"]
            model = str(response.get("model") or state.metadata["model"])
            choices = response.get("choices") or []
            finish = choices[0].get("finish_reason") if choices else "stop"
            stop_reason = "max_tokens" if finish == "length" else "stop"
        state.output = ModelOutput.from_content(model=model, content=text, stop_reason=stop_reason)
        state.messages = [
            *state.messages,
            ChatMessageAssistant(content=text, source="generate", model=model),
        ]
        return state

    return solve


@scorer(metrics=[accuracy(), stderr()])
def lean_replay_scorer() -> Scorer:
    async def score(state: TaskState, target: Target) -> Score:
        del target
        problems = {problem["id"]: problem for problem in load_compiled_problems(COMPILED)}
        parsed, candidate_text = extract_candidate(state.output.completion)
        lean_kind, lean_status, correct, result = await asyncio.to_thread(
            check_candidate,
            EXECUTABLE,
            problems[str(state.sample_id).split("::", 1)[1]],
            candidate_text,
        )
        return Score(
            value=1 if correct else 0,
            answer=state.output.completion,
            explanation=f"Lean check_candidate returned {lean_kind}/{lean_status}",
            metadata={
                "candidate_parsed": parsed,
                "lean_kind": lean_kind,
                "lean_status": lean_status,
                "correct": correct,
                "confidence": state.metadata.get("confidence"),
                "cost_usd": state.metadata["cost_usd"],
                "lean_result": result,
            },
        )

    return score


@task
def stage6_h5_replay() -> Task:
    rows = [
        json.loads(line)
        for line in (OUTPUT / "results.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    problems = {problem["id"]: problem for problem in load_compiled_problems(COMPILED)}
    samples: list[Sample] = []
    for row in rows:
        problem = problems[row["id"]]
        user = USER_TEMPLATE.format(
            problem_json=json.dumps(problem, sort_keys=True, separators=(",", ":"))
        )
        samples.append(
            Sample(
                id=f"{row['arm']}::{row['id']}",
                input=[ChatMessageSystem(content=SYSTEM_PROMPT), ChatMessageUser(content=user)],
                metadata={
                    "arm": row["arm"],
                    "model": row["model"],
                    "raw_path": row["raw_path"],
                    "grid_size": row["grid_size"],
                    "houses": row["houses"],
                    "categories": row["categories"],
                    "confidence": row["confidence"],
                    "cost_usd": row["cost_usd"],
                    "oracle_certificate": True,
                    "gold_excluded": True,
                },
            )
        )
    return Task(
        dataset=samples,
        solver=replay_raw(),
        scorer=lean_replay_scorer(),
        model=None,
        name="stage6_h5_replay",
        version="1",
        metadata={
            "replay_only": True,
            "provider_calls": 0,
            "correctness_judge": "Lean check_candidate ACCEPT_SOLVED only",
        },
    )
