"""Stage 4 trace-parser evidence gate."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from collections import Counter
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[2]
PROVIDER = "openrouter"
DEFAULT_PROVIDER_MODEL = "deepseek/deepseek-v4-flash"
TRACE_PROMPT_EXEMPLAR = {
    "schema_version": "0.2",
    "problem_id": "zl_example",
    "ops": [
        {"op": "assign_all", "solution": {"Category": {"1": "value"}}},
        {"op": "conclude", "status": "solved"},
    ],
}
REQUIRED_ERROR_CODES = (
    "invalid_json",
    "missing_schema_version",
    "unsupported_schema_version",
    "missing_problem_id",
    "missing_ops",
    "ops_not_array",
    "empty_ops",
    "unknown_op",
    "assign_all_missing_solution",
    "assign_all_malformed_solution",
    "place_missing_cat",
    "place_missing_house",
    "place_missing_val",
    "eliminate_missing_cat",
    "eliminate_missing_house",
    "eliminate_missing_val",
    "missing_justify",
    "malformed_justify",
    "malformed_from_cell",
    "conclude_missing_status",
    "conclude_bad_status",
    "unexpected_field",
)


@dataclass(frozen=True)
class TraceCase:
    trace_id: str
    category: str
    trace_text: str
    problem_id: str | None
    expected_kind: str
    expected_style: str | None = None
    expected_code: str | None = None
    expected_path: str | None = None


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise FileNotFoundError(f"required input is missing: {path}")
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def _invoke_lean(request: dict[str, Any], executable: Path | None) -> dict[str, Any]:
    command = [str(executable)] if executable is not None else ["lake", "exe", "sparse-ir-lean"]
    completed = subprocess.run(
        command,
        cwd=ROOT,
        input=json.dumps(request),
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"Lean verifier exited with {completed.returncode}: {completed.stderr.strip()}"
        )
    return json.loads(completed.stdout)


def _json_text(value: dict[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _full_candidate_cases(references: list[dict[str, Any]]) -> list[TraceCase]:
    cases: list[TraceCase] = []
    for index, reference in enumerate(references):
        candidate = reference["candidate"]
        problem_id = candidate["problem_id"]
        trace = {
            "schema_version": "0.2",
            "problem_id": problem_id,
            "ops": [
                {"op": "assign_all", "solution": candidate["solution"]},
                {"op": "conclude", "status": "solved"},
            ],
        }
        cases.append(
            TraceCase(
                f"valid-full-{index:04d}",
                "valid_full_candidate",
                _json_text(trace),
                problem_id,
                "TRACE_PARSED",
                "full_candidate",
            )
        )
    return cases


def _step_from_problem(problem: dict[str, Any]) -> dict[str, Any]:
    clues = problem["compiled_clues"]
    for clue in clues:
        if clue["type"] == "found_at":
            return {
                "op": "place",
                "cat": clue["cat"],
                "house": clue["house"],
                "val": clue["val"],
                "justify": {"clue": clue["id"]},
            }
    for clue in clues:
        if clue["type"] == "not_at":
            return {
                "op": "eliminate",
                "cat": clue["cat"],
                "house": clue["house"],
                "val": clue["val"],
                "justify": {"clue": clue["id"]},
            }
    clue = clues[0]
    source = clue.get("a", {"cat": problem["compiled_categories"][0]["name"], "val": problem["compiled_categories"][0]["values"][0]})
    return {
        "op": "eliminate",
        "cat": source["cat"],
        "house": 1,
        "val": source["val"],
        "justify": {
            "clue": clue["id"],
            "from": [{"cat": source["cat"], "house": 2, "val": source["val"]}],
        },
    }


def _stepwise_cases(
    references: list[dict[str, Any]], problems: dict[str, dict[str, Any]]
) -> list[TraceCase]:
    cases: list[TraceCase] = []
    for index, reference in enumerate(references):
        candidate = reference["candidate"]
        problem_id = candidate["problem_id"]
        problem = problems.get(problem_id)
        if problem is None:
            continue
        trace = {
            "schema_version": "0.2",
            "problem_id": problem_id,
            "ops": [
                _step_from_problem(problem),
                {"op": "conclude", "status": "solved", "solution": candidate["solution"]},
            ],
        }
        cases.append(
            TraceCase(
                f"valid-stepwise-{index:04d}",
                "valid_stepwise",
                _json_text(trace),
                problem_id,
                "TRACE_PARSED",
                "stepwise",
            )
        )
    return cases


def _malformed_case(
    trace_id: str, code: str, path: str, trace: dict[str, Any] | str
) -> TraceCase:
    text = trace if isinstance(trace, str) else _json_text(trace)
    return TraceCase(trace_id, "malformed", text, None, "REJECT", expected_code=code, expected_path=path)


def _malformed_cases() -> list[TraceCase]:
    envelope = {"schema_version": "0.2", "problem_id": "zl_stage4", "ops": []}
    cases = [_malformed_case("error-invalid-json", "invalid_json", "$", "{")]

    def case(name: str, code: str, path: str, value: dict[str, Any]) -> None:
        cases.append(_malformed_case(f"error-{name}", code, path, value))

    value = deepcopy(envelope)
    value.pop("schema_version")
    case("missing-schema-version", "missing_schema_version", "$.schema_version", value)
    value = deepcopy(envelope)
    value["schema_version"] = "9"
    case("unsupported-schema-version", "unsupported_schema_version", "$.schema_version", value)
    value = deepcopy(envelope)
    value.pop("problem_id")
    case("missing-problem-id", "missing_problem_id", "$.problem_id", value)
    value = deepcopy(envelope)
    value.pop("ops")
    case("missing-ops", "missing_ops", "$.ops", value)
    value = deepcopy(envelope)
    value["ops"] = {}
    case("ops-not-array", "ops_not_array", "$.ops", value)
    case("empty-ops", "empty_ops", "$.ops", deepcopy(envelope))

    def with_op(op: dict[str, Any]) -> dict[str, Any]:
        value = deepcopy(envelope)
        value["ops"] = [op]
        return value

    case("unknown-op", "unknown_op", "$.ops[0].op", with_op({"op": "guess"}))
    case(
        "assign-all-missing-solution",
        "assign_all_missing_solution",
        "$.ops[0].solution",
        with_op({"op": "assign_all"}),
    )
    case(
        "assign-all-malformed-solution",
        "assign_all_malformed_solution",
        "$.ops[0].solution",
        with_op({"op": "assign_all", "solution": []}),
    )
    place = {"op": "place", "cat": "Color", "house": 1, "val": "red", "justify": {"clue": "c1"}}
    for field, code in (
        ("cat", "place_missing_cat"),
        ("house", "place_missing_house"),
        ("val", "place_missing_val"),
    ):
        op = deepcopy(place)
        op.pop(field)
        case(code.replace("_", "-"), code, f"$.ops[0].{field}", with_op(op))
    eliminate = {"op": "eliminate", "cat": "Drink", "house": 2, "val": "tea", "justify": {"clue": "c2"}}
    for field, code in (
        ("cat", "eliminate_missing_cat"),
        ("house", "eliminate_missing_house"),
        ("val", "eliminate_missing_val"),
    ):
        op = deepcopy(eliminate)
        op.pop(field)
        case(code.replace("_", "-"), code, f"$.ops[0].{field}", with_op(op))
    op = deepcopy(place)
    op.pop("justify")
    case("missing-justify", "missing_justify", "$.ops[0].justify", with_op(op))
    op = deepcopy(place)
    op["justify"] = []
    case("malformed-justify", "malformed_justify", "$.ops[0].justify", with_op(op))
    op = deepcopy(place)
    op["justify"] = {"clue": "c1", "from": [{"cat": "Drink", "val": "tea"}]}
    case(
        "malformed-from-cell",
        "malformed_from_cell",
        "$.ops[0].justify.from[0].house",
        with_op(op),
    )
    case(
        "conclude-missing-status",
        "conclude_missing_status",
        "$.ops[0].status",
        with_op({"op": "conclude"}),
    )
    case(
        "conclude-bad-status",
        "conclude_bad_status",
        "$.ops[0].status",
        with_op({"op": "conclude", "status": "unknown"}),
    )
    value = with_op({"op": "conclude", "status": "solved"})
    value["extra"] = True
    case("unexpected-field", "unexpected_field", "$.extra", value)
    return cases


def _relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def build_provider_messages(problem_id: str, solution: dict[str, Any]) -> list[dict[str, str]]:
    exemplar = json.dumps(TRACE_PROMPT_EXEMPLAR, sort_keys=True, separators=(",", ":"))
    payload = json.dumps(
        {"problem_id": problem_id, "solution": solution},
        sort_keys=True,
        separators=(",", ":"),
    )
    return [
        {
            "role": "system",
            "content": (
                "Return only one raw trace.json object, with no wrapper, Markdown, commentary, "
                "or extra fields. The top-level keys must be exactly schema_version, problem_id, "
                "and ops. Use schema_version \"0.2\". The ops array must contain exactly "
                "{\"op\":\"assign_all\",\"solution\":...} followed by "
                "{\"op\":\"conclude\",\"status\":\"solved\"}. Copy the supplied solution "
                f"without changing its shape. Valid shape exemplar: {exemplar}"
            ),
        },
        {"role": "user", "content": payload},
    ]


def call_provider(messages: list[dict[str, str]], model: str) -> str:
    from openai import OpenAI

    client = OpenAI(
        api_key=os.environ["OPENROUTER_API_KEY"],
        base_url="https://openrouter.ai/api/v1",
        max_retries=0,
        timeout=60.0,
    )
    response = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=0,
        max_tokens=1800,
    )
    content = response.choices[0].message.content
    if not content:
        raise RuntimeError("provider returned an empty response")
    return content


def _provider_validation(
    references: list[dict[str, Any]],
    executable: Path | None,
    lean_invoke: Callable[[dict[str, Any], Path | None], dict[str, Any]],
    provider_call: Callable[[list[dict[str, str]], str], str],
    model: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    failures: Counter[str] = Counter()
    for index, reference in enumerate(references[:3]):
        candidate = reference["candidate"]
        sample_id = f"provider-trace-{index:02d}"
        messages = build_provider_messages(candidate["problem_id"], candidate["solution"])
        try:
            raw_output = provider_call(messages, model)
            try:
                parsed = json.loads(raw_output)
                valid_json = isinstance(parsed, dict)
            except json.JSONDecodeError:
                valid_json = False
            response = lean_invoke(
                {
                    "protocol_version": "0.1.0",
                    "request_id": sample_id,
                    "command": "parse_trace",
                    "payload": {"trace": raw_output},
                },
                executable,
            )
            result = response["result"]
            valid_schema = result.get("kind") == "TRACE_PARSED"
            failure_category = None
            if not valid_json:
                failure_category = "invalid_json"
            elif not valid_schema:
                failure_category = result.get("failure", {}).get("failure_code", "schema_reject")
            if failure_category:
                failures[failure_category] += 1
            rows.append(
                {
                    "sample_id": sample_id,
                    "problem_id": candidate["problem_id"],
                    "provider": PROVIDER,
                    "model": model,
                    "prompt_messages": messages,
                    "raw_output": raw_output,
                    "valid_json_trace": valid_json,
                    "valid_trace_schema": valid_schema,
                    "failure_category": failure_category,
                    "parser_result": result,
                }
            )
        except Exception as exc:
            failures["provider_error"] += 1
            rows.append(
                {
                    "sample_id": sample_id,
                    "problem_id": candidate["problem_id"],
                    "provider": PROVIDER,
                    "model": model,
                    "prompt_messages": messages,
                    "valid_json_trace": False,
                    "valid_trace_schema": False,
                    "failure_category": "provider_error",
                    "error": str(exc),
                }
            )
    total = len(rows)
    valid_json_count = sum(row["valid_json_trace"] for row in rows)
    valid_schema_count = sum(row["valid_trace_schema"] for row in rows)
    if total > 0 and valid_schema_count == total:
        status = "pass"
    elif valid_schema_count == 0:
        status = "fail"
    else:
        status = "partial"
    result = {
        "status": status,
        "diagnostic_only": True,
        "provider": PROVIDER,
        "model": model,
        "total_calls": total,
        "valid_json_traces": valid_json_count,
        "valid_json_trace_rate": valid_json_count / total if total else 0.0,
        "valid_trace_schemas": valid_schema_count,
        "valid_trace_schema_rate": valid_schema_count / total if total else 0.0,
        "common_trace_shape_failures": dict(failures.most_common()),
    }
    return result, rows


def run_trace_parser_gate(
    gate_a_dir: Path,
    reference_dir: Path,
    output: Path,
    seed: int,
    *,
    lean_invoke: Callable[[dict[str, Any], Path | None], dict[str, Any]] = _invoke_lean,
    provider_validate: bool = False,
    provider_call: Callable[[list[dict[str, str]], str], str] = call_provider,
    provider_model: str = DEFAULT_PROVIDER_MODEL,
) -> dict[str, Any]:
    references = _read_jsonl(reference_dir / "reference_solutions.jsonl")
    compiled = _read_jsonl(gate_a_dir / "compiled_problems.jsonl")
    problems = {row["problem_id"]: row for row in compiled}
    cases = _full_candidate_cases(references)
    cases.extend(_stepwise_cases(references, problems))
    cases.extend(_malformed_cases())

    output.mkdir(parents=True, exist_ok=True)
    trace_dir = output / "trace_json"
    if trace_dir.exists():
        shutil.rmtree(trace_dir)
    trace_dir.mkdir()
    executable = ROOT / ".lake" / "build" / "bin" / "sparse-ir-lean"
    executable_arg = executable if executable.is_file() else None

    trace_rows: list[dict[str, Any]] = []
    result_rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    coverage = {code: False for code in REQUIRED_ERROR_CODES}
    protocol_errors = 0
    full_count = 0
    stepwise_count = 0
    for case in cases:
        trace_path = trace_dir / f"{case.trace_id}.trace.json"
        trace_path.write_text(case.trace_text + "\n", encoding="utf-8")
        request = {
            "protocol_version": "0.1.0",
            "request_id": case.trace_id,
            "command": "parse_trace",
            "payload": {"trace": case.trace_text},
        }
        try:
            response = lean_invoke(request, executable_arg)
            result = response["result"]
        except Exception as exc:
            protocol_errors += 1
            result = {"kind": "PROTOCOL_ERROR", "message": str(exc)}
        passed = result.get("kind") == case.expected_kind
        if case.expected_kind == "TRACE_PARSED":
            passed = passed and result.get("problem_id") == case.problem_id
            passed = passed and result.get("trace_style") == case.expected_style
            passed = passed and result.get("op_count", 0) > 0
            if case.expected_style == "full_candidate" and passed:
                full_count += 1
            if case.expected_style == "stepwise" and passed:
                stepwise_count += 1
        else:
            failure = result.get("failure", {})
            passed = passed and failure.get("failure_code") == case.expected_code
            passed = passed and failure.get("path") == case.expected_path
            passed = passed and bool(failure.get("message"))
            if passed and case.expected_code in coverage:
                coverage[case.expected_code] = True
        trace_rows.append(
            {
                "trace_id": case.trace_id,
                "category": case.category,
                "problem_id": case.problem_id,
                "trace_path": _relative(trace_path),
                "expected_kind": case.expected_kind,
                "expected_code": case.expected_code,
                "expected_path": case.expected_path,
            }
        )
        result_rows.append({"trace_id": case.trace_id, "passed": passed, "result": result})
        if not passed:
            failures.append(
                {
                    "trace_id": case.trace_id,
                    "expected_kind": case.expected_kind,
                    "expected_code": case.expected_code,
                    "expected_path": case.expected_path,
                    "actual": result,
                }
            )

    if provider_validate:
        provider_validation, provider_rows = _provider_validation(
            references, executable_arg, lean_invoke, provider_call, provider_model
        )
        _write_jsonl(output / "provider_validation.jsonl", provider_rows)
    else:
        provider_validation = {
            "status": "blocked",
            "reason": "missing provider authorization/access",
            "diagnostic_only": True,
        }
        provider_path = output / "provider_validation.jsonl"
        if provider_path.exists():
            provider_path.unlink()
    status = (
        "pass"
        if not failures
        and protocol_errors == 0
        and full_count > 0
        and stepwise_count > 0
        and all(coverage.values())
        else "fail"
    )
    _write_jsonl(output / "traces.jsonl", trace_rows)
    _write_jsonl(output / "results.jsonl", result_rows)
    _write_jsonl(output / "failures.jsonl", failures)
    manifest = {
        "gate": "stage4_trace_parser",
        "status": status,
        "seed": seed,
        "total_traces": len(cases),
        "full_candidate_traces": full_count,
        "stepwise_traces": stepwise_count,
        "malformed_traces": len(_malformed_cases()),
        "parse_error_coverage": coverage,
        "total_protocol_error": protocol_errors,
        "failure_count": len(failures),
        "provider_validation": provider_validation,
        "replay_or_checking": False,
        "lean_solver_search": False,
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    examples = ["# Stage 4 trace-parser examples", ""]
    for row in result_rows[:6]:
        examples.extend(["```json", json.dumps(row, indent=2), "```", ""])
    (output / "examples.md").write_text("\n".join(examples), encoding="utf-8")
    provider_summary = (
        "BLOCKED by missing provider authorization/access"
        if provider_validation["status"] == "blocked"
        else (
            f"{provider_validation['status'].upper()} "
            f"({provider_validation['valid_json_traces']}/"
            f"{provider_validation['total_calls']} valid JSON; "
            f"{provider_validation['valid_trace_schemas']}/"
            f"{provider_validation['total_calls']} schema-valid)"
        )
    )
    summary = f"""# Stage 4 trace-parser gate

Status: **{status.upper()}**

- Traces: {len(cases)}
- Full-candidate traces: {full_count}
- Stepwise traces: {stepwise_count}
- Parse-error coverage: {sum(coverage.values())}/{len(coverage)}
- Protocol errors: {protocol_errors}
- Failures: {len(failures)}

Stage 4 core parser: {status.upper()}
Provider trace-shape validation: {provider_summary}

The core gate parses and lowers trace JSON only. Provider trace-shape diagnostics are
reported separately and do not replay operations, check trace correctness, score puzzle
answers, retry requests, or perform solver/search work in Lean.
"""
    (output / "summary.md").write_text(summary, encoding="utf-8")
    return manifest
