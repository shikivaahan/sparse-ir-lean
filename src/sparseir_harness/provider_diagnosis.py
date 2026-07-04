"""Diagnose Stage 4 provider trace-shape validation without replay or scoring."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable

from sparseir_harness.trace_parser_gate import (
    DEFAULT_PROVIDER_MODEL,
    ROOT,
    TRACE_PROMPT_EXEMPLAR,
    _invoke_lean,
    _read_jsonl,
    _write_jsonl,
    build_provider_messages,
    call_provider,
)


OLD_SYSTEM_PROMPT = (
    "Return only one JSON trace object. Use schema_version 0.2, the supplied "
    "problem_id, an assign_all operation containing the supplied solution, and "
    "a conclude operation with status solved. Do not use Markdown fences."
)
TOP_LEVEL_KEYS = {"schema_version", "problem_id", "ops"}


def old_provider_messages(problem_id: str, solution: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": OLD_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": json.dumps(
                {"problem_id": problem_id, "solution": solution}, sort_keys=True
            ),
        },
    ]


def provider_validation_status(total: int, schema_valid: int) -> str:
    if total > 0 and schema_valid == total:
        return "pass"
    if schema_valid == 0:
        return "fail"
    return "partial"


def score_expected_parser_outcome(
    result: dict[str, Any], expected_kind: str, expected_code: str | None = None
) -> dict[str, Any]:
    actual_kind = result.get("kind")
    actual_code = result.get("failure", {}).get("failure_code")
    passed = actual_kind == expected_kind and (
        expected_code is None or actual_code == expected_code
    )
    return {
        "passed": passed,
        "expected_kind": expected_kind,
        "expected_code": expected_code,
        "actual_kind": actual_kind,
        "actual_code": actual_code,
    }


def extract_top_level_json(raw_output: str) -> dict[str, Any]:
    try:
        value = json.loads(raw_output)
    except json.JSONDecodeError as exc:
        return {
            "status": "invalid_json",
            "extracted_json": None,
            "message": str(exc),
        }
    if not isinstance(value, dict):
        return {
            "status": "extraction_failure",
            "extracted_json": None,
            "message": "top-level JSON value is not an object",
        }
    wrapper_fields = [
        key
        for key, nested in value.items()
        if isinstance(nested, dict) and TOP_LEVEL_KEYS.issubset(nested)
    ]
    if wrapper_fields and not TOP_LEVEL_KEYS.issubset(value):
        return {
            "status": "unexpected_wrapper_object",
            "extracted_json": value,
            "wrapper_fields": wrapper_fields,
        }
    return {"status": "top_level_object", "extracted_json": value}


def _operation_allowed_fields(operation: dict[str, Any]) -> set[str]:
    return {
        "assign_all": {"op", "solution"},
        "place": {"op", "cat", "house", "val", "justify"},
        "eliminate": {"op", "cat", "house", "val", "justify"},
        "conclude": {"op", "status", "solution"},
    }.get(operation.get("op"), {"op"})


def _nested_field_paths(value: Any, path: str) -> list[str]:
    paths: list[str] = []
    if isinstance(value, dict):
        for key, nested in value.items():
            child = f"{path}.{key}"
            paths.append(child)
            if key not in {"solution", "assignment", "assignments"}:
                paths.extend(_nested_field_paths(nested, child))
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            paths.extend(_nested_field_paths(nested, f"{path}[{index}]"))
    return paths


def unexpected_field_paths(value: dict[str, Any]) -> list[str]:
    paths: list[str] = []
    for key, nested in value.items():
        if key not in TOP_LEVEL_KEYS:
            path = f"$.{key}"
            paths.append(path)
            paths.extend(_nested_field_paths(nested, path))
    operations = value.get("ops")
    if not isinstance(operations, list):
        return sorted(paths)
    for index, operation in enumerate(operations):
        if not isinstance(operation, dict):
            continue
        op_path = f"$.ops[{index}]"
        allowed = _operation_allowed_fields(operation)
        paths.extend(f"{op_path}.{key}" for key in operation if key not in allowed)
        justify = operation.get("justify")
        if isinstance(justify, dict):
            paths.extend(
                f"{op_path}.justify.{key}"
                for key in justify
                if key not in {"clue", "from"}
            )
            from_cells = justify.get("from")
            if isinstance(from_cells, list):
                for cell_index, cell in enumerate(from_cells):
                    if isinstance(cell, dict):
                        paths.extend(
                            f"{op_path}.justify.from[{cell_index}].{key}"
                            for key in cell
                            if key not in {"cat", "house", "val"}
                        )
    return sorted(paths)


def remove_only_unexpected_fields(value: dict[str, Any]) -> dict[str, Any]:
    normalized = {key: deepcopy(item) for key, item in value.items() if key in TOP_LEVEL_KEYS}
    operations = normalized.get("ops")
    if not isinstance(operations, list):
        return normalized
    filtered_operations: list[Any] = []
    for operation in operations:
        if not isinstance(operation, dict):
            filtered_operations.append(operation)
            continue
        allowed = _operation_allowed_fields(operation)
        filtered = {key: deepcopy(item) for key, item in operation.items() if key in allowed}
        justify = filtered.get("justify")
        if isinstance(justify, dict):
            filtered_justify = {
                key: deepcopy(item) for key, item in justify.items() if key in {"clue", "from"}
            }
            from_cells = filtered_justify.get("from")
            if isinstance(from_cells, list):
                filtered_justify["from"] = [
                    {key: deepcopy(item) for key, item in cell.items() if key in {"cat", "house", "val"}}
                    if isinstance(cell, dict)
                    else cell
                    for cell in from_cells
                ]
            filtered["justify"] = filtered_justify
        filtered_operations.append(filtered)
    normalized["ops"] = filtered_operations
    return normalized


def _trace_path(stage4_dir: Path, row: dict[str, Any]) -> Path:
    path = Path(row["trace_path"])
    if path.is_absolute():
        return path
    root_path = ROOT / path
    if root_path.is_file():
        return root_path
    return stage4_dir / "trace_json" / Path(row["trace_path"]).name


def _parse_trace(
    trace_text: str,
    request_id: str,
    executable: Path | None,
    lean_invoke: Callable[[dict[str, Any], Path | None], dict[str, Any]],
) -> dict[str, Any]:
    response = lean_invoke(
        {
            "protocol_version": "0.1.0",
            "request_id": request_id,
            "command": "parse_trace",
            "payload": {"trace": trace_text},
        },
        executable,
    )
    return response["result"]


def _update_stage4_summary(
    stage4_dir: Path, provider_summary: dict[str, Any], rows: list[dict[str, Any]], output: Path
) -> None:
    manifest_path = stage4_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["provider_validation"] = {
        **provider_summary,
        "diagnosis_path": output.relative_to(stage4_dir).as_posix(),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _write_jsonl(stage4_dir / "provider_validation.jsonl", rows)
    summary_path = stage4_dir / "summary.md"
    lines = summary_path.read_text(encoding="utf-8").splitlines()
    replacement = (
        f"Provider trace-shape validation: {provider_summary['status'].upper()} "
        f"({provider_summary['valid_json']}/{provider_summary['total_provider_calls']} valid JSON; "
        f"{provider_summary['schema_valid']}/{provider_summary['total_provider_calls']} schema-valid)"
    )
    lines = [replacement if line.startswith("Provider trace-shape validation:") else line for line in lines]
    summary_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_provider_diagnosis(
    stage4_dir: Path,
    output: Path,
    model: str = DEFAULT_PROVIDER_MODEL,
    samples: int = 20,
    *,
    provider_call: Callable[[list[dict[str, str]], str], str] = call_provider,
    lean_invoke: Callable[[dict[str, Any], Path | None], dict[str, Any]] = _invoke_lean,
) -> dict[str, Any]:
    trace_rows = [
        row
        for row in _read_jsonl(stage4_dir / "traces.jsonl")
        if row["category"] == "valid_full_candidate"
    ]
    if samples < 1 or samples > len(trace_rows):
        raise ValueError(f"samples must be between 1 and {len(trace_rows)}")
    selected: list[tuple[dict[str, Any], dict[str, Any]]] = []
    by_problem: dict[str, dict[str, Any]] = {}
    for row in trace_rows:
        trace = json.loads(_trace_path(stage4_dir, row).read_text(encoding="utf-8"))
        by_problem[trace["problem_id"]] = trace
        if len(selected) < samples:
            selected.append((row, trace))

    executable = ROOT / ".lake" / "build" / "bin" / "sparse-ir-lean"
    executable_arg = executable if executable.is_file() else None
    old_manifest = json.loads((stage4_dir / "manifest.json").read_text(encoding="utf-8"))
    old_provider_status = old_manifest["provider_validation"].get("status")
    prior_raw_path = output / "raw_outputs.jsonl"
    prior_prompt_path = output / "prompts.jsonl"
    if prior_raw_path.is_file() and prior_prompt_path.is_file():
        prior_prompts = {
            row["sample_id"]: row["messages"]
            for row in _read_jsonl(prior_prompt_path)
            if row["phase"] == "before"
        }
        baseline_rows = [
            {
                "sample_id": row["sample_id"],
                "problem_id": row["problem_id"],
                "raw_output": row["raw_output"],
                "prompt_messages": prior_prompts[row["sample_id"]],
            }
            for row in _read_jsonl(prior_raw_path)
            if row["phase"] == "before"
        ]
        prior_manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
        if "scorer_bug" in prior_manifest.get("root_cause", []):
            old_provider_status = "complete"
    else:
        baseline_rows = _read_jsonl(stage4_dir / "provider_validation.jsonl")

    prompt_rows: list[dict[str, Any]] = []
    raw_rows: list[dict[str, Any]] = []
    extracted_rows: list[dict[str, Any]] = []
    parse_rows: list[dict[str, Any]] = []
    unexpected_rows: list[dict[str, Any]] = []
    normalized_rows: list[dict[str, Any]] = []

    def inspect_output(
        phase: str,
        sample_id: str,
        problem_id: str,
        raw_output: str,
        messages: list[dict[str, str]],
    ) -> dict[str, Any]:
        prompt_rows.append(
            {
                "phase": phase,
                "sample_id": sample_id,
                "problem_id": problem_id,
                "model": model,
                "messages": messages,
            }
        )
        raw_rows.append(
            {
                "phase": phase,
                "sample_id": sample_id,
                "problem_id": problem_id,
                "model": model,
                "raw_output": raw_output,
            }
        )
        extraction = extract_top_level_json(raw_output)
        extracted = extraction["extracted_json"]
        extracted_rows.append(
            {
                "phase": phase,
                "sample_id": sample_id,
                "problem_id": problem_id,
                **extraction,
            }
        )
        result = _parse_trace(raw_output, sample_id, executable_arg, lean_invoke)
        score = score_expected_parser_outcome(result, "TRACE_PARSED")
        parse_rows.append(
            {
                "phase": phase,
                "sample_id": sample_id,
                "problem_id": problem_id,
                "result": result,
                "score": score,
            }
        )
        paths = unexpected_field_paths(extracted) if isinstance(extracted, dict) else []
        for path in paths:
            unexpected_rows.append(
                {
                    "phase": phase,
                    "sample_id": sample_id,
                    "problem_id": problem_id,
                    "path": path,
                    "field": path.rsplit(".", 1)[-1],
                }
            )
        if isinstance(extracted, dict) and paths:
            normalized = remove_only_unexpected_fields(extracted)
            normalized_result = _parse_trace(
                json.dumps(normalized, separators=(",", ":")),
                f"{sample_id}-normalized",
                executable_arg,
                lean_invoke,
            )
            normalized_rows.append(
                {
                    "phase": phase,
                    "sample_id": sample_id,
                    "removed_paths": paths,
                    "normalized_json": normalized,
                    "result": normalized_result,
                }
            )
        return {
            "valid_json": extraction["status"] not in {"invalid_json", "extraction_failure"},
            "schema_valid": score["passed"],
            "extraction_status": extraction["status"],
            "result": result,
            "unexpected_paths": paths,
        }

    baseline_inspections: list[dict[str, Any]] = []
    for row in baseline_rows:
        trace = by_problem[row["problem_id"]]
        messages = row.get("prompt_messages") or old_provider_messages(
            trace["problem_id"], trace["ops"][0]["solution"]
        )
        baseline_inspections.append(
            inspect_output(
                "before",
                row["sample_id"],
                row["problem_id"],
                row["raw_output"],
                messages,
            )
        )

    after_inspections: list[dict[str, Any]] = []
    provider_rows: list[dict[str, Any]] = []
    for index, (_row, trace) in enumerate(selected):
        sample_id = f"diagnosis-{index:03d}"
        messages = build_provider_messages(trace["problem_id"], trace["ops"][0]["solution"])
        try:
            raw_output = provider_call(messages, model)
            inspection = inspect_output(
                "after_fix", sample_id, trace["problem_id"], raw_output, messages
            )
            provider_rows.append(
                {
                    "sample_id": sample_id,
                    "problem_id": trace["problem_id"],
                    "provider": "openrouter",
                    "model": model,
                    "prompt_messages": messages,
                    "raw_output": raw_output,
                    "valid_json_trace": inspection["valid_json"],
                    "valid_trace_schema": inspection["schema_valid"],
                    "failure_category": None
                    if inspection["schema_valid"]
                    else inspection["result"].get("failure", {}).get(
                        "failure_code", inspection["extraction_status"]
                    ),
                    "parser_result": inspection["result"],
                }
            )
        except Exception as exc:
            inspection = {
                "valid_json": False,
                "schema_valid": False,
                "extraction_status": "provider_error",
                "result": {"kind": "PROVIDER_ERROR", "message": str(exc)},
                "unexpected_paths": [],
            }
            prompt_rows.append(
                {
                    "phase": "after_fix",
                    "sample_id": sample_id,
                    "problem_id": trace["problem_id"],
                    "model": model,
                    "messages": messages,
                }
            )
            raw_rows.append(
                {
                    "phase": "after_fix",
                    "sample_id": sample_id,
                    "problem_id": trace["problem_id"],
                    "model": model,
                    "provider_error": str(exc),
                }
            )
            provider_rows.append(
                {
                    "sample_id": sample_id,
                    "problem_id": trace["problem_id"],
                    "provider": "openrouter",
                    "model": model,
                    "prompt_messages": messages,
                    "valid_json_trace": False,
                    "valid_trace_schema": False,
                    "failure_category": "provider_error",
                    "error": str(exc),
                }
            )
        after_inspections.append(inspection)

    exemplar_text = json.dumps(TRACE_PROMPT_EXEMPLAR, separators=(",", ":"))
    exemplar_result = _parse_trace(
        exemplar_text, "prompt-exemplar", executable_arg, lean_invoke
    )
    exemplar_rows = [
        {
            "exemplar": TRACE_PROMPT_EXEMPLAR,
            "result": exemplar_result,
            "passed": exemplar_result.get("kind") == "TRACE_PARSED",
        }
    ]

    valid_json = sum(row["valid_json"] for row in after_inspections)
    schema_valid = sum(row["schema_valid"] for row in after_inspections)
    unexpected_failures = sum(bool(row["unexpected_paths"]) for row in after_inspections)
    wrapper_failures = sum(
        row["extraction_status"] == "unexpected_wrapper_object" for row in after_inspections
    )
    extraction_failures = sum(
        row["extraction_status"] in {"invalid_json", "extraction_failure", "provider_error"}
        for row in after_inspections
    )
    prompt_failures = sum(not row["passed"] for row in exemplar_rows)
    after_status = provider_validation_status(samples, schema_valid)

    root_causes = ["prompt_contract_mismatch", "provider_added_extra_fields"]
    if old_provider_status == "complete" and not any(
        row["schema_valid"] for row in baseline_inspections
    ):
        root_causes.append("scorer_bug")
    if after_status != "pass":
        root_causes.append("model_noncompliance")
    fixed = after_status == "pass" and prompt_failures == 0
    status = "pass" if fixed else after_status
    manifest = {
        "status": status,
        "model_primary": model,
        "model_secondary": None,
        "total_provider_calls": samples,
        "valid_json": valid_json,
        "schema_valid": schema_valid,
        "unexpected_field_failures": unexpected_failures,
        "wrapper_failures": wrapper_failures,
        "prompt_exemplar_parse_failures": prompt_failures,
        "extraction_failures": extraction_failures,
        "root_cause": root_causes,
        "fixed": fixed,
    }

    output.mkdir(parents=True, exist_ok=True)
    _write_jsonl(output / "prompts.jsonl", prompt_rows)
    _write_jsonl(output / "raw_outputs.jsonl", raw_rows)
    _write_jsonl(output / "extracted_json.jsonl", extracted_rows)
    _write_jsonl(output / "parse_results.jsonl", parse_rows)
    _write_jsonl(output / "unexpected_fields.jsonl", unexpected_rows)
    _write_jsonl(output / "prompt_exemplar_parse_results.jsonl", exemplar_rows)
    _write_jsonl(output / "normalized_reparse_results.jsonl", normalized_rows)
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    before_unexpected = sorted(
        {path for row in baseline_inspections for path in row["unexpected_paths"]}
    )
    before_normalized = [
        row["result"].get("failure", {}).get("failure_code", row["result"].get("kind"))
        for row in normalized_rows
        if row["phase"] == "before"
    ]
    root_cause = f"""# Stage 4 provider root cause

