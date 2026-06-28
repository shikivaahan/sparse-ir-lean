"""Stage 2 CLI compile command tests.

The Lean executable is the trusted static compiler. Python only routes the
request and validates that the response conforms to the frozen verifier
protocol. Every status code and dataset-derived mutation comes from real
fixtures in ``tests/problems/``.
"""

from __future__ import annotations

import json
import os
import subprocess
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from jsonschema import Draft202012Validator

from sparseir_harness.dataset import load_zebra_subset


ROOT = Path(__file__).resolve().parents[1]
PROBLEM_FIXTURES = ROOT / "tests" / "problems"
PROBLEM_SCHEMA = json.loads(
    (ROOT / "schemas" / "zebra-problem.schema.json").read_text(encoding="utf-8")
)
PROTOCOL_SCHEMA = json.loads(
    (ROOT / "schemas" / "verifier-protocol.schema.json").read_text(encoding="utf-8")
)
PROTOCOL_VALIDATOR = Draft202012Validator(PROTOCOL_SCHEMA)
PROBLEM_VALIDATOR = Draft202012Validator(PROBLEM_SCHEMA)


def _lake() -> str:
    return os.environ.get("LAKE", "lake")


def _invoke(request: dict[str, Any]) -> dict[str, Any]:
    PROTOCOL_VALIDATOR.validate(request)
    completed = subprocess.run(
        [_lake(), "exe", "sparse-ir-lean"],
        cwd=ROOT,
        input=json.dumps(request),
        text=True,
        capture_output=True,
        check=True,
    )
    response = json.loads(completed.stdout)
    PROTOCOL_VALIDATOR.validate(response)
    return response


def _load_fixture(name: str) -> dict[str, Any]:
    return json.loads((PROBLEM_FIXTURES / name).read_text(encoding="utf-8"))


def _all_gold_fixtures() -> list[dict[str, Any]]:
    return [
        _load_fixture("lgp-test-2x2-33.problem.json"),
        _load_fixture("lgp-test-4x4-27.problem.json"),
        _load_fixture("lgp-test-6x6-5.problem.json"),
    ]


def _compile(problem: dict[str, Any], *, request_id: str = "compile") -> dict[str, Any]:
    PROBLEM_VALIDATOR.validate(problem)
    return _invoke(
        {
            "protocol_version": "0.1.0",
            "request_id": request_id,
            "command": "compile",
            "payload": {"problem": json.dumps(problem)},
        }
    )


@pytest.mark.parametrize("fixture", _all_gold_fixtures(), ids=lambda value: value["id"])
def test_compile_accepts_dataset_derived_gold_fixtures(fixture: dict[str, Any]) -> None:
    response = _compile(fixture, request_id=f"gold-{fixture['id']}")

    assert response["request_id"] == f"gold-{fixture['id']}"
    assert response["result"]["kind"] == "COMPILED"
    assert response["result"]["compiled"]["problem_id"] == fixture["id"]


def test_compile_view_exposes_human_reviewable_stage2_representation() -> None:
    fixture = _load_fixture("lgp-test-4x4-27.problem.json")
    response = _invoke(
        {
            "protocol_version": "0.1.0",
            "request_id": "compiled-view",
            "command": "compile_view",
            "payload": {"problem": json.dumps(fixture)},
        }
    )

    compiled = response["result"]["compiled"]
    assert response["result"]["kind"] == "COMPILED"
    assert compiled["problem_id"] == fixture["id"]
    assert compiled["houses"] == 4
    assert compiled["categories"] == 4
    assert compiled["compiled_categories"]
    assert compiled["compiled_clues"] == fixture["clues"]


def test_compile_accepts_fixture_without_expect_field() -> None:
    fixture = deepcopy(_load_fixture("lgp-test-4x4-27.problem.json"))
    fixture.pop("expect", None)
    PROBLEM_VALIDATOR.validate(fixture)

    response = _compile(fixture, request_id="no-expect")

    assert response["result"]["kind"] == "COMPILED"
    assert response["result"]["compiled"]["problem_id"] == fixture["id"]


