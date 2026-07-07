#!/usr/bin/env python3
"""Regenerate Stage 4 synthetic parser fixtures from Stage 2 Gate A artifacts.

These fixtures are STRUCTURALLY VALID per-puzzle candidate assignments used
ONLY by the Stage 4 parser gate (`trace_parser_gate.run_trace_parser_gate`)
to exercise the full-candidate and stepwise trace generators across grid
sizes. They are not clingo gold, not semantic solutions; see the README at
`eval/gates/stage4_trace_parser/parser_fixtures/README.md`.

Usage:

    set -a; source .env; set +a
    uv run python scripts/make_stage4_parser_fixtures.py \\
      --compiled-problems eval/gates/stage2_gate_a_compile_all/compiled_problems.jsonl \\
      --output eval/gates/stage4_trace_parser/parser_fixtures/parser_fixture_solutions.jsonl
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--compiled-problems",
        type=Path,
        required=True,
        help=(
            "Path to Stage 2 Gate A's compiled_problems.jsonl. The puzzle "
            "surface is real ZebraLogic-derived."
        ),
    )
    p.add_argument(
        "--output",
        type=Path,
        required=True,
        help=(
            "Path to parser_fixture_solutions.jsonl. The output location "
            "must be Stage 4-owned (e.g. "
            "eval/gates/stage4_trace_parser/parser_fixtures/). The "
            "filename is fixed: parser_fixture_solutions.jsonl."
        ),
    )
    args = p.parse_args()

    rows_out: list[dict[str, object]] = []
    for line in args.compiled_problems.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        cp = json.loads(line)
        categories = cp["compiled_categories"]
        houses = cp["houses"]
        solution: dict[str, dict[str, str]] = {}
        for cat in categories:
            values = cat["values"]
            assignments: dict[str, str] = {}
            for h in range(1, houses + 1):
                # Use modulo to cycle if fewer values than houses.
                assignments[str(h)] = values[(h - 1) % len(values)]
            solution[cat["name"]] = assignments
        rows_out.append(
            {
                "candidate": {
                    "schema_version": "0.2",
                    "problem_id": cp["problem_id"],
                    "solution": solution,
                },
                "_meta": {
                    "purpose": "stage4_parser_fixture",
                    "synthetic": True,
                    "semantic_correctness_claimed": False,
                    "clingo_used": False,
                    "source_artifact": str(args.compiled_problems),
                    "intended_consumer": "stage4_trace_parser_gate_only",
                },
            }
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as handle:
        for r in rows_out:
            handle.write(json.dumps(r) + "\n")
    print(f"wrote {len(rows_out)} synthetic Stage 4 parser fixtures to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
