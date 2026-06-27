import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, ValidationError

from sparseir_harness.dataset import load_zebra_subset


ROOT = Path(__file__).resolve().parents[1]


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