def test_compile_preserves_opaque_expect_payload_opaquely() -> None:
    fixture = _load_fixture("lgp-test-4x4-27.problem.json")
    # The Stage 2 compile response never returns `expect`; the opaque field is
    # not a verifier premise. Sanity-check that the compiled problem id matches
    # the envelope and that no expect-derived information leaks into the result.
    response = _compile(fixture, request_id="opaque")

    assert response["result"]["kind"] == "COMPILED"
    assert "expect" not in response["result"]["compiled"]
    assert response["result"]["compiled"] == {"problem_id": fixture["id"]}


def test_compile_rejects_invalid_json_payload() -> None:
    response = _invoke(
        {
            "protocol_version": "0.1.0",
            "request_id": "ij",
            "command": "compile",
            "payload": {"problem": "{"},
        }
    )

    assert response["result"]["kind"] == "STATIC_ERROR"
    assert response["result"]["error_code"] == "invalid_json"


def test_compile_rejects_schema_violation() -> None:
    bad = {"foo": "bar"}
    response = _invoke(
        {
            "protocol_version": "0.1.0",
            "request_id": "schema",
            "command": "compile",
            "payload": {"problem": json.dumps(bad)},
        }
    )

    assert response["result"]["kind"] == "STATIC_ERROR"
    assert response["result"]["error_code"] == "invalid_schema"


def test_compile_rejects_unsupported_schema_version() -> None:
    fixture = _load_fixture("lgp-test-2x2-33.problem.json")
    fixture["schema_version"] = "9"

    response = _compile(fixture, request_id="bad-schema-version")

    assert response["result"]["kind"] == "STATIC_ERROR"
    assert response["result"]["error_code"] == "unsupported_schema_version"


def test_compile_rejects_invalid_domain() -> None:
    fixture = _load_fixture("lgp-test-2x2-33.problem.json")
    fixture["domain"] = "horn"

    response = _compile(fixture, request_id="bad-domain")

    assert response["result"]["kind"] == "STATIC_ERROR"
    assert response["result"]["error_code"] == "invalid_domain"


def test_compile_accepts_house_999_at_parse_then_rejects_as_static() -> None:
    # Stage 1 parses house 999 (positive integer) without complaint.
    # Stage 2 must reject it because 999 is outside 1..N for N=2.
    fixture = _load_fixture("lgp-test-2x2-33.problem.json")
    fixture["clues"][1]["house"] = 999

    response = _compile(fixture, request_id="house-999")

    assert response["result"]["kind"] == "STATIC_ERROR"
    assert response["result"]["error_code"] == "house_out_of_range"


def test_compile_accepts_unknown_category_at_parse_then_rejects_as_static() -> None:
    fixture = _load_fixture("lgp-test-2x2-33.problem.json")
    fixture["clues"][0]["a"]["cat"] = "NotARealCategory"

    response = _compile(fixture, request_id="unknown-cat")

    assert response["result"]["kind"] == "STATIC_ERROR"
    assert response["result"]["error_code"] == "unknown_category"


def test_compile_accepts_unknown_value_at_parse_then_rejects_as_static() -> None:
    fixture = _load_fixture("lgp-test-2x2-33.problem.json")
    fixture["clues"][0]["a"]["val"] = "NotARealValue"

    response = _compile(fixture, request_id="unknown-val")

    assert response["result"]["kind"] == "STATIC_ERROR"
    assert response["result"]["error_code"] == "unknown_value"


def test_compile_accepts_duplicate_clue_id_at_parse_then_rejects_as_static() -> None:
    fixture = _load_fixture("lgp-test-2x2-33.problem.json")
    fixture["clues"][1]["id"] = fixture["clues"][0]["id"]

    response = _compile(fixture, request_id="dup-clue")

    assert response["result"]["kind"] == "STATIC_ERROR"
    assert response["result"]["error_code"] == "duplicate_clue_id"


