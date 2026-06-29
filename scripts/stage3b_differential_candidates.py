#!/usr/bin/env python3
"""Run Stage 3B Lean-vs-clingo differential checks on full assignments."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from sparseir_harness.differential_candidates import run_differential_gate


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gate-a-dir", type=Path, required=True)
    parser.add_argument("--reference-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--target-candidates", type=int, required=True)
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    args = parser.parse_args()
    manifest = run_differential_gate(
        args.gate_a_dir,
        args.reference_dir,
        args.output,
        args.seed,
        args.target_candidates,
        args.timeout_seconds,
    )
    print(json.dumps(manifest, indent=2))
    return 0 if manifest["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
