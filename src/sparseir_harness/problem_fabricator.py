"""Re-derive ``problem.json`` rows from committed compiled-puzzle artifacts.

The committed ``eval/gates/stage2_gate_a_compile_all/compiled_problems.jsonl``
artifact is the trusted Stage 2A output; the public checkout intentionally
omits both ``data/zebralogic/source.json`` (external source) and the
regenerated ``ingested_problems/`` directory. To run the stepwise G1 gate
without silently downgrading the corpus, this module reconstructs the
``schema_version 0.2`` problem rows that the Lean compiler accepts.

The fabricator is only a reconstruction helper. It never reads
``expect.source_solution`` and never uses any solution hint to derive the
re-emitted puzzle.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "0.2"
DOMAIN = "zebra"


def _attribute(raw: dict[str, Any]) -> dict[str, str]:
    return {"cat": raw["cat"], "val": raw["val"]}


def _clue(compiled: dict[str, Any]) -> dict[str, Any]:
    clue_type = compiled["type"]
    if clue_type in {"found_at", "not_at"}:
        return {
            "id": compiled["id"],
            "type": clue_type,
            "cat": compiled["cat"],
            "val": compiled["val"],
            "house": int(compiled["house"]),
        }
    return {
        "id": compiled["id"],
        "type": clue_type,
        "a": _attribute(compiled["a"]),
        "b": _attribute(compiled["b"]),
    }


def fabric_to_problem(compiled: dict[str, Any]) -> dict[str, Any]:
    """Reconstruct a schema-version-0.2 ``problem.json`` from a compiled row."""
    categories: dict[str, list[str]] = {
        category["name"]: list(category["values"])
        for category in compiled["compiled_categories"]
    }
    houses = int(compiled["houses"])
    expected_categories = len(compiled["compiled_categories"])
    clues = [_clue(compiled_clue) for compiled_clue in compiled["compiled_clues"]]
    problem_id = compiled["problem_id"]
    return {
        "schema_version": SCHEMA_VERSION,
        "domain": DOMAIN,
        "id": problem_id,
        "source": {
            "dataset": "zebralogic",
            "split": "test",
            "external_id": compiled["external_id"],
            "grid": compiled["grid"],
        },
        "size": {"houses": houses, "categories": expected_categories},
        "categories": categories,
        "clues": clues,
    }


def fabric_corpus(
    compiled_path: Path,
    output_dir: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Re-emit one ``problem.json`` per compiled row into ``output_dir``.

    Returns the parsed problem list and a provenance record (sha256, counts,
    generator identity) for the gate's ``manifest.json``.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    for stale in output_dir.glob("*.problem.json"):
        stale.unlink()
    raw_text = compiled_path.read_bytes()
    sha256 = hashlib.sha256(raw_text).hexdigest()
    rows = [json.loads(line) for line in raw_text.decode("utf-8").splitlines() if line]
    problems: list[dict[str, Any]] = []
    for row in rows:
        problem = fabric_to_problem(row)
        external_id = row["external_id"]
        path = output_dir / f"{external_id}.problem.json"
        path.write_text(json.dumps(problem, indent=2) + "\n", encoding="utf-8")
        problems.append(problem)
    provenance = {
        "compiled_path": str(compiled_path),
        "compiled_sha256": sha256,
        "compiled_rows": len(rows),
        "fabricated_rows": len(problems),
        "fabricator_version": "stage3-stepwise-g1-v1",
    }
    return problems, provenance


def load_problems_from_dir(problem_dir: Path) -> list[dict[str, Any]]:
    return [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(problem_dir.glob("*.problem.json"))
    ]