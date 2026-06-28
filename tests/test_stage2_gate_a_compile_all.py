from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

from sparseir_harness.zebralogic_ingest import convert_source_record, load_official_source


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "stage2_gate_a_compile_all.py"
sys.path.insert(0, str(SCRIPT.parent))
SPEC = importlib.util.spec_from_file_location("stage2_gate_a_compile_all", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
gate_a = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = gate_a
SPEC.loader.exec_module(gate_a)
REAL_RECORDS, _SOURCE_ROOTS = load_official_source(ROOT)


def _compiled(request: dict[str, Any]) -> dict[str, Any]:
    problem = json.loads(request["payload"]["problem"])
    categories = [
        {"name": name, "values": values} for name, values in problem["categories"].items()
    ]
    return {
        "protocol_version": "0.1.0",
        "request_id": request["request_id"],
        "result": {
            "kind": "COMPILED",
            "compiled": {
                "problem_id": problem["id"],
                "houses": problem["size"]["houses"],
                "categories": len(categories),
                "compiled_categories": categories,
                "compiled_clues": problem["clues"],
            },
        },
    }


def _run(
    tmp_path: Path,
    records: int,
    invoke_fn: Any = _compiled,
) -> tuple[int, dict[str, Any], Path]:
    output = tmp_path / "out"
    exit_code, manifest = gate_a.run_gate(
        tmp_path,
        output,
        "gate-a-test",
        invoke_fn=invoke_fn,
        canonical_records=REAL_RECORDS[:records],
        source_roots=["data/zebralogic"],
    )
    return exit_code, manifest, output


def test_gate_fails_when_zero_problems_are_discovered_and_writes_artifacts(
    tmp_path: Path,
) -> None:
    exit_code, manifest, output = _run(tmp_path, 0)

    assert exit_code == 1
    assert manifest["status"] == "fail"
    assert manifest["total_ingested"] == 0
    assert manifest["failures"][0]["error_code"] == "no_problems_discovered"
    assert {path.name for path in output.iterdir()} >= {
        "manifest.json",
        "source_manifest.jsonl",
        "results.jsonl",
        "compiled_problems.jsonl",
        "raw_problem_index.md",
        "compiled_problem_index.md",
        "summary.md",
    }


def test_gate_fails_when_only_three_logical_problems_are_available(tmp_path: Path) -> None:
    exit_code, manifest, _output = _run(tmp_path, 3)

    assert exit_code == 1
    assert manifest["total_ingested"] == 3
    assert manifest["total_compiled"] == 3
    assert manifest["failures"] == [
        {
            "error_code": "smoke_coverage_only",
            "error_path": None,
            "error_message": (
                "only 3 unique problems are available; this is smoke coverage "
                "and not enough for Stage 2 Gate A"
            ),
        }
    ]


def test_gate_records_provenance_and_writes_human_reviewable_compiled_views(
    tmp_path: Path,
) -> None:
    exit_code, manifest, output = _run(tmp_path, 4)
    source_rows = [
        json.loads(line)
        for line in (output / "source_manifest.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    compiled_rows = [
        json.loads(line)
        for line in (output / "compiled_problems.jsonl").read_text(encoding="utf-8").splitlines()
    ]

    assert exit_code == 0
    assert manifest["status"] == "pass"
    assert manifest["total_source_records_seen"] == 4
    assert manifest["total_ingested"] == manifest["total_compiled"] == 4
    assert all(row["dataset"] == "zebralogic" for row in source_rows)
    assert all(row["source_row_index"] is not None for row in source_rows)
    assert all(len(row["source_sha256"]) == 64 for row in source_rows)
    assert all(row["ingested_problem_path"].endswith(".problem.json") for row in source_rows)
    assert all(row["compiled_categories"] for row in compiled_rows)
    assert all(row["compiled_clues"] for row in compiled_rows)
    raw_index = (output / "raw_problem_index.md").read_text(encoding="utf-8")
    compiled_index = (output / "compiled_problem_index.md").read_text(encoding="utf-8")
    assert REAL_RECORDS[0].problem_id in raw_index
    assert REAL_RECORDS[0].problem_id in compiled_index
    assert "c1:" in raw_index
    assert "c1:" in compiled_index


def test_gate_deduplicates_converted_fixture_by_external_id_and_grid(tmp_path: Path) -> None:
    fixture = tmp_path / "tests/problems/duplicate.problem.json"
    fixture.parent.mkdir(parents=True)
    fixture.write_text(
        json.dumps(convert_source_record(REAL_RECORDS[0])), encoding="utf-8"
    )

    exit_code, manifest, output = _run(tmp_path, 4)
    source_rows = [
        json.loads(line)
        for line in (output / "source_manifest.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    duplicates = [row for row in source_rows if row["status"] == "skipped"]

    assert exit_code == 0
    assert manifest["total_source_records_seen"] == 5
    assert manifest["total_ingested"] == 4
    assert manifest["total_duplicates"] == 1
    assert manifest["total_skipped"] == 1
    assert len(duplicates) == 1
    assert "duplicate stable key" in duplicates[0]["skip_reason"]


def test_gate_records_compile_failure_fields(tmp_path: Path) -> None:
    rejected_id = REAL_RECORDS[0].problem_id

    def reject_one(request: dict[str, Any]) -> dict[str, Any]:
        problem = json.loads(request["payload"]["problem"])
        if problem["id"] != rejected_id:
            return _compiled(request)
        return {
            "protocol_version": "0.1.0",
            "request_id": request["request_id"],
            "result": {
                "kind": "STATIC_ERROR",
                "error_code": "unknown_value",
                "error_path": "$.clues[0].a.val",
                "message": "value is not declared",
            },
        }

    exit_code, manifest, output = _run(tmp_path, 4, reject_one)
    results = [
        json.loads(line)
        for line in (output / "results.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    failure = next(row for row in results if row["status"] == "failed")

    assert exit_code == 1
    assert manifest["total_failed"] == 1
    assert failure["error_code"] == "unknown_value"
    assert failure["error_path"] == "$.clues[0].a.val"
    assert failure["error_message"] == "value is not declared"


def test_pinned_source_conversion_covers_every_official_record_and_clue() -> None:
    converted = [convert_source_record(record) for record in REAL_RECORDS]

    assert len(converted) == 1000
    assert sum(len(problem["clues"]) for problem in converted) == 10_388
    assert {problem["source"]["grid"] for problem in converted} == {
        f"{houses}x{categories}"
        for houses in range(2, 7)
        for categories in range(2, 7)
    }
