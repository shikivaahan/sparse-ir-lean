"""Stage 4 provider trace-syntax feature validation tests."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from sparseir_harness.provider_feature_validation import (
    REQUIRED_FEATURES,
    feature_exemplar,
    validation_status,
)


ROOT = Path(__file__).resolve().parents[1]
EXECUTABLE = ROOT / ".lake" / "build" / "bin" / "sparse-ir-lean"


def test_all_feature_prompt_exemplars_parse_with_lean() -> None:
    for feature in REQUIRED_FEATURES:
        exemplar = feature_exemplar(feature)
        completed = subprocess.run(
            [str(EXECUTABLE)],
            cwd=ROOT,
            input=json.dumps(
                {
                    "protocol_version": "0.1.0",
                    "request_id": feature,
                    "command": "parse_trace",
                    "payload": {"trace": json.dumps(exemplar)},
                }
            ),
            text=True,
            capture_output=True,
            check=True,
        )
        result = json.loads(completed.stdout)["result"]
        assert result["kind"] == "TRACE_PARSED", feature


def test_pass_requires_full_matrix_thresholds() -> None:
    coverage = {feature: 20 for feature in REQUIRED_FEATURES}
    passes = {feature: 16 for feature in REQUIRED_FEATURES}
    assert validation_status(140, 112, 0, coverage, passes) == "pass"
    assert validation_status(140, 0, 0, coverage, {}) == "fail"
    assert validation_status(140, 111, 0, coverage, passes) == "partial"
    assert validation_status(140, 112, 1, coverage, passes) == "partial"


def test_schema_valid_zero_cannot_pass() -> None:
    coverage = {feature: 20 for feature in REQUIRED_FEATURES}
    assert validation_status(140, 0, 0, coverage, {}) == "fail"


def test_exemplars_have_exact_trace_top_level_keys() -> None:
    for feature in REQUIRED_FEATURES:
        assert set(feature_exemplar(feature)) == {"schema_version", "problem_id", "ops"}