## Proven cause

- `prompt_contract_mismatch`: the original system prompt named semantic operations but never
  specified the required `ops`, `op`, and operation payload keys and supplied no exemplar.
- `provider_added_extra_fields`: all baseline outputs used `operations` at `$.operations`;
  nested objects also used variants such as `type`, `assignment`, or `assignments`.
- `scorer_bug`: the original reporter labeled 0/3 schema-valid as `complete` instead of `fail`.

The unexpected baseline paths were: {json.dumps(before_unexpected)}. Removing only those
unexpected fields did not make the output valid; normalized reparses produced
{json.dumps(before_normalized)} because the required `ops` field was still absent.

## Ruled out

- The extracted top-level objects were the intended trace objects, not wrappers.
- The original prompt did not contain `operations`, `type`, `assignment`, or `assignments`.
- The protocol schema documents `parse_trace` and `TRACE_PARSED` but contains no conflicting
  trace-input shape, and no repository schema or prompt example uses the old field names.
- The Lean parser matches the Stage 4 trace contract and remained unchanged.
- The corrected prompt exemplar parses through Lean `parse_trace`.
- No reasoning mode or reasoning-trace request was used.

## Fix

The provider prompt now gives exact allowed keys, a Lean-validated exemplar, and explicit
raw-object/no-wrapper requirements. Reporting now uses `fail` for zero schema-valid outputs,
`partial` for mixed results, and `pass` only when every requested sample is schema-valid.
"""
    (output / "root_cause.md").write_text(root_cause, encoding="utf-8")
    summary = f"""# Stage 4 provider diagnosis

Status: **{status.upper()}**

- Primary model: `{model}`
- Baseline: 3/3 valid JSON, 0/3 schema-valid
- After fix: {valid_json}/{samples} valid JSON, {schema_valid}/{samples} schema-valid
- Unexpected-field failures after fix: {unexpected_failures}
- Wrapper failures after fix: {wrapper_failures}
- Extraction failures after fix: {extraction_failures}
- Prompt exemplar failures: {prompt_failures}
- Fixed: {str(fixed).lower()}

This is trace-shape validation only. It does not score puzzle correctness, replay traces,
request reasoning, retry calls, or run solver/search in Lean.
"""
    (output / "summary.md").write_text(summary, encoding="utf-8")
    provider_summary = {
        "status": after_status,
        "diagnostic_only": True,
        "provider": "openrouter",
        "model": model,
        "total_provider_calls": samples,
        "valid_json": valid_json,
        "valid_json_rate": valid_json / samples,
        "schema_valid": schema_valid,
        "schema_valid_rate": schema_valid / samples,
        "unexpected_field_failures": unexpected_failures,
        "wrapper_failures": wrapper_failures,
        "extraction_failures": extraction_failures,
    }
    _update_stage4_summary(stage4_dir, provider_summary, provider_rows, output)
    return manifest
