#!/usr/bin/env python3
"""Run the standalone Stage 6 Mode-0 H2/H3 task.

Inspect integration is deliberately skipped here: the direct runner keeps raw
OpenRouter responses and invokes the same Lean subprocess with less glue.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path

from sparseir_harness.stage6_mode0 import DEFAULT_MODEL, run_evaluation


ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--problem-dir",
        type=Path,
        default=ROOT / "eval/gates/stage2_gate_a_compile_all/ingested_problems",
    )
    parser.add_argument(
        "--output", type=Path, default=ROOT / "eval/gates/stage6_mode0_h2_h3"
    )
    parser.add_argument(
        "--executable", type=Path, default=ROOT / ".lake/build/bin/sparse-ir-lean"
    )
    parser.add_argument("--n", type=int, required=True)
    parser.add_argument("--seed", type=int, default=20260630)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--model", default=os.environ.get("STAGE6_MODEL", DEFAULT_MODEL))
    args = parser.parse_args()

    if not os.environ.get("OPENROUTER_API_KEY"):
        parser.error("OPENROUTER_API_KEY is not set; refusing to start provider evaluation")
    git_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, capture_output=True, check=True
    ).stdout.strip()
    manifest = run_evaluation(
        args.problem_dir,
        args.output,
        args.executable,
        n=args.n,
        seed=args.seed,
        model=args.model,
        git_commit=git_commit,
        workers=args.workers,
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
