#!/usr/bin/env python3
"""Run the Stage 3 stepwise G1 closure gate."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from sparseir_harness.stage3_stepwise_g1 import (
    FUZZ_MIN_COUNT,
    DEFAULT_STATES_PER_PUZZLE,
    DEFAULT_STEPS_PER_STATE,
    run_gate,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiled-path", type=Path, required=True)
    parser.add_argument("--reference-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--fuzz-seed", type=int, required=True)
    parser.add_argument("--fuzz-count", type=int, default=FUZZ_MIN_COUNT)
    parser.add_argument("--states-per-puzzle", type=int, default=DEFAULT_STATES_PER_PUZZLE)
    parser.add_argument("--steps-per-state", type=int, default=DEFAULT_STEPS_PER_STATE)
    parser.add_argument("--clingo-timeout-seconds", type=float, default=30.0)
    args = parser.parse_args()
    manifest = run_gate(
        compiled_path=args.compiled_path,
        reference_dir=args.reference_dir,
        output_dir=args.output,
        seed=args.seed,
        fuzz_seed=args.fuzz_seed,
        fuzz_count=args.fuzz_count,
        states_per_puzzle=args.states_per_puzzle,
        steps_per_state=args.steps_per_state,
        clingo_timeout_seconds=args.clingo_timeout_seconds,
    )
    print(json.dumps(manifest, indent=2))
    return 0 if manifest["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())