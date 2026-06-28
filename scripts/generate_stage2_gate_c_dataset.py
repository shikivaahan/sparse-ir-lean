#!/usr/bin/env python3
"""Generate the explicit Stage 2 Gate C Inspect dataset from Gate A outputs."""

from pathlib import Path

from sparseir_harness.stage2_gate_c import DATASET_RELATIVE_PATH, generate_dataset


ROOT = Path(__file__).resolve().parents[1]


if __name__ == "__main__":
    rows = generate_dataset(ROOT)
    print(f"wrote {len(rows)} samples to {DATASET_RELATIVE_PATH}")
