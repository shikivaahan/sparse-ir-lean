"""Stage 4 provider prompt, extraction, diagnosis, and reporting tests."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from sparseir_harness.provider_diagnosis import (
    extract_top_level_json,
    provider_validation_status,
    remove_only_unexpected_fields,
    run_provider_diagnosis,
    score_expected_parser_outcome,
    unexpected_field_paths,
)
from sparseir_harness.trace_parser_gate import TRACE_PROMPT_EXEMPLAR


ROOT = Path(__file__).resolve().parents[1]
EXECUTABLE = ROOT / ".lake" / "build" / "bin" / "sparse-ir-lean"


def _parse_trace(trace: dict[str, Any]) -> dict[str, Any]:
    completed = subprocess.run(
        [str(EXECUTABLE)],
        cwd=ROOT,
        input=json.dumps(
            {
                "protocol_version": "0.1.0",
                "request_id": "provider-diagnosis-test",
                "command": "parse_trace",
                "payload": {"trace": json.dumps(trace)},
            }
        ),
        text=True,
        capture_output=True,
        check=True,
    )
    return json.loads(completed.stdout)["result"]


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def test_every_provider_prompt_exemplar_parses_with_lean() -> None:
    result = _parse_trace(TRACE_PROMPT_EXEMPLAR)
    assert result["kind"] == "TRACE_PARSED"
    assert result["trace_style"] == "full_candidate"


def test_extracted_provider_json_requires_top_level_trace_keys() -> None:
    extraction = extract_top_level_json(json.dumps(TRACE_PROMPT_EXEMPLAR))
    assert extraction["status"] == "top_level_object"
    assert set(extraction["extracted_json"]) == {"schema_version", "problem_id", "ops"}


def test_wrapper_object_is_classified_as_extraction_failure() -> None:
    extraction = extract_top_level_json(json.dumps({"trace": TRACE_PROMPT_EXEMPLAR}))
    assert extraction["status"] == "unexpected_wrapper_object"
    assert extraction["wrapper_fields"] == ["trace"]


def test_extra_fields_are_reported_by_exact_path_and_only_extras_are_removed() -> None:
    trace = json.loads(json.dumps(TRACE_PROMPT_EXEMPLAR))
    trace["metadata"] = {"source": "provider"}
    trace["ops"][0]["type"] = "assign_all"
    trace["ops"][1]["note"] = "done"
    assert unexpected_field_paths(trace) == [
        "$.metadata",
        "$.metadata.source",
        "$.ops[0].type",
        "$.ops[1].note",
    ]
    normalized = remove_only_unexpected_fields(trace)
    assert normalized == TRACE_PROMPT_EXEMPLAR
    assert _parse_trace(normalized)["kind"] == "TRACE_PARSED"


def test_zero_schema_valid_outputs_report_fail() -> None:
    assert provider_validation_status(20, 0) == "fail"
    assert provider_validation_status(20, 19) == "partial"
    assert provider_validation_status(20, 20) == "pass"


def test_scorer_respects_expected_parser_side() -> None:
    rejection = {
        "kind": "REJECT",
        "failure": {"failure_code": "missing_ops", "path": "$.ops"},
    }
    expected_rejection = score_expected_parser_outcome(rejection, "REJECT", "missing_ops")
    expected_valid_trace = score_expected_parser_outcome(rejection, "TRACE_PARSED")
    assert expected_rejection["passed"] is True
    assert expected_valid_trace["passed"] is False


def test_diagnosis_writes_artifacts_and_updates_honest_status(tmp_path: Path) -> None:
    stage4 = tmp_path / "stage4"
    output = stage4 / "provider_diagnosis"
    trace = {
        "schema_version": "0.2",
        "problem_id": "zl_fixture",
        "ops": [
            {"op": "assign_all", "solution": {"Color": {"1": "red"}}},
            {"op": "conclude", "status": "solved"},
        ],
    }
    trace_path = stage4 / "trace_json" / "valid-full-0000.trace.json"
    trace_path.parent.mkdir(parents=True)
    trace_path.write_text(json.dumps(trace), encoding="utf-8")
    _write_jsonl(
        stage4 / "traces.jsonl",
        [
            {
                "trace_id": "valid-full-0000",
                "category": "valid_full_candidate",
                "problem_id": trace["problem_id"],
                "trace_path": str(trace_path),
            }
        ],
    )
    old_output = {
        "schema_version": "0.2",
        "problem_id": trace["problem_id"],
        "operations": [
            {"type": "assign_all", "solution": trace["ops"][0]["solution"]},
            {"type": "conclude", "status": "solved"},
        ],
    }
    _write_jsonl(
        stage4 / "provider_validation.jsonl",
        [
            {
                "sample_id": "provider-trace-00",
                "problem_id": trace["problem_id"],
                "raw_output": json.dumps(old_output),
            }
        ],
    )
    (stage4 / "manifest.json").write_text(
        json.dumps({"status": "pass", "provider_validation": {"status": "complete"}}),
        encoding="utf-8",
    )
    (stage4 / "summary.md").write_text(
        "Stage 4 core parser: PASS\nProvider trace-shape validation: COMPLETE\n",
        encoding="utf-8",
    )

    def valid_provider(messages: list[dict[str, str]], _model: str) -> str:
        payload = json.loads(messages[1]["content"])
        return json.dumps(
            {
                "schema_version": "0.2",
                "problem_id": payload["problem_id"],
                "ops": [
                    {"op": "assign_all", "solution": payload["solution"]},
                    {"op": "conclude", "status": "solved"},
                ],
            }
        )

    manifest = run_provider_diagnosis(
        stage4,
        output,
        "deepseek/deepseek-v4-flash",
        1,
        provider_call=valid_provider,
    )

    assert manifest["status"] == "pass"
    assert manifest["fixed"] is True
    assert manifest["schema_valid"] == 1
    assert manifest["root_cause"] == [
        "prompt_contract_mismatch",
        "provider_added_extra_fields",
        "scorer_bug",
    ]
    for name in (
        "manifest.json",
        "prompts.jsonl",
        "raw_outputs.jsonl",
        "extracted_json.jsonl",
        "parse_results.jsonl",
        "unexpected_fields.jsonl",
        "prompt_exemplar_parse_results.jsonl",
        "normalized_reparse_results.jsonl",
        "root_cause.md",
        "summary.md",
    ):
        assert (output / name).is_file()
    updated = json.loads((stage4 / "manifest.json").read_text(encoding="utf-8"))
    assert updated["provider_validation"]["status"] == "pass"
    normalized_rows = [
        json.loads(line)
        for line in (output / "normalized_reparse_results.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert normalized_rows[0]["result"]["failure"]["failure_code"] == "missing_ops"
