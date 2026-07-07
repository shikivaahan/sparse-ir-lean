#!/usr/bin/env python3
"""Regenerate the Stage 6 capability-ladder metrics.json and summary.md.

Uses the Lean verdicts and per-puzzle cost/token fields already persisted on
each row in ``eval/gates/stage6_capability_ladder/results/``. It does NOT call
the provider, does NOT re-invoke Lean, and does NOT touch git history. The
sole reason this script exists is to keep committed aggregation artifacts in
sync with changes to ``compute_metrics`` (e.g. wall-time provenance).

Usage:
    PYTHONPATH=src python scripts/regenerate_stage6_capability_ladder_metrics.py
"""

from __future__ import annotations

import json
from pathlib import Path

from sparseir_harness.stage6_capability_ladder import regenerate_metrics_from_results


ROOT = Path(__file__).resolve().parents[1]
RUN_DIR = ROOT / "eval/gates/stage6_capability_ladder"
PROBE_PATH = RUN_DIR / "concurrency_probe.json"


def main() -> int:
    if not PROBE_PATH.exists():
        raise SystemExit(
            f"missing {PROBE_PATH}: cannot regenerate summary without probe metadata"
        )
    probe_blob = json.loads(PROBE_PATH.read_text(encoding="utf-8"))
    metrics = regenerate_metrics_from_results(
        RUN_DIR,
        probe_blob["chosen"],
        probe_blob["probed"],
        probe_blob["rejected"],
    )
    ladder = metrics["ladder"]
    print(json.dumps({
        "models": [row["model_id"] for row in ladder],
        "wall_time_status": {row["model_id"]: row["wall_time_status"] for row in ladder},
        "wall_minutes": {row["model_id"]: row["wall_minutes"] for row in ladder},
        "examples_per_minute": {row["model_id"]: row["examples_per_minute"] for row in ladder},
        "total_cost_usd": metrics["totals"]["total_cost_usd"],
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())