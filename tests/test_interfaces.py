import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, ValidationError

from sparseir_harness.dataset import load_zebra_subset


ROOT = Path(__file__).resolve().parents[1]
PROBLEM_FIXTURES = ROOT / "tests" / "problems"


def test_canonical_envelope_schema_accepts_dataset_metadata() -> None:
    schema = json.loads((ROOT / "schemas" / "problem-envelope.schema.json").read_text())
    Draft202012Validator.check_schema(schema)
    record = load_zebra_subset().records[0]
    envelope = {
        "schema_version": "0.2",
        "domain": "zebra",
        "id": f"zl_{record.external_id}",
        "source": {
            "dataset": "zebralogic",
            "split": record.split,
            "external_id": record.external_id,
            "grid": record.grid,
        },
        "expect": {"opaque": True},
    }

    Draft202012Validator(schema).validate(envelope)


def test_frozen_zebra_problem_schema_accepts_dataset_derived_fixtures() -> None:
    schema = json.loads((ROOT / "schemas" / "zebra-problem.schema.json").read_text())
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)

    fixtures = sorted(PROBLEM_FIXTURES.glob("*.problem.json"))
    assert [path.name for path in fixtures] == [
        "lgp-test-2x2-33.problem.json",
        "lgp-test-4x4-27.problem.json",
        "lgp-test-6x6-5.problem.json",
    ]
    source_records = {record.external_id: record for record in load_zebra_subset().records}
    clue_types: set[str] = set()
    for fixture in fixtures:
        value = json.loads(fixture.read_text(encoding="utf-8"))
        validator.validate(value)
        source = source_records[value["source"]["external_id"]]
        assert value["source"]["grid"] == source.grid
        assert value["size"]["houses"] == int(source.grid.split("x")[0])
        clue_types.update(clue["type"] for clue in value["clues"])
    assert clue_types == {
        "found_at",
        "not_at",
        "same_house",
        "direct_left",
        "direct_right",
        "side_by_side",
        "left_of",
        "right_of",
        "one_between",
        "two_between",
    }


def test_problem_schema_freezes_stage1_policy_and_error_vocabulary() -> None:
    schema = json.loads((ROOT / "schemas" / "zebra-problem.schema.json").read_text())

    assert schema["x-sparseir-interface"] == {
        "version": "0.2",
        "status": "frozen-stage-2",
        "unknown-field-policy": "reject",
    }
    assert schema["x-sparseir-parse-error-codes"] == [
        "invalid_json",
        "expected_object",
        "missing_field",
        "unknown_field",
        "invalid_field_type",
        "invalid_value",
        "invalid_house",
        "unknown_clue_type",
    ]
    assert schema["x-sparseir-static-error-codes"] == [
        "invalid_json",
        "invalid_schema",
        "unsupported_schema_version",
        "invalid_domain",
        "size_mismatch",
        "category_size_mismatch",
        "duplicate_value",
        "unknown_category",
        "unknown_value",
        "house_out_of_range",
        "duplicate_clue_id",
    ]


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.pop("domain"),
        lambda value: value.update(extra=True),
        lambda value: value["clues"][0].update(type="unknown"),
        lambda value: value["clues"][0].pop("a"),
        lambda value: value["clues"][1].update(house=0),
        lambda value: value["clues"][1].update(house="1"),
    ],
)
def test_problem_schema_rejects_dataset_derived_malformed_mutations(mutation) -> None:
    schema = json.loads((ROOT / "schemas" / "zebra-problem.schema.json").read_text())
    value = json.loads(
        (PROBLEM_FIXTURES / "lgp-test-2x2-33.problem.json").read_text(encoding="utf-8")
    )
    mutation(value)

    with pytest.raises(ValidationError):
        Draft202012Validator(schema).validate(value)


@pytest.mark.parametrize(
    "mutation",
    [
        # Semantic-but-shape-valid mutations that the JSON Schema accepts but
        # Stage 2 must reject. They exist so the parser boundary stays narrow.
        lambda value: value.update(domain="horn"),
        lambda value: value.update(schema_version="9"),
        lambda value: value.update(size={"houses": 99, "categories": 2}),
        lambda value: value["categories"].update(Name=["Eric", "Eric"]),
        lambda value: value["clues"][0]["a"].update(cat="Undeclared"),
        lambda value: value["clues"][0]["a"].update(val="Missing"),
        lambda value: value["clues"][1].update(house=99),
        lambda value: value["clues"][1].update(id=value["clues"][0]["id"]),
    ],
)
def test_problem_schema_accepts_shape_valid_semantic_mutations(mutation) -> None:
    schema = json.loads((ROOT / "schemas" / "zebra-problem.schema.json").read_text())
    value = json.loads(
        (PROBLEM_FIXTURES / "lgp-test-2x2-33.problem.json").read_text(encoding="utf-8")
    )
    mutation(value)

    # Stage 1 (the JSON Schema shape check) accepts these. Stage 2 rejects them.
    Draft202012Validator(schema).validate(value)


