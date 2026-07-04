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


def test_frozen_trace_schema_validates_against_lean_parser(tmp_path: Path) -> None:
    """The published zebra-trace.schema.json must accept the same shapes the
    Lean TraceParser accepts, and must reject the same shapes it rejects.
    Drift between the JSON Schema and the trusted parser is a Stage 4 freeze
    failure: this test pins them together."""

    import jsonschema

    schema_path = ROOT / "schemas" / "zebra-trace.schema.json"
    assert schema_path.is_file(), "missing schemas/zebra-trace.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    validator = jsonschema.Draft202012Validator(schema)

    def _expect_valid(trace_obj: dict[str, Any]) -> None:
        validator.validate(trace_obj)

    def _expect_invalid(trace_obj: dict[str, Any]) -> None:
        try:
            validator.validate(trace_obj)
        except jsonschema.ValidationError:
            return
        raise AssertionError(f"schema accepted trace that should be invalid: {trace_obj}")

    # positive: full-candidate
    _expect_valid(
        {
            "schema_version": "0.2",
            "problem_id": "zl_test",
            "ops": [
                {"op": "assign_all", "solution": {"Color": {"1": "red"}}},
                {"op": "conclude", "status": "solved"},
            ],
        }
    )
    # positive: stepwise with from-cells
    _expect_valid(
        {
            "schema_version": "0.2",
            "problem_id": "zl_test",
            "ops": [
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
            ],
        }
    )
    # negative: schema_version mismatch
    _expect_invalid(
        {"schema_version": "0.3", "problem_id": "zl_test", "ops": [{"op": "conclude", "status": "solved"}]}
    )
    # negative: missing required field on place
    _expect_invalid(
        {
            "schema_version": "0.2",
            "problem_id": "zl_test",
            "ops": [{"op": "place", "house": 1, "val": "red", "justify": {"clue": "c1"}}],
        }
    )
    # negative: unknown top-level field
    _expect_invalid(
        {
            "schema_version": "0.2",
            "problem_id": "zl_test",
            "ops": [{"op": "conclude", "status": "solved"}],
            "extra": True,
        }
    )
    # negative: empty ops
    _expect_invalid({"schema_version": "0.2", "problem_id": "zl_test", "ops": []})
    # negative: unknown op
    _expect_invalid(
        {"schema_version": "0.2", "problem_id": "zl_test", "ops": [{"op": "guess"}]}
    )
    # negative: justify missing 'clue'
    _expect_invalid(
        {
            "schema_version": "0.2",
            "problem_id": "zl_test",
            "ops": [
                {"op": "place", "cat": "Color", "house": 1, "val": "red", "justify": {"from": []}}
            ],
        }
    )
    # negative: forbidden justification shape (the internal rule names MUST NOT
    # appear in the public interface).
    _expect_invalid(
        {
            "schema_version": "0.2",
            "problem_id": "zl_test",
            "ops": [
                {
                    "op": "place",
                    "cat": "Color",
                    "house": 1,
                    "val": "red",
                    "justify": {"clue": "c1", "rule": "given_found_at_place"},
                }
            ],
        }
    )
    # negative: bad conclude status
    _expect_invalid(
        {
            "schema_version": "0.2",
            "problem_id": "zl_test",
            "ops": [{"op": "conclude", "status": "unknown"}],
        }
    )


def test_frozen_trace_schema_rejects_internal_rule_names() -> None:
    """The published schema must not admit any of the 22 internal Lean
    consequence-rule names as a valid justification field. This is a hard
    contract: model-supplied internal rule names are not trusted input."""

    import jsonschema

    schema = json.loads(
        (ROOT / "schemas" / "zebra-trace.schema.json").read_text(encoding="utf-8")
    )
    validator = jsonschema.Draft202012Validator(schema)

    forbidden = {
        "given_found_at_place",
        "given_not_at_eliminate",
        "bijection_place_eliminates_same_value_other_houses",
        "bijection_place_eliminates_other_values_same_house",
        "bijection_cell_singleton_forces_place",
        "bijection_value_singleton_forces_place",
        "same_house_place_from_placed",
        "same_house_eliminate_no_possible_match",
        "direct_left_place_from_fixed",
        "direct_left_eliminate_no_possible_partner",
        "direct_right_place_from_fixed",
        "direct_right_eliminate_no_possible_partner",
        "side_by_side_place_from_single_neighbor",
        "side_by_side_eliminate_no_possible_neighbor",
        "left_of_eliminate_impossible_order",
        "right_of_eliminate_impossible_order",
        "one_between_place_from_fixed",
        "one_between_eliminate_no_possible_partner",
        "two_between_place_from_fixed",
        "two_between_eliminate_no_possible_partner",
        "solved_conclusion",
        "contradiction_detection",
    }

    for name in forbidden:
        trace = {
            "schema_version": "0.2",
            "problem_id": "zl_test",
            "ops": [
                {
                    "op": "place",
                    "cat": "Color",
                    "house": 1,
                    "val": "red",
                    "justify": {"clue": "c1", "rule": name},
                }
            ],
        }
        with pytest_raises_jsonschema():
            validator.validate(trace)


def pytest_raises_jsonschema():
    """Tiny helper: context manager that asserts jsonschema.ValidationError."""
    import contextlib

    import jsonschema

    @contextlib.contextmanager
    def _ctx():
        try:
            yield
        except jsonschema.ValidationError:
            return
        raise AssertionError("expected jsonschema.ValidationError")

    return _ctx()
