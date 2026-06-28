from __future__ import annotations

import importlib.util
import json
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

from sparseir_harness.zebralogic_ingest import (
    SourceRecord,
    convert_source_record,
    load_official_source,
)


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/audit_stage2_gate_a_dataset.py"
sys.path.insert(0, str(SCRIPT.parent))
SPEC = importlib.util.spec_from_file_location("audit_stage2_gate_a_dataset", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
audit = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = audit
SPEC.loader.exec_module(audit)
RECORDS, _ROOTS = load_official_source(ROOT)


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8"
    )


def _source_row(record: SourceRecord, problem_path: Path) -> dict[str, Any]:
    return {
        "problem_id": record.problem_id,
        "dataset": "zebralogic",
        "external_id": record.external_id,
        "split": record.split,
        "grid": record.grid,
        "source_file": record.source_file,
        "source_row_index": record.source_row_index,
        "source_record_id": record.source_record_id,
        "source_sha256": record.source_sha256,
        "source_file_sha256": record.source_file_sha256,
        "upstream_url": record.upstream_url,
        "ingested_problem_path": problem_path.as_posix(),
        "status": "ingested",
        "skip_reason": None,
    }


def _make_gate(tmp_path: Path, record: SourceRecord) -> tuple[Path, dict[str, Any]]:
    gate = tmp_path / "gate"
    problems = gate / "ingested_problems"
    problems.mkdir(parents=True)
    problem = convert_source_record(record)
    problem_path = problems / f"{record.external_id}.problem.json"
    problem_path.write_text(json.dumps(problem), encoding="utf-8")
    source = _source_row(record, problem_path)
    result = {
        "path": problem_path.as_posix(),
        "problem_id": record.problem_id,
        "external_id": record.external_id,
        "split": record.split,
        "grid": record.grid,
        "status": "compiled",
        "protocol_kind": "COMPILED",
        "error_code": None,
        "error_path": None,
        "error_message": None,
    }
    compiled = {
        "problem_id": record.problem_id,
        "external_id": record.external_id,
        "grid": record.grid,
        "houses": problem["size"]["houses"],
        "categories": len(problem["categories"]),
        "compiled_categories": [
            {"name": name, "values": values}
            for name, values in sorted(problem["categories"].items())
        ],
        "compiled_clues": deepcopy(problem["clues"]),
        "source_problem_path": problem_path.as_posix(),
        "source_sha256": record.source_sha256,
    }
    (gate / "manifest.json").write_text(
        json.dumps(
            {
                "gate": "stage2_gate_a_compile_all",
                "status": "pass",
                "total_source_records_seen": 1,
                "total_ingested": 1,
                "total_compiled": 1,
                "total_failed": 0,
                "total_skipped": 0,
                "failures": [],
            }
        ),
        encoding="utf-8",
    )
    _write_jsonl(gate / "source_manifest.jsonl", [source])
    _write_jsonl(gate / "results.jsonl", [result])
    _write_jsonl(gate / "compiled_problems.jsonl", [compiled])
    examples = ", ".join(f"{clue['id']}:{clue['type']}" for clue in problem["clues"][:3])
    (gate / "raw_problem_index.md").write_text(
        f"| `{record.problem_id}` | {record.grid} | `{record.source_file}` | "
        f"`{problem_path.as_posix()}` | {examples} |\n",
        encoding="utf-8",
    )
    (gate / "compiled_problem_index.md").write_text(
        f"| `{record.problem_id}` | {record.grid} | {problem['size']['houses']} | "
        f"{len(problem['categories'])} | {len(problem['clues'])} | {examples} |\n",
        encoding="utf-8",
    )
    return gate, problem


