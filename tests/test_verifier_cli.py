import json
import os
import subprocess
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_SCHEMA = json.loads(
    (ROOT / "schemas" / "verifier-protocol.schema.json").read_text(encoding="utf-8")
)
PROTOCOL_VALIDATOR = Draft202012Validator(PROTOCOL_SCHEMA)


def _lake() -> str:
    return os.environ.get("LAKE", "lake")


def _response(stdout: str) -> dict:
    response = json.loads(stdout)
    PROTOCOL_VALIDATOR.validate(response)
    return response


def test_info_command_reports_stage0_capabilities() -> None:
    request_value = {
        "protocol_version": "0.1.0",
        "request_id": "test-info",
        "command": "info",
    }
    PROTOCOL_VALIDATOR.validate(request_value)
    completed = subprocess.run(
        [_lake(), "exe", "sparse-ir-lean"],
        cwd=ROOT,
        input=json.dumps(request_value),
        text=True,
        capture_output=True,
        check=True,
    )
    response = _response(completed.stdout)

    assert response["protocol_version"] == "0.1.0"
    assert response["request_id"] == "test-info"
    assert response["result"]["kind"] == "INFO"
    assert response["result"]["domain"] == "zebra"
    assert response["result"]["schema_version"] == "0.2"
    assert response["result"]["capabilities"]["modes"] == [0]
    assert response["result"]["capabilities"]["stepwise"] is False
    assert response["result"]["capabilities"]["audit_view"] is False
    assert response["result"]["capabilities"]["tactics"] is False


@pytest.mark.parametrize(
    "command",
    [
        "step",
        "classify",
        "render_audit",
        "emit_artifact",
    ],
)
def test_unimplemented_commands_fail_closed(command: str) -> None:
    request_value = {
        "protocol_version": "0.1.0",
        "request_id": f"test-{command}",
        "command": command,
    }
    PROTOCOL_VALIDATOR.validate(request_value)
    completed = subprocess.run(
        [_lake(), "exe", "sparse-ir-lean"],
        cwd=ROOT,
        input=json.dumps(request_value),
        text=True,
        capture_output=True,
        check=True,
    )
    response = _response(completed.stdout)

    assert response["result"]["kind"] == "STATIC_ERROR"
    assert response["result"]["error_code"] == "not_implemented_stage_0"


def test_unknown_protocol_version_fails_closed() -> None:
    request = json.dumps(
        {"protocol_version": "99", "request_id": "test-version", "command": "info"}
    )
    completed = subprocess.run(
        [_lake(), "exe", "sparse-ir-lean"],
        cwd=ROOT,
        input=request,
        text=True,
        capture_output=True,
        check=True,
    )
    response = _response(completed.stdout)

    assert response["result"]["kind"] == "STATIC_ERROR"
    assert response["result"]["error_code"] == "unsupported_protocol_version"


@pytest.mark.parametrize(
    "request_value",
    [
        [],
        {"protocol_version": "0.1.0", "command": "info", "extra": True},
        {"protocol_version": "0.1.0", "command": "info", "payload": []},
        {"protocol_version": "0.1.0", "command": "unknown"},
    ],
)
def test_requests_outside_frozen_schema_are_rejected(request_value: object) -> None:
    completed = subprocess.run(
        [_lake(), "exe", "sparse-ir-lean"],
        cwd=ROOT,
        input=json.dumps(request_value),
        text=True,
        capture_output=True,
        check=True,
    )
    response = _response(completed.stdout)

    assert response["result"]["kind"] == "STATIC_ERROR"
    assert response["result"]["error_code"] == "invalid_request"
