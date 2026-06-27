import json
import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _lake() -> str:
    return os.environ.get("LAKE", "lake")


def test_info_command_reports_stage0_capabilities() -> None:
    request = json.dumps(
        {"protocol_version": "0.1.0", "request_id": "test-info", "command": "info"}
    )
    completed = subprocess.run(
        [_lake(), "exe", "sparse-ir-lean"],
        cwd=ROOT,
        input=request,
        text=True,
        capture_output=True,
        check=True,
    )
    response = json.loads(completed.stdout)

    assert response["protocol_version"] == "0.1.0"
    assert response["request_id"] == "test-info"
    assert response["result"]["kind"] == "INFO"
    assert response["result"]["domain"] == "zebra"
    assert response["result"]["schema_version"] == "0.2"
    assert response["result"]["capabilities"]["modes"] == []


def test_unimplemented_command_fails_closed() -> None:
    request = json.dumps(
        {"protocol_version": "0.1.0", "request_id": "test-compile", "command": "compile"}
    )
    completed = subprocess.run(
        [_lake(), "exe", "sparse-ir-lean"],
        cwd=ROOT,
        input=request,
        text=True,
        capture_output=True,
        check=True,
    )
    response = json.loads(completed.stdout)

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
    response = json.loads(completed.stdout)

    assert response["result"]["kind"] == "STATIC_ERROR"
    assert response["result"]["error_code"] == "unsupported_protocol_version"
