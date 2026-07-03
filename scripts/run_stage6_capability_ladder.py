#!/usr/bin/env python3
"""Prepare, probe, run, and finalize the Stage 6 capability ladder."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from sparseir_harness.stage6_capability_ladder import (
    MODELS,
    finalize,
    prepare,
    run_concurrency_probe,
    run_full,
    resume_one_model,
)
from sparseir_harness.stage6_budget_sweep import (
    N_PUZZLES,
    select_puzzles,
    _read_jsonl,
)
from sparseir_harness.stage6_h5_cleanup import load_compiled_problems


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "eval/gates/stage6_capability_ladder"
COMPILED = ROOT / "eval/gates/stage2_gate_a_compile_all/compiled_problems.jsonl"
EXECUTABLE = ROOT / ".lake/build/bin/sparse-ir-lean"


def _load_puzzles():
    problems = load_compiled_problems(COMPILED)
    return select_puzzles(problems, N_PUZZLES, 20260702)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("prepare", "probe", "run", "finalize"))
    parser.add_argument("--n", type=int, default=N_PUZZLES,
                        help="override N for prepare (default mirrors budget sweep)")
    parser.add_argument("--model", choices=[m["id"] for m in MODELS],
                        help="limit resume/finalize result rewriting to one model")
    parser.add_argument("--resume", action="store_true",
                        help="resume only missing IDs for --model")
    parser.add_argument("--workers", type=int, default=1,
                        help="workers for a resumed model (default: 1)")
    args = parser.parse_args()

    if args.phase == "prepare":
        prepare(COMPILED, OUTPUT, EXECUTABLE, n=args.n)
        result = {"prepared": args.n, "models": [m["id"] for m in MODELS]}
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0

    if args.phase == "probe":
        problems = _load_puzzles()
        probe_results, chosen, rejected = run_concurrency_probe(problems, OUTPUT, EXECUTABLE)
        # Persist probe artifacts immediately for the user to inspect.
        OUTPUT.mkdir(parents=True, exist_ok=True)
        (OUTPUT / "concurrency_probe.json").write_text(json.dumps({
            "probed": probe_results, "chosen": chosen, "rejected": rejected
        }, indent=2, sort_keys=True), encoding="utf-8")
        from sparseir_harness.stage6_capability_ladder import _render_probe_markdown
        (OUTPUT / "concurrency_probe.md").write_text(
            _render_probe_markdown(probe_results, chosen, rejected),
            encoding="utf-8",
        )
        result = {
            "chosen": chosen,
            "rejected_summary": {
                mid: [{"workers": r["workers"], "reason": r["reason"]} for r in rejected.get(mid, [])]
                for mid in [m["id"] for m in MODELS]
            },
        }
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0

    if args.phase == "run":
        # Chosen workers must already exist on disk from probe; reload them.
        probe_blob = json.loads((OUTPUT / "concurrency_probe.json").read_text())
        chosen = probe_blob["chosen"]
        problems = _load_puzzles()
        if args.resume:
            if not args.model:
                parser.error("--resume requires --model")
            problems = _read_jsonl(OUTPUT / "configs" / "puzzles.jsonl")
            rows = resume_one_model(problems, args.model, OUTPUT, EXECUTABLE, args.workers)
            print(json.dumps({"model": args.model, "completed": len(rows)}, indent=2, sort_keys=True))
            return 0
        run_full(problems, OUTPUT, EXECUTABLE, chosen)
        print(json.dumps({"chosen": chosen}, indent=2, sort_keys=True))
        return 0

    # finalize
    probe_blob = json.loads((OUTPUT / "concurrency_probe.json").read_text())
    chosen = probe_blob["chosen"]
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, capture_output=True, check=True
    ).stdout.strip()
    metrics = finalize(OUTPUT, EXECUTABLE, chosen, commit,
                       probe_blob["probed"], probe_blob["rejected"],
                       {args.model} if args.model else None)
    print(json.dumps({"models": [m["id"] for m in MODELS],
                      "total_cost_usd": metrics["totals"]["total_cost_usd"]},
                     indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