def _run(tmp_path: Path, gate: Path, record: SourceRecord) -> tuple[int, dict[str, Any], list[dict[str, Any]]]:
    output = tmp_path / "audit"
    exit_code, manifest = audit.run_audit(
        ROOT, gate, output, "audit-test", expected_records=[record]
    )
    findings = [
        json.loads(line)
        for line in (output / "findings.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    return exit_code, manifest, findings


def _field_names(findings: list[dict[str, Any]]) -> set[str]:
    return {finding["field"] for finding in findings}


def test_missing_source_row_causes_audit_failure(tmp_path: Path) -> None:
    record = RECORDS[0]
    gate, _problem = _make_gate(tmp_path, record)
    _write_jsonl(gate / "source_manifest.jsonl", [])

    exit_code, manifest, findings = _run(tmp_path, gate, record)

    assert exit_code == 1
    assert manifest["status"] == "fail"
    assert "missing_eval_problem" in _field_names(findings)


def test_source_ingested_category_mismatch_causes_audit_failure(tmp_path: Path) -> None:
    record = RECORDS[0]
    gate, problem = _make_gate(tmp_path, record)
    first_category = next(iter(problem["categories"]))
    problem["categories"][first_category][0] = "not-from-source"
    next((gate / "ingested_problems").glob("*.problem.json")).write_text(
        json.dumps(problem), encoding="utf-8"
    )

    exit_code, _manifest, findings = _run(tmp_path, gate, record)

    assert exit_code == 1
    assert "category_value_mismatch" in _field_names(findings)


def test_source_ingested_clue_mismatch_causes_audit_failure(tmp_path: Path) -> None:
    record = RECORDS[0]
    gate, problem = _make_gate(tmp_path, record)
    clue = problem["clues"][0]
    clue["type"] = "not_at" if clue["type"] == "found_at" else "found_at"
    next((gate / "ingested_problems").glob("*.problem.json")).write_text(
        json.dumps(problem), encoding="utf-8"
    )

    exit_code, _manifest, findings = _run(tmp_path, gate, record)

    assert exit_code == 1
    assert "clue_operand_mismatch" in _field_names(findings)


def test_missing_compiled_row_causes_audit_failure(tmp_path: Path) -> None:
    record = RECORDS[0]
    gate, _problem = _make_gate(tmp_path, record)
    _write_jsonl(gate / "compiled_problems.jsonl", [])

    exit_code, _manifest, findings = _run(tmp_path, gate, record)

    assert exit_code == 1
    assert "compiled_row_missing" in _field_names(findings)


def test_compiled_category_mismatch_causes_audit_failure(tmp_path: Path) -> None:
    record = RECORDS[0]
    gate, _problem = _make_gate(tmp_path, record)
    compiled = audit._read_jsonl(gate / "compiled_problems.jsonl")
    compiled[0]["compiled_categories"][0]["values"][0] = "not-from-raw"
    _write_jsonl(gate / "compiled_problems.jsonl", compiled)

    exit_code, _manifest, findings = _run(tmp_path, gate, record)

    assert exit_code == 1
    assert "compiled_category_mismatch" in _field_names(findings)


def test_compiled_clue_mismatch_causes_audit_failure(tmp_path: Path) -> None:
    record = RECORDS[0]
    gate, _problem = _make_gate(tmp_path, record)
    compiled = audit._read_jsonl(gate / "compiled_problems.jsonl")
    compiled[0]["compiled_clues"][0]["id"] = "wrong-id"
    _write_jsonl(gate / "compiled_problems.jsonl", compiled)

    exit_code, _manifest, findings = _run(tmp_path, gate, record)

    assert exit_code == 1
    assert "compiled_clue_mismatch" in _field_names(findings)


def test_cross_category_duplicate_values_are_valid(tmp_path: Path) -> None:
    record = next(
        record
        for record in RECORDS
        if (
            lambda problem: "Alice" in problem["categories"].get("Name", [])
            and "Alice" in problem["categories"].get("Children", [])
        )(convert_source_record(record))
    )
    gate, _problem = _make_gate(tmp_path, record)

    exit_code, manifest, findings = _run(tmp_path, gate, record)

    assert exit_code == 0
    assert manifest["status"] == "pass"
    assert findings == []


def test_duplicate_logical_problem_detection(tmp_path: Path) -> None:
    record = RECORDS[0]
    gate, problem = _make_gate(tmp_path, record)
    source_rows = audit._read_jsonl(gate / "source_manifest.jsonl")
    duplicate_path = gate / "ingested_problems/duplicate.problem.json"
    duplicate_path.write_text(json.dumps(problem), encoding="utf-8")
    duplicate = deepcopy(source_rows[0])
    duplicate["ingested_problem_path"] = duplicate_path.as_posix()
    _write_jsonl(gate / "source_manifest.jsonl", [source_rows[0], duplicate])

    exit_code, _manifest, findings = _run(tmp_path, gate, record)

    assert exit_code == 1
    assert "duplicate_logical_problem" in _field_names(findings)
