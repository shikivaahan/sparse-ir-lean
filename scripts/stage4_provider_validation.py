#!/usr/bin/env python3
"""Run Stage 4 provider validation across required trace syntax features."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from sparseir_harness.provider_feature_validation import run_feature_validation


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage4-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--samples-per-feature", type=int, required=True)
    args = parser.parse_args()
    manifest = run_feature_validation(
        args.stage4_dir, args.output, args.model, args.samples_per_feature
    )
    print(json.dumps(manifest, indent=2))
    return 0 if manifest["provider_validation_status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
