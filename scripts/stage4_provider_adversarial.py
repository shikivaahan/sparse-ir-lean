#!/usr/bin/env python3
"""Run Stage 4 provider-backed positive and adversarial parser validation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from sparseir_harness.provider_adversarial import run_provider_adversarial


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage4-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--positive-samples-per-feature", type=int, required=True)
    parser.add_argument("--adversarial-samples-per-feature", type=int, required=True)
    parser.add_argument("--seed", type=int, required=True)
    args = parser.parse_args()
    manifest = run_provider_adversarial(
        args.stage4_dir,
        args.output,
        args.model,
        args.positive_samples_per_feature,
        args.adversarial_samples_per_feature,
        args.seed,
    )
    print(json.dumps(manifest, indent=2))
    return 0 if manifest["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
