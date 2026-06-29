#!/usr/bin/env python3
"""Run the Stage 4 JSON trace-parser evidence gate."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from sparseir_harness.trace_parser_gate import run_trace_parser_gate


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gate-a-dir", type=Path, required=True)
    parser.add_argument("--reference-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, required=True)
    args = parser.parse_args()
    manifest = run_trace_parser_gate(
        args.gate_a_dir,
        args.reference_dir,
        args.output,
        args.seed,
        provider_validate=bool(os.environ.get("OPENROUTER_API_KEY")),
        provider_model=os.environ.get("STAGE4_PROVIDER_MODEL", "deepseek/deepseek-v4-flash"),
    )
    print(json.dumps(manifest, indent=2))
    return 0 if manifest["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
