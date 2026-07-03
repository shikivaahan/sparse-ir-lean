#!/usr/bin/env python3
"""Prepare, smoke, run, and finalize the Stage 6 reasoning-budget sweep."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from sparseir_harness.stage6_budget_sweep import (
    BUDGETS,
    N_PUZZLES,
    WORKERS_DEFAULT,
    SMOKE_N,
    _budget_label,
    finalize,
    prepare,
    run,
    smoke,
)


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "eval/gates/stage6_budget_sweep"
COMPILED = ROOT / "eval/gates/stage2_gate_a_compile_all/compiled_problems.jsonl"
EXECUTABLE = ROOT / ".lake/build/bin/sparse-ir-lean"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("prepare", "smoke", "run", "finalize"))
    parser.add_argument("--workers", type=int, default=WORKERS_DEFAULT)
    parser.add_argument("--n", type=int, default=None,
                        help="override N for prepare (default: 200) or smoke (default: 6)")
    parser.add_argument("--budgets", default=None,
                        help="comma-separated budget ladder override (smoke/run); "
                             "values like 0,256,...,full")
    args = parser.parse_args()

    if args.phase == "prepare":
        n = args.n if args.n is not None else N_PUZZLES
        selected = prepare(COMPILED, OUTPUT, EXECUTABLE, n)
        result = {"prepared": len(selected), "house_bins": dict(sorted(
            __import__("collections").Counter(str(p["size"]["houses"]) for p in selected).items()
        ))}
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0

    budgets = None
    if args.budgets:
        budgets = []
        for token in args.budgets.split(","):
            token = token.strip()
            budgets.append(None if token == "full" else int(token))

    if args.phase == "smoke":
        n = args.n if args.n is not None else SMOKE_N
        result = smoke(OUTPUT, EXECUTABLE, budgets=budgets, n=n, workers=args.workers)
        print(json.dumps(result, indent=2, sort_keys=True, default=str))
        return 0 if result["healthy"] else 1

    if args.phase == "run":
        rows = run(OUTPUT, OUTPUT, EXECUTABLE, args.workers, budgets=budgets)
        result = {"completed": len(rows),
                  "budgets": [_budget_label(v) for v in (budgets or BUDGETS)]}
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0

    # finalize
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, capture_output=True, check=True
    ).stdout.strip()
    metrics = finalize(OUTPUT, EXECUTABLE, commit)
    print(json.dumps({"verdict": "complete",
                      "budgets": metrics["totals"]["budgets"],
                      "total_cost_usd": metrics["totals"]["total_cost_usd"]},
                     indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
