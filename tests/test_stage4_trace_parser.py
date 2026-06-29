"""Stage 4 trace AST, protocol, and evidence-gate tests."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from sparseir_harness.trace_parser_gate import (
    REQUIRED_ERROR_CODES,
    _provider_validation,
    _malformed_cases,
    run_trace_parser_gate,
)


ROOT = Path(__file__).resolve().parents[1]
EXECUTABLE = ROOT / ".lake" / "build" / "bin" / "sparse-ir-lean"


def _call(trace: str) -> dict[str, Any]:
    completed = subprocess.run(
        [str(EXECUTABLE)],
        cwd=ROOT,
        input=json.dumps(
            {
                "protocol_version": "0.1.0",
                "request_id": "stage4-test",
                "command": "parse_trace",
                "payload": {"trace": trace},
            }
        ),
        text=True,
        capture_output=True,
        check=True,
    )
    return json.loads(completed.stdout)["result"]


def _trace(ops: list[dict[str, Any]]) -> str:
    return json.dumps({"schema_version": "0.2", "problem_id": "zl_test", "ops": ops})


def test_valid_full_candidate_trace_parses_without_checking_solution() -> None:
    result = _call(
        _trace(
            [
                {"op": "assign_all", "solution": {"Color": {"1": "not-declared"}}},
                {"op": "conclude", "status": "solved"},
            ]
        )
    )
    assert result == {
        "kind": "TRACE_PARSED",
        "problem_id": "zl_test",
        "op_count": 2,
        "trace_style": "full_candidate",
    }


def test_valid_stepwise_trace_parses_justify_and_from_cells() -> None:
    result = _call(
        _trace(
            [
                {
                    "op": "place",
                    "cat": "Color",
                    "house": 2,
                    "val": "red",
                    "justify": {"clue": "c1"},
                },
                {
                    "op": "eliminate",
                    "cat": "Drink",
                    "house": 1,
                    "val": "tea",
                    "justify": {
                        "clue": "c3",
                        "from": [{"cat": "Color", "house": 2, "val": "red"}],
                    },
                },
                {"op": "conclude", "status": "solved"},
            ]
        )
    )
    assert result["kind"] == "TRACE_PARSED"
    assert result["trace_style"] == "stepwise"
    assert result["op_count"] == 3


def test_all_required_parse_errors_return_structured_codes_and_paths() -> None:
    observed: set[str] = set()
    for case in _malformed_cases():
        result = _call(case.trace_text)
        assert result["kind"] == "REJECT", case.trace_id
        failure = result["failure"]
        assert failure["status"] == "malformed_trace", case.trace_id
        assert failure["failure_code"] == case.expected_code, case.trace_id
        assert failure["path"] == case.expected_path, case.trace_id
        assert failure["message"], case.trace_id
        observed.add(failure["failure_code"])
    assert observed == set(REQUIRED_ERROR_CODES)


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def test_gate_writes_complete_parser_artifacts(tmp_path: Path) -> None:
    gate_a = tmp_path / "gate-a"
    references = tmp_path / "references"
    output = tmp_path / "stage4"
    problem_id = "zl_fixture"
    _write_jsonl(
        gate_a / "compiled_problems.jsonl",
        [
            {
                "problem_id": problem_id,
                "compiled_categories": [{"name": "Color", "values": ["red", "blue"]}],
                "compiled_clues": [
                    {"id": "c1", "type": "found_at", "cat": "Color", "val": "red", "house": 1}
                ],
            }
        ],
    )
    _write_jsonl(
        references / "reference_solutions.jsonl",
        [
            {
                "candidate": {
                    "schema_version": "0.2",
                    "problem_id": problem_id,
                    "solution": {"Color": {"1": "red", "2": "blue"}},
                }
            }
        ],
    )

    manifest = run_trace_parser_gate(gate_a, references, output, 20260629)

    assert manifest["status"] == "pass"
    assert manifest["full_candidate_traces"] == 1
    assert manifest["stepwise_traces"] == 1
    assert all(manifest["parse_error_coverage"].values())
    assert manifest["total_protocol_error"] == 0
    assert manifest["provider_validation"]["status"] == "blocked"
    assert manifest["replay_or_checking"] is False
    for name in (
        "manifest.json",
        "traces.jsonl",
        "results.jsonl",
        "failures.jsonl",
        "examples.md",
        "summary.md",
    ):
        assert (output / name).is_file()
    assert len(list((output / "trace_json").glob("*.trace.json"))) == manifest["total_traces"]
    assert (output / "failures.jsonl").read_text(encoding="utf-8") == ""
    assert not (output / "provider_validation.jsonl").exists()


def test_provider_validation_is_diagnostic_and_does_not_change_core_status(tmp_path: Path) -> None:
    gate_a = tmp_path / "gate-a"
    references = tmp_path / "references"
    output = tmp_path / "stage4"
    candidate = {
        "schema_version": "0.2",
        "problem_id": "zl_provider_fixture",
        "solution": {"Color": {"1": "red"}},
    }
    _write_jsonl(
        gate_a / "compiled_problems.jsonl",
        [
            {
                "problem_id": candidate["problem_id"],
                "compiled_categories": [{"name": "Color", "values": ["red"]}],
                "compiled_clues": [
                    {"id": "c1", "type": "found_at", "cat": "Color", "val": "red", "house": 1}
                ],
            }
        ],
    )
    _write_jsonl(references / "reference_solutions.jsonl", [{"candidate": candidate}])

    provider_trace = _trace(
        [
            {"op": "assign_all", "solution": candidate["solution"]},
            {"op": "conclude", "status": "solved"},
        ]
    ).replace("zl_test", candidate["problem_id"])
    manifest = run_trace_parser_gate(
        gate_a,
        references,
        output,
        20260629,
        provider_validate=True,
        provider_call=lambda _prompt, _model: provider_trace,
    )

    assert manifest["status"] == "pass"
    assert manifest["provider_validation"]["status"] == "pass"
    assert manifest["provider_validation"]["valid_json_trace_rate"] == 1.0
    assert manifest["provider_validation"]["valid_trace_schema_rate"] == 1.0
    rows = [
        json.loads(line)
        for line in (output / "provider_validation.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert rows[0]["parser_result"]["kind"] == "TRACE_PARSED"


def test_provider_validation_reports_fail_when_no_output_is_schema_valid() -> None:
    references = [
        {
            "candidate": {
                "problem_id": "zl_fixture",
                "solution": {"Color": {"1": "red"}},
            }
        }
    ]

    def reject_trace(_request: dict[str, Any], _executable: Path | None) -> dict[str, Any]:
        return {
            "result": {
                "kind": "REJECT",
                "failure": {
                    "failure_code": "unexpected_field",
                    "path": "$.operations",
                },
            }
        }

    result, _rows = _provider_validation(
        references,
        None,
        reject_trace,
        lambda _messages, _model: json.dumps({"operations": []}),
        "deepseek/deepseek-v4-flash",
    )
    assert result["status"] == "fail"
    assert result["valid_trace_schemas"] == 0
