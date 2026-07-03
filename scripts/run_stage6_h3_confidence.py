#!/usr/bin/env python3
"""Prepare, run, and finalize the Stage 6 H3 confidence elicitation."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from sparseir_harness.stage6_h3_confidence import (
    MODELS,
    finalize,
    prepare,
    run_one_model,
)


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "eval/gates/stage6_h3_confidence"
LADDER = ROOT / "eval/gates/stage6_capability_ladder"
COMPILED = ROOT / "eval/gates/stage2_gate_a_compile_all/compiled_problems.jsonl"
EXECUTABLE = ROOT / ".lake/build/bin/sparse-ir-lean"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("prepare", "run", "finalize"))
    parser.add_argument("--model", default=None,
                        help="comma-separated model IDs to run (default: all)")
    parser.add_argument("--workers", type=int, default=None,
                        help="override worker count for all models")
    args = parser.parse_args()

    if args.phase == "prepare":
        inventory = prepare(LADDER, COMPILED, OUTPUT, EXECUTABLE)
        result = {"inventory": inventory, "models": [m["id"] for m in MODELS]}
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0

    if args.phase == "run":
        selected_ids = set(args.model.split(",")) if args.model else None
        for m in MODELS:
            if selected_ids is not None and m["id"] not in selected_ids:
                continue
            rows = run_one_model(LADDER, OUTPUT, EXECUTABLE, m, workers_override=args.workers)
            print(f"{m['id']}: completed {len(rows)} rows", flush=True)
        # Aggregate into top-level results.jsonl.
        all_rows = []
        for m in MODELS:
            safe = m["id"].replace("/", "__")
            chunk = OUTPUT / "results" / f"{safe}.jsonl"
            if chunk.exists():
                all_rows.extend([json.loads(line) for line in chunk.read_text().splitlines() if line.strip()])
        (OUTPUT / "results.jsonl").write_text(
            "".join(json.dumps(r, sort_keys=True) + "\n" for r in all_rows),
            encoding="utf-8",
        )
        print(f"aggregated: {len(all_rows)} rows", flush=True)
        return 0

    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, capture_output=True, check=True
    ).stdout.strip()
    metrics = finalize(OUTPUT, EXECUTABLE, commit)
    print(json.dumps({
        "models": [m["id"] for m in MODELS],
        "totals": metrics["totals"],
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
