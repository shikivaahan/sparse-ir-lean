#!/usr/bin/env python3
"""Run phases of the Stage 6 Mode-0 cleanup and frontier evaluation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from sparseir_harness.stage6_h5_cleanup import (
    CHEAP_ARM,
    CHEAP_MODEL,
    FRONTIER_ARM,
    FRONTIER_MODEL,
    OPUS_BUDGET_USD,
    SEED,
    _theoretical_opus_call_cost,
    cheap_working_set,
    choose_frontier_n,
    finalize,
    frontier_subset,
    git_head,
    load_compiled_problems,
    opus_probe_set,
    prepare_working_set,
    run_arm,
)


ROOT = Path(__file__).resolve().parents[2]
COMPILED = ROOT / "eval/gates/stage2_gate_a_compile_all/compiled_problems.jsonl"
OUTPUT = ROOT / "eval/gates/stage6_mode0_h5_cleanup"
EXECUTABLE = ROOT / ".lake/build/bin/sparse-ir-lean"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "phase", choices=("prepare", "cheap", "opus-probe", "opus-run", "finalize")
    )
    parser.add_argument("--n", type=int)
    parser.add_argument("--workers", type=int, default=16)
    args = parser.parse_args()

    problems = load_compiled_problems(COMPILED)
    if args.phase == "prepare":
        result = prepare_working_set(COMPILED, OUTPUT, EXECUTABLE)
    elif args.phase == "cheap":
        n = args.n or 1000
        selected = cheap_working_set(problems, n, SEED)
        rows = run_arm(
            selected,
            OUTPUT,
            EXECUTABLE,
            model=CHEAP_MODEL,
            arm=CHEAP_ARM,
            seed=SEED,
            workers=args.workers,
        )
        result = {
            "n": len(rows),
            "malformed": sum(row["lean_status"] == "malformed" for row in rows),
            "malformed_rate": sum(row["lean_status"] == "malformed" for row in rows)
            / len(rows),
            "cost_usd": sum(float(row["cost_usd"]) for row in rows),
        }
    elif args.phase == "opus-probe":
        selected = opus_probe_set(problems, SEED)
        rows = run_arm(
            selected,
            OUTPUT,
            EXECUTABLE,
            model=FRONTIER_MODEL,
            arm=FRONTIER_ARM,
            seed=SEED,
            workers=1,
            budget_usd=OPUS_BUDGET_USD,
            hard_call_bounds={
                problem["id"]: _theoretical_opus_call_cost(problem) for problem in selected
            },
        )
        result = choose_frontier_n(problems, rows, SEED)
        (OUTPUT / "opus_cost_gate.json").write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    elif args.phase == "opus-run":
        gate = json.loads((OUTPUT / "opus_cost_gate.json").read_text(encoding="utf-8"))
        selected = frontier_subset(problems, int(gate["n"]), SEED, set(gate["probe_ids"]))
        rows = run_arm(
            selected,
            OUTPUT,
            EXECUTABLE,
            model=FRONTIER_MODEL,
            arm=FRONTIER_ARM,
            seed=SEED,
            workers=1,
            budget_usd=OPUS_BUDGET_USD,
            hard_call_bounds={
                problem["id"]: _theoretical_opus_call_cost(problem) for problem in selected
            },
        )
        result = {
            "n": len(rows),
            "cost_usd": sum(float(row["cost_usd"]) for row in rows),
            "malformed_rate": sum(row["lean_status"] == "malformed" for row in rows)
            / len(rows),
        }
    else:
        result = finalize(COMPILED, OUTPUT, EXECUTABLE, git_head(ROOT))
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