def test_compile_accepts_duplicate_value_at_parse_then_rejects_as_static() -> None:
    fixture = _load_fixture("lgp-test-2x2-33.problem.json")
    fixture["categories"]["Name"] = ["Eric", "Eric"]

    response = _compile(fixture, request_id="dup-val")

    assert response["result"]["kind"] == "STATIC_ERROR"
    assert response["result"]["error_code"] == "duplicate_value"


def test_compile_accepts_size_mismatch_at_parse_then_rejects_as_static() -> None:
    fixture = _load_fixture("lgp-test-4x4-27.problem.json")
    fixture["size"]["categories"] = 1  # declared 1, actual 4

    response = _compile(fixture, request_id="size-mismatch-parse")

    assert response["result"]["kind"] == "STATIC_ERROR"
    assert response["result"]["error_code"] == "size_mismatch"


def test_compile_rejects_size_mismatch() -> None:
    fixture = _load_fixture("lgp-test-4x4-27.problem.json")
    fixture["size"]["categories"] = 1  # declared 1, actual 4

    response = _compile(fixture, request_id="size-mismatch")

    assert response["result"]["kind"] == "STATIC_ERROR"
    assert response["result"]["error_code"] == "size_mismatch"


def test_compile_rejects_category_size_mismatch() -> None:
    fixture = _load_fixture("lgp-test-4x4-27.problem.json")
    fixture["categories"]["Name"] = fixture["categories"]["Name"][:3]  # 3 of 4

    response = _compile(fixture, request_id="category-size")

    assert response["result"]["kind"] == "STATIC_ERROR"
    assert response["result"]["error_code"] == "category_size_mismatch"


def test_compile_rejects_duplicate_value() -> None:
    fixture = _load_fixture("lgp-test-2x2-33.problem.json")
    fixture["categories"]["Name"] = ["Eric", "Eric"]

    response = _compile(fixture, request_id="duplicate-value")

    assert response["result"]["kind"] == "STATIC_ERROR"
    assert response["result"]["error_code"] == "duplicate_value"


def test_compile_rejects_unknown_category() -> None:
    fixture = _load_fixture("lgp-test-2x2-33.problem.json")
    fixture["clues"][0]["a"]["cat"] = "Undeclared"

    response = _compile(fixture, request_id="unknown-category")

    assert response["result"]["kind"] == "STATIC_ERROR"
    assert response["result"]["error_code"] == "unknown_category"


def test_compile_rejects_unknown_value() -> None:
    fixture = _load_fixture("lgp-test-2x2-33.problem.json")
    fixture["clues"][0]["a"]["val"] = "Missing"

    response = _compile(fixture, request_id="unknown-value")

    assert response["result"]["kind"] == "STATIC_ERROR"
    assert response["result"]["error_code"] == "unknown_value"
    assert response["result"]["error_path"] == "$.clues[0].a.val"


def test_compile_rejects_house_out_of_range() -> None:
    fixture = _load_fixture("lgp-test-2x2-33.problem.json")
    # house 99 is one-based and positive (parser accepts) but exceeds N=2.
    fixture["clues"][1]["house"] = 99

    response = _compile(fixture, request_id="house-out-of-range")

    assert response["result"]["kind"] == "STATIC_ERROR"
    assert response["result"]["error_code"] == "house_out_of_range"


def test_compile_rejects_duplicate_clue_id() -> None:
    fixture = _load_fixture("lgp-test-2x2-33.problem.json")
    fixture["clues"][1]["id"] = fixture["clues"][0]["id"]

    response = _compile(fixture, request_id="duplicate-clue-id")

    assert response["result"]["kind"] == "STATIC_ERROR"
    assert response["result"]["error_code"] == "duplicate_clue_id"


def test_compile_rejects_payload_without_problem_field() -> None:
    response = _invoke(
        {
            "protocol_version": "0.1.0",
            "request_id": "no-problem",
            "command": "compile",
            "payload": {},
        }
    )

    assert response["result"]["kind"] == "STATIC_ERROR"
    assert response["result"]["error_code"] == "invalid_request"


