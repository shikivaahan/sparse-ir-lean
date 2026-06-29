#!/usr/bin/env python3
"""Generate reference-only clingo solutions and verify them with Lean."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from sparseir_harness.reference_solutions import run_reference_gate


def parse_max_problems(value: str) -> int | None:
    if value == "all":
        return None
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("--max-problems must be 'all' or a positive integer")
    return parsed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gate-a-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-problems", type=parse_max_problems, default=None)
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    parser.add_argument("--store-reference-solutions", action="store_true")
    args = parser.parse_args()
    manifest = run_reference_gate(
        args.gate_a_dir,
        args.output,
        args.max_problems,
        args.timeout_seconds,
        args.store_reference_solutions,
    )
    print(json.dumps(manifest, indent=2))
    return 0 if manifest["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
