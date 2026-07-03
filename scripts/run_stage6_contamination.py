#!/usr/bin/env python3
"""Prepare, run, and finalize the Stage 6 contamination gate."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from sparseir_harness.stage6_contamination import finalize, prepare, run, smoke_health


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "eval/gates/stage6_contamination"
COMPILED = ROOT / "eval/gates/stage2_gate_a_compile_all/compiled_problems.jsonl"
EXECUTABLE = ROOT / ".lake/build/bin/sparse-ir-lean"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("prepare", "smoke", "run", "finalize"))
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--n", type=int)
    args = parser.parse_args()
    if args.phase == "prepare":
        result = {"prepared": len(prepare(COMPILED, OUTPUT, EXECUTABLE, args.n or 40))}
    elif args.phase == "smoke":
        run_dir = OUTPUT / "smoke"
        run(OUTPUT, run_dir, EXECUTABLE, args.workers, args.n or 10)
        healthy, metrics = smoke_health(run_dir)
        result = metrics
        if not healthy:
            print(json.dumps(result, indent=2, sort_keys=True))
            return 1
    elif args.phase == "run":
        result = {"completed": len(run(OUTPUT, OUTPUT, EXECUTABLE, args.workers, args.n))}
    else:
        commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, capture_output=True, check=True).stdout.strip()
        result = finalize(OUTPUT, EXECUTABLE, commit)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
