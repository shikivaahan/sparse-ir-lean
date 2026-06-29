#!/usr/bin/env python3
"""Run the Stage 3C stepwise checker-kernel evidence gate."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from sparseir_harness.step_kernel_gate import run_step_gate


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gate-a-dir", type=Path, required=True)
    parser.add_argument("--reference-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, required=True)
    args = parser.parse_args()
    manifest = run_step_gate(args.gate_a_dir, args.reference_dir, args.output, args.seed)
    print(json.dumps(manifest, indent=2))
    return 0 if manifest["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
