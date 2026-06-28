"""Focused non-provider tests for the Stage 2 Gate C pipeline."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sparseir_harness.stage2_gate_c import (
    BASE_EXTERNAL_IDS,
    GATE_RELATIVE_PATH,
    REQUIRED_TASK_KINDS,
    classify_provider_output,
    extract_json_object,
    generate_dataset,
    initialize_artifacts,
    record_provider_result,
)


ROOT = Path(__file__).resolve().parents[1]


def _sample() -> dict[str, Any]:
    return {
        "sample_id": "gate-c-2x2-valid_reemit_problem",
        "task_kind": "valid_reemit_problem",
        "source_problem_id": "zl_lgp-test-2x2-33",
        "source_grid": "2x2",
    }


def _response(request: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    return {
        "protocol_version": "0.1.0",
        "request_id": request["request_id"],
        "result": result,
    }


def _prepare_gate_a(tmp_path: Path) -> None:
    source_manifest = tmp_path / "eval/gates/stage2_gate_a_compile_all/source_manifest.jsonl"
    source_manifest.parent.mkdir(parents=True)
    rows = []
    fixtures = {
        "lgp-test-2x2-33": ROOT / "tests/problems/lgp-test-2x2-33.problem.json",
        "lgp-test-4x4-27": ROOT / "tests/problems/lgp-test-4x4-27.problem.json",
        "lgp-test-6x6-5": ROOT / "tests/problems/lgp-test-6x6-5.problem.json",
    }
    for external_id in BASE_EXTERNAL_IDS:
        relative = f"gate-a/{external_id}.problem.json"
        destination = tmp_path / relative
        destination.parent.mkdir(exist_ok=True)
        problem = json.loads(fixtures[external_id].read_text(encoding="utf-8"))
        destination.write_text(json.dumps(problem), encoding="utf-8")
        rows.append(
            {
                "external_id": external_id,
                "status": "ingested",
                "ingested_problem_path": relative,
            }
        )
    source_manifest.write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
    )


def test_dataset_generation_writes_30_samples_and_all_task_kinds(tmp_path: Path) -> None:
    _prepare_gate_a(tmp_path)
    destination = tmp_path / "eval/datasets/stage2_gate_c_provider_static.jsonl"

    rows = generate_dataset(tmp_path, destination)

    assert destination.is_file()
    assert len(rows) == 30
    assert {row["task_kind"] for row in rows} == set(REQUIRED_TASK_KINDS)
    assert {row["source_grid"] for row in rows} == {"2x2", "4x4", "6x6"}
    required_fields = {
        "sample_id",
        "source_problem_id",
        "source_external_id",
        "source_grid",
        "source_problem_path",
        "task_kind",
        "prompt",
        "expected_behavior",
        "target_error_family_or_null",
        "metadata",
    }
    assert all(required_fields <= row.keys() for row in rows)


def test_extracts_exact_json_object() -> None:
    extraction = extract_json_object('{"schema_version":"0.2"}')

    assert extraction.status == "exact_json"
    assert extraction.value == {"schema_version": "0.2"}


def test_extracts_fenced_json_without_repairing_it() -> None:
    extraction = extract_json_object('Here it is:\n```json\n{"domain":"zebra"}\n```\nThanks')

    assert extraction.status == "fenced_json"
    assert extraction.value == {"domain": "zebra"}


def test_extracts_first_embedded_json_object() -> None:
    extraction = extract_json_object('candidate follows {"domain":"zebra"} trailing prose')

    assert extraction.status == "embedded_json"
    assert extraction.value == {"domain": "zebra"}


def test_invalid_non_json_is_still_passed_to_lean_and_classified() -> None:
    observed: list[dict[str, Any]] = []

    def invoke(request: dict[str, Any]) -> dict[str, Any]:
        observed.append(request)
        return _response(
            request,
            {
                "kind": "STATIC_ERROR",
                "error_code": "invalid_json",
                "error_path": "$",
                "message": "expected JSON",
            },
        )

    extraction, classification = classify_provider_output(_sample(), "not JSON", invoke)

    assert extraction.status == "not_json"
    assert observed[0]["payload"]["problem"] == "not JSON"
    assert classification["classification"] == "provider_output_not_json"
    assert classification["lean_error_code"] == "invalid_json"


def test_lean_classification_wrapper_parses_compiled() -> None:
    def invoke(request: dict[str, Any]) -> dict[str, Any]:
        return _response(
            request, {"kind": "COMPILED", "compiled": {"problem_id": "provider-id"}}
        )

    _extraction, classification = classify_provider_output(_sample(), '{"id":"x"}', invoke)

    assert classification["lean_protocol_kind"] == "COMPILED"
    assert classification["classification"] == "compiled"
    assert classification["compiled_problem_id_or_null"] == "provider-id"


def test_lean_classification_wrapper_parses_static_error_fields() -> None:
    def invoke(request: dict[str, Any]) -> dict[str, Any]:
        return _response(
            request,
            {
                "kind": "STATIC_ERROR",
                "error_code": "unknown_category",
                "error_path": "$.clues[0].a.cat",
                "message": "unknown category 'GhostCategory'",
            },
        )

    _extraction, classification = classify_provider_output(_sample(), '{"id":"x"}', invoke)

    assert classification["lean_protocol_kind"] == "STATIC_ERROR"
    assert classification["classification"] == "static_error"
    assert classification["lean_error_code"] == "unknown_category"
    assert classification["lean_error_path"] == "$.clues[0].a.cat"
    assert classification["lean_error_message"] == "unknown category 'GhostCategory'"


def test_artifact_writing_preserves_raw_extracted_and_diagnostics(tmp_path: Path) -> None:
    dataset = [{**_sample(), "expected_behavior": "compile", "prompt": "emit JSON"}]
    initialize_artifacts(tmp_path, dataset)

    def invoke(request: dict[str, Any]) -> dict[str, Any]:
        return _response(
            request,
            {
                "kind": "STATIC_ERROR",
                "error_code": "invalid_schema",
                "error_path": "$.schema_version",
                "message": "schema_version is required",
            },
        )

    record_provider_result(tmp_path, dataset, _sample(), "```json\n{\"id\":\"x\"}\n```", invoke)

    gate_dir = tmp_path / GATE_RELATIVE_PATH
    provider = json.loads((gate_dir / "provider_outputs.jsonl").read_text())
    classification = json.loads((gate_dir / "classifications.jsonl").read_text())
    assert (tmp_path / provider["raw_output_path"]).read_text() == '```json\n{"id":"x"}\n```'
    assert (tmp_path / provider["extracted_json_path"]).is_file()
    assert classification["lean_error_code"] == "invalid_schema"
    assert (gate_dir / "manifest.json").is_file()
    assert (gate_dir / "dataset_index.md").is_file()
    assert (gate_dir / "summary.md").is_file()