def test_verifier_protocol_schema_is_version_stamped() -> None:
    schema = json.loads((ROOT / "schemas" / "verifier-protocol.schema.json").read_text())
    Draft202012Validator.check_schema(schema)
    assert schema["x-sparseir-interface"] == {
        "version": "0.1.0",
        "status": "frozen-stage-0",
        "transport": "single-request-json-stdin-single-response-json-stdout",
    }
    assert set(schema["x-sparseir-command-results"]) == set(
        schema["$defs"]["request"]["properties"]["command"]["enum"]
    )
    result_kinds = set(schema["$defs"]["result_kind"]["enum"])
    for admitted_results in schema["x-sparseir-command-results"].values():
        assert set(admitted_results) <= result_kinds
        assert set(admitted_results) != {"STATIC_ERROR"}


def _verifier_protocol_validator() -> Draft202012Validator:
    schema = json.loads((ROOT / "schemas" / "verifier-protocol.schema.json").read_text())
    return Draft202012Validator(schema)


@pytest.mark.parametrize(
    "message",
    [
        {"protocol_version": "0.1.0", "command": "info"},
        {
            "protocol_version": "0.1.0",
            "request_id": "compile-test",
            "command": "compile",
            "payload": {},
        },
        {
            "protocol_version": "0.1.0",
            "request_id": "compile-view-test",
            "command": "compile_view",
            "payload": {},
        },
    ],
)
def test_published_verifier_schema_accepts_requests_directly(message: dict) -> None:
    _verifier_protocol_validator().validate(message)


@pytest.mark.parametrize(
    "message",
    [
        None,
        {},
        {"protocol_version": "0.1.0", "command": "unknown"},
        {"protocol_version": "0.1.0", "command": "info", "payload": []},
        {"protocol_version": "0.1.0", "command": "info", "extra": True},
    ],
)
def test_published_verifier_schema_rejects_invalid_messages_directly(
    message: object,
) -> None:
    with pytest.raises(ValidationError):
        _verifier_protocol_validator().validate(message)


@pytest.mark.parametrize(
    "result",
    [
        {
            "kind": "INFO",
            "backend_id": "SparseIRLeanVerifier",
            "backend_version": "0.1.0",
            "domain": "zebra",
            "schema_version": "0.2",
            "trust": "trusted_for_results",
            "capabilities": {
                "modes": [0, 1, 2],
                "stepwise": False,
                "tactics": False,
                "audit_view": False,
            },
        },
        {"kind": "STATIC_ERROR", "error_code": "invalid_request", "message": "bad"},
        {"kind": "COMPILED", "compiled": {"problem_id": "test"}},
        {"kind": "STATE_INITIALIZED", "state": {"cursor": 0}},
        {"kind": "ACCEPT_STEP", "state": {"cursor": 1}},
        {"kind": "ACCEPT_SOLVED", "artifact": {"status": "checked"}},
        {"kind": "INCOMPLETE", "state": {"cursor": 1}},
        {"kind": "REJECT", "failure": {"code": "bad_step"}},
        {"kind": "AUDIT_RENDERED", "readable_view": "checked assignment"},
        {"kind": "ARTIFACT_EMITTED", "artifact": {"status": "checked"}},
    ],
)
def test_verifier_response_schema_accepts_each_frozen_result(result: dict) -> None:
    _verifier_protocol_validator().validate(
        {"protocol_version": "0.1.0", "request_id": "test", "result": result}
    )


@pytest.mark.parametrize(
    "result",
    [
        {},
        {"kind": "UNKNOWN"},
        {"kind": "COMPILED"},
        {"kind": "STATE_INITIALIZED"},
        {"kind": "ACCEPT_STEP"},
        {"kind": "ACCEPT_SOLVED"},
        {"kind": "INCOMPLETE"},
        {"kind": "REJECT"},
        {"kind": "AUDIT_RENDERED"},
        {"kind": "ARTIFACT_EMITTED"},
        {"kind": "REJECT", "failure": {}, "arbitrary": True},
        {"kind": "STATIC_ERROR", "error_code": "invalid_request"},
        {
            "kind": "INFO",
            "backend_id": "SparseIRLeanVerifier",
            "backend_version": "0.1.0",
            "domain": "zebra",
            "schema_version": "0.2",
            "trust": "trusted_for_results",
            "capabilities": {
                "modes": [],
                "stepwise": False,
                "tactics": False,
                "audit_view": False,
            },
            "arbitrary": True,
        },
        {
            "kind": "INFO",
            "backend_id": "SparseIRLeanVerifier",
            "backend_version": "0.1.0",
            "domain": "zebra",
            "schema_version": "0.2",
            "trust": "trusted_for_results",
            "capabilities": {
                "modes": ["0", "1", "2"],
                "stepwise": True,
                "tactics": False,
                "audit_view": True,
            },
        },
    ],
)
def test_verifier_response_schema_rejects_invalid_results(result: dict) -> None:
    with pytest.raises(ValidationError):
        _verifier_protocol_validator().validate(
            {"protocol_version": "0.1.0", "request_id": "test", "result": result}
        )