def test_compile_request_validates_against_protocol_schema() -> None:
    # Use the protocol schema directly to ensure the request shape we send is
    # part of the frozen contract, not an implementation accident.
    fixture = _all_gold_fixtures()[0]
    request = {
        "protocol_version": "0.1.0",
        "request_id": "schema-check",
        "command": "compile",
        "payload": {"problem": json.dumps(fixture)},
    }
    PROTOCOL_VALIDATOR.validate(request)


def test_compile_matches_dataset_records_after_parse() -> None:
    # The compiled problem_id must match the envelope id of every gold dataset
    # record, ensuring fixture derivation and compilation stay aligned.
    fixtures = {fixture["id"]: fixture for fixture in _all_gold_fixtures()}
    for record in load_zebra_subset().records:
        fixture = fixtures[f"zl_{record.external_id}"]
        response = _compile(fixture, request_id=f"dataset-{record.external_id}")
        assert response["result"]["kind"] == "COMPILED"
        assert response["result"]["compiled"]["problem_id"] == fixture["id"]


# ----------------------------------------------------------------------------
# Walkthrough tests: lock the Stage 1 / Stage 2 boundary end-to-end.
# These exist as tests (not a permanent debug exe) so the boundary stays
# observable on every CI run.
# ----------------------------------------------------------------------------


def test_compile_walkthrough_problem_to_compiled_protocol() -> None:
    # problem.json -> COMPILED response carrying only the envelope id.
    # Stage 1 parses JSON shape and opaque expect; Stage 2 produces the
    # opaque CompiledPuzzle; the wire result exposes nothing but the
    # envelope id, never a solution.
    fixture = _load_fixture("lgp-test-2x2-33.problem.json")
    response = _compile(fixture, request_id="walkthrough")

    assert response["request_id"] == "walkthrough"
    assert response["result"]["kind"] == "COMPILED"
    assert response["result"]["compiled"] == {"problem_id": fixture["id"]}
    # Nothing derived from the puzzle may leak across the seam.
    for forbidden in ("solution", "expect", "categories", "clues", "size"):
        assert forbidden not in response["result"]["compiled"], forbidden


def test_compile_walkthrough_static_rejection_carries_code_and_message() -> None:
    # Same seam, semantically-bad input: the Lean static compiler rejects it
    # with a structured STATIC_ERROR result that carries the static error code
    # and a human-readable message.
    fixture = _load_fixture("lgp-test-2x2-33.problem.json")
    fixture["clues"][1]["house"] = 999

    response = _compile(fixture, request_id="walkthrough-bad")

    assert response["result"]["kind"] == "STATIC_ERROR"
    assert response["result"]["error_code"] == "house_out_of_range"
    assert response["result"]["message"]
    assert "999" in response["result"]["message"]


def test_compile_walkthrough_each_boundary_step() -> None:
    # Three-step demonstration on the same gold fixture:
    #   1) the JSON Schema (Stage 1 shape) accepts the fixture
    #   2) the verifier returns a COMPILED result with only the envelope id
    #   3) a shape-valid-but-semantically-bad mutation is rejected by the
    #      Lean static compiler (Stage 2) with the right code.
    fixture = _load_fixture("lgp-test-2x2-33.problem.json")

    PROBLEM_VALIDATOR.validate(fixture)

    compiled = _compile(fixture, request_id="walkthrough-step-2")
    assert compiled["result"]["kind"] == "COMPILED"
    assert compiled["result"]["compiled"] == {"problem_id": fixture["id"]}

    bad = json.loads(json.dumps(fixture))
    bad["clues"][0]["a"]["cat"] = "NotARealCategory"
    PROBLEM_VALIDATOR.validate(bad)
    rejected = _compile(bad, request_id="walkthrough-step-3")
    assert rejected["result"]["kind"] == "STATIC_ERROR"
    assert rejected["result"]["error_code"] == "unknown_category"
