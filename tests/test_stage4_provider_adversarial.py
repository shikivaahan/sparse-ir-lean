"""Stage 4 provider positive/adversarial parser validation tests."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from sparseir_harness.provider_adversarial import (
    ADVERSARIAL_EXPECTATIONS,
    POSITIVE_BUCKETS,
    bucket_exemplar,
    gate_status,
    run_provider_adversarial,
    score_sample,
)
from sparseir_harness.provider_diagnosis import extract_top_level_json, unexpected_field_paths


ROOT = Path(__file__).resolve().parents[1]
EXECUTABLE = ROOT / ".lake" / "build" / "bin" / "sparse-ir-lean"


def _lean_result(value: dict[str, Any]) -> dict[str, Any]:
    completed = subprocess.run(
        [str(EXECUTABLE)],
        cwd=ROOT,
        input=json.dumps(
            {
                "protocol_version": "0.1.0",
                "request_id": "adversarial-test",
                "command": "parse_trace",
                "payload": {"trace": json.dumps(value)},
            }
        ),
        text=True,
        capture_output=True,
        check=True,
    )
    return json.loads(completed.stdout)["result"]


def test_positive_buckets_score_trace_parsed_only() -> None:
    for bucket in POSITIVE_BUCKETS:
        exemplar = bucket_exemplar(bucket, "zl_test")
        result = _lean_result(exemplar)
        score = score_sample(False, bucket, True, "top_level_object", result)
        assert result["kind"] == "TRACE_PARSED"
        assert score["passed"] is True


def test_adversarial_buckets_score_expected_rejection_as_pass() -> None:
    for bucket, (expected_code, expected_path) in ADVERSARIAL_EXPECTATIONS.items():
        exemplar = bucket_exemplar(bucket, "zl_test")
        extraction = extract_top_level_json(json.dumps(exemplar))
        result = _lean_result(exemplar)
        score = score_sample(True, bucket, True, extraction["status"], result)
        assert score["passed"] is True, bucket
        assert score["expected_code"] == expected_code
        assert score["expected_path"] == expected_path


def test_model_compliance_is_separate_from_lean_rejection() -> None:
    exemplar = bucket_exemplar("missing_ops", "zl_test")
    result = _lean_result(exemplar)
    compliant = score_sample(True, "missing_ops", True, "top_level_object", result)
    noncompliant = score_sample(True, "missing_ops", False, "top_level_object", result)
    assert compliant["actual_code"] == "missing_ops"
    assert compliant["passed"] is True
    assert noncompliant["passed"] is False


def test_wrapper_and_unexpected_fields_have_separate_diagnostics() -> None:
    wrapper = bucket_exemplar("wrapper_object", "zl_test")
    extraction = extract_top_level_json(json.dumps(wrapper))
    assert extraction["status"] == "unexpected_wrapper_object"
    assert "$.trace" in unexpected_field_paths(wrapper)
    extra = bucket_exemplar("unexpected_top_level_field", "zl_test")
    assert unexpected_field_paths(extra) == ["$.extra"]


def test_zero_schema_valid_cannot_pass() -> None:
    coverage = {bucket: 20 for bucket in POSITIVE_BUCKETS}
    coverage.update({bucket: 10 for bucket in ADVERSARIAL_EXPECTATIONS})
    assert gate_status(140, 0, 120, 0, 0, coverage, {}) == "fail"


def test_gate_writes_all_artifacts_and_raw_lean_outputs(tmp_path: Path) -> None:
    output = tmp_path / "provider-adversarial"

    def copy_exemplar(messages: list[dict[str, str]], _model: str) -> str:
        return messages[0]["content"].split("Exemplar: ", 1)[1]

    manifest = run_provider_adversarial(
        ROOT / "eval" / "gates" / "stage4_trace_parser",
        output,
        "deepseek/deepseek-v4-flash",
        1,
        1,
        20260629,
        provider_call=copy_exemplar,
        require_access=False,
    )
    assert manifest["total_samples"] == 19
    assert manifest["trace_parsed"] == 7
    assert manifest["expected_rejections"] == 12
    for name in (
        "manifest.json",
        "feature_matrix.json",
        "prompts.jsonl",
        "raw_outputs.jsonl",
        "extracted_json.jsonl",
        "parse_results.jsonl",
        "lean_outputs.jsonl",
        "unexpected_fields.jsonl",
        "failures.jsonl",
        "examples.md",
        "summary.md",
    ):
        assert (output / name).is_file()
    lean_rows = (output / "lean_outputs.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lean_rows) == 19
    assert all("raw_lean_output" in json.loads(row) for row in lean_rows)
    assert len(list((output / "trace_json").glob("*.trace.json"))) == 19


def test_inspect_eval_includes_lean_raw_outputs() -> None:
    source = (ROOT / "evals" / "stage4_provider_adversarial.py").read_text(
        encoding="utf-8"
    )
    assert '_rows("lean_outputs.jsonl")' in source
    assert '"lean_raw_output": lean["raw_lean_output"]' in source
    assert '"raw_lean_output": metadata["raw_lean_output"]' in source
