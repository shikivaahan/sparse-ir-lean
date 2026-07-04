#!/usr/bin/env python3
"""Diagnose and rerun Stage 4 provider trace-shape validation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from sparseir_harness.provider_diagnosis import run_provider_diagnosis


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage4-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--samples", type=int, required=True)
    args = parser.parse_args()
    manifest = run_provider_diagnosis(
        args.stage4_dir, args.output, args.model, args.samples
    )
    print(json.dumps(manifest, indent=2))
    return 0 if manifest["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
