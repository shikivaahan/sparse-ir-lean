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
    fixtures = tmp_path / "parser-fixtures"
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
        fixtures / "parser_fixture_solutions.jsonl",
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

    manifest = run_trace_parser_gate(gate_a, fixtures, output, 20260629)

    assert manifest["status"] == "pass"
    assert manifest["full_candidate_traces"] == 1
    # Each fixture produces 1 clue-based stepwise + 1 bijection-based
    # stepwise (the latter exercises the public `{"rule": "bijection",
    # "from": ...}` half of the tagged union).
    assert manifest["stepwise_traces"] == 2
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
    fixtures = tmp_path / "parser-fixtures"
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
    _write_jsonl(fixtures / "parser_fixture_solutions.jsonl", [{"candidate": candidate}])

    provider_trace = _trace(
        [
            {"op": "assign_all", "solution": candidate["solution"]},
            {"op": "conclude", "status": "solved"},
        ]
    ).replace("zl_test", candidate["problem_id"])
    manifest = run_trace_parser_gate(
        gate_a,
        fixtures,
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
    failure: this test pins them together.

    This is now a REAL differential gate: every entry in the parity corpus
    is fed through both the JSON Schema validator and the trusted Lean
    TraceParser.parse executable. Verdicts MUST agree on every entry. The
    corpus covers: top-level shapes, missing/extra fields, every JSON value
    type at every nested position, empty/numeric/scientific house indexes,
    the new tagged-union justification contract (`{clue/from}` vs
    `{rule: bijection/from}`), the 22 private kernel rule names being
    rejected at parse time, and the conclusion-shape boundary.
    """

    import jsonschema

    from sparseir_harness.trace_parity_corpus import parity_corpus

    schema_path = ROOT / "schemas" / "zebra-trace.schema.json"
    assert schema_path.is_file(), "missing schemas/zebra-trace.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)

    corpus = parity_corpus()

    def _schema_says_valid(trace_obj: dict[str, Any]) -> bool:
        try:
            validator.validate(trace_obj)
            return True
        except jsonschema.ValidationError:
            return False

    def _lean_says_valid(trace_obj: dict[str, Any]) -> bool:
        completed = subprocess.run(
            [str(EXECUTABLE)],
            cwd=ROOT,
            input=json.dumps(
                {
                    "protocol_version": "0.1.0",
                    "request_id": "parity",
                    "command": "parse_trace",
                    "payload": {
                        "trace": json.dumps(trace_obj, sort_keys=True, separators=(",", ":"))
                    },
                }
            ),
            text=True,
            capture_output=True,
            check=True,
        )
        response = json.loads(completed.stdout)["result"]
        return response.get("kind") == "TRACE_PARSED"

    mismatches: list[tuple[str, bool, bool, bool]] = []
    for name, trace_obj, expected in corpus:
        schema_v = _schema_says_valid(trace_obj)
        lean_v = _lean_says_valid(trace_obj)
        if not (schema_v == lean_v == expected):
            mismatches.append((name, expected, schema_v, lean_v))

    summary = "\n".join(
        f"  {name}: expected={exp} schema={schema_v} lean={lean_v}"
        for name, exp, schema_v, lean_v in mismatches[:20]
    )
    assert not mismatches, (
        "JSON Schema and Lean parser disagree on these trace shapes:\n" + summary
    )


# Regression test: the per-sample four-layer evidence emitted by
# scripts/stage4_provider_stepwise.py must use the canonical field name
# `provider_output_present`. A prior freeze used `raw_output_present` on
# the normal-row path while `provider_output_present` was used on the
# provider-error path — inconsistent. This test pins the canonical name
# so a future edit cannot silently re-introduce the alias.
PROVIDER_OUTPUT_PRESENT_FIELD = "provider_output_present"
LEGACY_PROVIDER_OUTPUT_PRESENT_FIELDS = ("raw_output_present",)


def test_provider_stepwise_analysis_uses_canonical_field_name() -> None:
    """If `scripts/stage4_provider_stepwise.py` ever emits per-sample rows
    with the legacy `raw_output_present` (or any other alias) field instead
    of `provider_output_present`, this test fails the build. The check
    asserts (a) every analyze row carries the canonical key, (b) no row
    carries any of the forbidden alias keys, (c) the four-layer metrics
    pipeline in `analyze_outputs` populates the field correctly.
    """
    import sys

    sys.path.insert(0, str(ROOT / "scripts"))
    from stage4_provider_stepwise import (  # noqa: E402
        PRIVATE_KERNEL_RULE_NAMES,
        analyze_outputs,
    )
    import jsonschema

    # Build a fake output dir with one provider-error row, one raw-JSON
    # valid + schema-valid + Lean TRACE_PARSED row, and one garbage-JSON row.
    fake_dir = ROOT / "eval" / "stage4-fake-analyze-test"
    fake_dir.mkdir(parents=True, exist_ok=True)
    raw_lines = [
        {
            "sample_id": "alpha-00",
            "scenario": "alpha",
            "problem_id": "p1",
            "provider_error": "rate limit",
        },
        {
            "sample_id": "beta-00",
            "scenario": "beta",
            "problem_id": "p2",
            "raw_output": json.dumps(
                {
                    "schema_version": "0.2",
                    "problem_id": "p2",
                    "ops": [{"op": "conclude", "status": "solved"}],
                }
            ),
        },
        {
            "sample_id": "gamma-00",
            "scenario": "gamma",
            "problem_id": "p3",
            "raw_output": '{"schema_version": "0.2", "problem_id":',  # malformed JSON
        },
    ]
    (fake_dir / "raw_outputs.jsonl").write_text(
        "\n".join(json.dumps(r) for r in raw_lines) + "\n", encoding="utf-8"
    )
    (fake_dir / "prompts.jsonl").write_text(
        "\n".join(
            json.dumps(
                {
                    "sample_id": r["sample_id"],
                    "scenario": r["scenario"],
                    "problem_id": r["problem_id"],
                    "model": "test",
                    "messages": [],
                }
            )
            for r in raw_lines
        )
        + "\n",
        encoding="utf-8",
    )

    schema = json.loads((ROOT / "schemas" / "zebra-trace.schema.json").read_text(encoding="utf-8"))
    schema_validator = jsonschema.Draft202012Validator(schema)
    executable = ROOT / ".lake" / "build" / "bin" / "sparse-ir-lean"
    executable_arg = executable if executable.is_file() else None

    manifest = analyze_outputs(
        fake_dir,
        lean_executable=executable_arg,
        schema_validator=schema_validator,
        model="test",
    )
    rows = [
        json.loads(line)
        for line in (fake_dir / "analyze_results.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(rows) == 3, rows

    # (a) every analyze row carries the canonical key.
    for r in rows:
        assert PROVIDER_OUTPUT_PRESENT_FIELD in r, (
            f"row missing canonical field {PROVIDER_OUTPUT_PRESENT_FIELD!r}: {r}"
        )

    # (b) no row carries any forbidden alias key.
    for r in rows:
        for alias in LEGACY_PROVIDER_OUTPUT_PRESENT_FIELDS:
            assert alias not in r, (
                f"row still carries legacy alias {alias!r}: {r}"
            )

    # (c) The provider-output-present value is meaningful: provider_error
    # row -> False, valid-output row -> True, garbage-JSON row -> True
    # (the provider DID return text; what we mean by "valid JSON" is the
    # next layer).
    by_id = {r["sample_id"]: r for r in rows}
    assert by_id["alpha-00"][PROVIDER_OUTPUT_PRESENT_FIELD] is False
    assert by_id["beta-00"][PROVIDER_OUTPUT_PRESENT_FIELD] is True
    assert by_id["gamma-00"][PROVIDER_OUTPUT_PRESENT_FIELD] is True
    # Also sanity-check that the global count the manifest reports matches
    # what the rows say.
    counts = [
        bool(r.get(PROVIDER_OUTPUT_PRESENT_FIELD)) for r in rows
    ]
    assert manifest["provider_returned_output"] == sum(counts)
    # And PRIVATE_KERNEL_RULE_NAMES must be the exact set of names declared
    # by SparseIRLean.StepKernel.supportedRules, with no duplicates on
    # either side. This catches the class of drift where one legitimate
    # rule disappears from Python (or a stale name appears) while the
    # total cardinality happens to stay at 22.
    import re as _re

    step_kernel_text = (ROOT / "SparseIRLean" / "StepKernel.lean").read_text(encoding="utf-8")
    # Narrowly scope extraction to the supportedRules declaration body so
    # every other double-quoted string literal in the file is ignored.
    m = _re.search(
        r"def\s+supportedRules\s*:\s*List\s+String\s*:=\s*\[(?P<body>.*?)\]",
        step_kernel_text,
        flags=_re.DOTALL,
    )
    assert m is not None, (
        "could not locate SparseIRLean/StepKernel.lean::supportedRules "
        "list declaration; the extraction rule may be stale."
    )
    lean_supported_rules: list[str] = _re.findall(r'"([^"]+)"', m.group("body"))
    assert len(lean_supported_rules) > 0, (
        "expected at least one string literal inside "
        "StepKernel.supportedRules body"
    )
    # Exact-set equality between the Python leakage scan and the Lean
    # declaration, with both sides required to be duplicate-free so the
    # set comparison cannot mask a duplicate.
    assert len(PRIVATE_KERNEL_RULE_NAMES) == len(set(PRIVATE_KERNEL_RULE_NAMES)), (
        "PRIVATE_KERNEL_RULE_NAMES contains duplicates"
    )
    assert len(lean_supported_rules) == len(set(lean_supported_rules)), (
        "StepKernel.supportedRules contains duplicates"
    )
    py_set = set(PRIVATE_KERNEL_RULE_NAMES)
    lean_set = set(lean_supported_rules)
    missing_in_py = lean_set - py_set
    extra_in_py = py_set - lean_set
    assert not missing_in_py and not extra_in_py, (
        "PRIVATE_KERNEL_RULE_NAMES is out of sync with "
        "StepKernel.supportedRules.\n"
        f"  in Lean only (Python is missing): {sorted(missing_in_py)}\n"
        f"  in Python only (Lean has no such rule): {sorted(extra_in_py)}\n"
        "Update one of them so the two sides match exactly."
    )
    assert py_set == lean_set, "redundant guard"

    # Cleanup.
    import shutil as _shutil

    _shutil.rmtree(fake_dir)


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
