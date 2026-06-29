"""Provider validation for Stage 4 trace syntax features only."""

from __future__ import annotations

import json
import os
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable

from sparseir_harness.provider_diagnosis import extract_top_level_json, unexpected_field_paths
from sparseir_harness.trace_parser_gate import ROOT, _invoke_lean, _write_jsonl, call_provider


REQUIRED_FEATURES = (
    "assign_all",
    "place",
    "eliminate",
    "conclude",
    "justify",
    "justify_from",
    "mixed_traces",
)


FEATURE_OPS: dict[str, list[dict[str, Any]]] = {
    "assign_all": [
        {"op": "assign_all", "solution": {"Color": {"1": "red"}}},
        {"op": "conclude", "status": "solved"},
    ],
    "place": [
        {
            "op": "place",
            "cat": "Color",
            "house": 1,
            "val": "red",
            "justify": {"clue": "c1"},
        },
        {"op": "conclude", "status": "solved"},
    ],
    "eliminate": [
        {
            "op": "eliminate",
            "cat": "Drink",
            "house": 2,
            "val": "tea",
            "justify": {"clue": "c2"},
        },
        {"op": "conclude", "status": "solved"},
    ],
    "conclude": [{"op": "conclude", "status": "solved"}],
    "justify": [
        {
            "op": "place",
            "cat": "Pet",
            "house": 2,
            "val": "cat",
            "justify": {"clue": "c3"},
        },
        {"op": "conclude", "status": "solved"},
    ],
    "justify_from": [
        {
            "op": "eliminate",
            "cat": "Drink",
            "house": 1,
            "val": "coffee",
            "justify": {
                "clue": "c4",
                "from": [{"cat": "Color", "house": 2, "val": "blue"}],
            },
        },
        {"op": "conclude", "status": "solved"},
    ],
    "mixed_traces": [
        {
            "op": "place",
            "cat": "Color",
            "house": 1,
            "val": "red",
            "justify": {"clue": "c1"},
        },
        {
            "op": "eliminate",
            "cat": "Drink",
            "house": 2,
            "val": "tea",
            "justify": {
                "clue": "c2",
                "from": [{"cat": "Color", "house": 1, "val": "red"}],
            },
        },
        {"op": "conclude", "status": "solved"},
    ],
}


def feature_exemplar(feature: str) -> dict[str, Any]:
    return {
        "schema_version": "0.2",
        "problem_id": f"zl_{feature}_example",
        "ops": FEATURE_OPS[feature],
    }


def feature_prompt(feature: str, problem_id: str) -> list[dict[str, str]]:
    exemplar = feature_exemplar(feature)
    exemplar["problem_id"] = problem_id
    compact = json.dumps(exemplar, separators=(",", ":"), sort_keys=True)
    return [
        {
            "role": "system",
            "content": (
                "Return only one raw trace.json object. This tests JSON syntax only; do not prove "
                "or explain correctness. Use exactly the exemplar shape and values. Top-level keys "
                "must be exactly schema_version, problem_id, ops. Do not add wrappers, fields, "
                f"Markdown, or commentary. Feature: {feature}. Exemplar: {compact}"
            ),
        },
        {"role": "user", "content": f"Emit the {feature} trace for problem_id {problem_id}."},
    ]


def validation_status(
    total: int,
    trace_parsed: int,
    protocol_error: int,
    coverage: dict[str, int],
    pass_counts: dict[str, int],
) -> str:
    if total == 0:
        return "blocked"
    feature_pass = all(
        coverage.get(feature, 0) >= 20
        and pass_counts.get(feature, 0) / coverage[feature] >= 0.8
        for feature in REQUIRED_FEATURES
    )
    if total >= 140 and feature_pass and trace_parsed / total >= 0.8 and protocol_error == 0:
        return "pass"
    if trace_parsed == 0:
        return "fail"
    return "partial"


def _parse_trace(
    raw: str,
    sample_id: str,
    executable: Path | None,
    lean_invoke: Callable[[dict[str, Any], Path | None], dict[str, Any]],
) -> dict[str, Any]:
    return lean_invoke(
        {
            "protocol_version": "0.1.0",
            "request_id": sample_id,
            "command": "parse_trace",
            "payload": {"trace": raw},
        },
        executable,
    )["result"]


def run_feature_validation(
    stage4_dir: Path,
    output: Path,
    model: str,
    samples_per_feature: int,
    *,
    provider_call: Callable[[list[dict[str, str]], str], str] = call_provider,
    lean_invoke: Callable[[dict[str, Any], Path | None], dict[str, Any]] = _invoke_lean,
    require_access: bool = True,
) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    if require_access and not os.environ.get("OPENROUTER_API_KEY"):
        manifest = {
            "provider_validation_status": "blocked",
            "model": model,
            "total_samples": 0,
            "valid_json": 0,
            "trace_parsed": 0,
            "schema_invalid": 0,
            "provider_output_not_json": 0,
            "protocol_error": 0,
            "feature_coverage": {},
            "feature_pass_counts": {},
            "failure_codes": {},
        }
        (output / "manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        return manifest

    executable = ROOT / ".lake" / "build" / "bin" / "sparse-ir-lean"
    executable_arg = executable if executable.is_file() else None
    prompt_rows: list[dict[str, Any]] = []
    tasks: list[tuple[int, str, str, str, list[dict[str, str]]]] = []
    task_index = 0
    for feature in REQUIRED_FEATURES:
        for index in range(samples_per_feature):
            sample_id = f"{feature}-{index:03d}"
            problem_id = f"zl_stage4_{feature}_{index:03d}"
            messages = feature_prompt(feature, problem_id)
            tasks.append((task_index, sample_id, feature, problem_id, messages))
            prompt_rows.append(
                {
                    "sample_id": sample_id,
                    "feature": feature,
                    "problem_id": problem_id,
                    "model": model,
                    "messages": messages,
                }
            )
            task_index += 1

    provider_results: dict[int, tuple[str | None, str | None]] = {}
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {
            executor.submit(provider_call, messages, model): index
            for index, _sample, _feature, _problem, messages in tasks
        }
        for future in as_completed(futures):
            index = futures[future]
            try:
                provider_results[index] = (future.result(), None)
            except Exception as exc:
                provider_results[index] = (None, str(exc))

    raw_rows: list[dict[str, Any]] = []
    extracted_rows: list[dict[str, Any]] = []
    parse_rows: list[dict[str, Any]] = []
    unexpected_rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    coverage: Counter[str] = Counter()
    pass_counts: Counter[str] = Counter()
    failure_codes: Counter[str] = Counter()
    valid_json = trace_parsed = schema_invalid = not_json = protocol_errors = 0
    for index, sample_id, feature, problem_id, _messages in tasks:
        coverage[feature] += 1
        raw, provider_error = provider_results[index]
        raw_row = {
            "sample_id": sample_id,
            "feature": feature,
            "problem_id": problem_id,
            "model": model,
        }
        if provider_error is not None:
            raw_row["provider_error"] = provider_error
            raw_rows.append(raw_row)
            not_json += 1
            failure_codes["provider_error"] += 1
            failures.append({**raw_row, "failure_code": "provider_error"})
            continue
        assert raw is not None
        raw_row["raw_output"] = raw
        raw_rows.append(raw_row)
        extraction = extract_top_level_json(raw)
        extracted = extraction["extracted_json"]
        exact_keys = isinstance(extracted, dict) and set(extracted) == {
            "schema_version",
            "problem_id",
            "ops",
        }
        extracted_rows.append(
            {
                "sample_id": sample_id,
                "feature": feature,
                "status": extraction["status"],
                "exact_top_level_keys": exact_keys,
                "extracted_json": extracted,
            }
        )
        if extraction["status"] in {"invalid_json", "extraction_failure"}:
            not_json += 1
        else:
            valid_json += 1
        paths = unexpected_field_paths(extracted) if isinstance(extracted, dict) else []
        for path in paths:
            unexpected_rows.append(
                {"sample_id": sample_id, "feature": feature, "path": path}
            )
        try:
            result = _parse_trace(raw, sample_id, executable_arg, lean_invoke)
        except Exception as exc:
            protocol_errors += 1
            failure_codes["protocol_error"] += 1
            failures.append(
                {"sample_id": sample_id, "feature": feature, "failure_code": "protocol_error", "message": str(exc)}
            )
            continue
        passed = result.get("kind") == "TRACE_PARSED"
        parse_rows.append(
            {"sample_id": sample_id, "feature": feature, "passed": passed, "result": result}
        )
        if passed:
            trace_parsed += 1
            pass_counts[feature] += 1
        else:
            schema_invalid += 1
            code = result.get("failure", {}).get("failure_code", "schema_invalid")
            failure_codes[code] += 1
            failures.append(
                {"sample_id": sample_id, "feature": feature, "failure_code": code, "result": result}
            )

    total = len(tasks)
    status = validation_status(total, trace_parsed, protocol_errors, coverage, pass_counts)
    matrix = {
        feature: {
            "samples": coverage[feature],
            "trace_parsed": pass_counts[feature],
            "parse_rate": pass_counts[feature] / coverage[feature],
            "exemplar": feature_exemplar(feature),
        }
        for feature in REQUIRED_FEATURES
    }
    manifest = {
        "provider_validation_status": status,
        "model": model,
        "total_samples": total,
        "valid_json": valid_json,
        "trace_parsed": trace_parsed,
        "schema_invalid": schema_invalid,
        "provider_output_not_json": not_json,
        "protocol_error": protocol_errors,
        "feature_coverage": dict(coverage),
        "feature_pass_counts": dict(pass_counts),
        "failure_codes": dict(failure_codes),
    }
    _write_jsonl(output / "prompts.jsonl", prompt_rows)
    _write_jsonl(output / "raw_outputs.jsonl", raw_rows)
    _write_jsonl(output / "extracted_json.jsonl", extracted_rows)
    _write_jsonl(output / "parse_results.jsonl", parse_rows)
    _write_jsonl(output / "unexpected_fields.jsonl", unexpected_rows)
    _write_jsonl(output / "failures.jsonl", failures)
    (output / "feature_matrix.json").write_text(
        json.dumps(matrix, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    examples = ["# Stage 4 provider syntax examples", ""]
    for row in parse_rows[:7]:
        examples.extend(["```json", json.dumps(row, indent=2), "```", ""])
    (output / "examples.md").write_text("\n".join(examples), encoding="utf-8")
    summary = f"""# Stage 4 provider feature validation

Status: **{status.upper()}**

- Model: `{model}`
- Samples: {total}
- Valid JSON: {valid_json}/{total}
- TRACE_PARSED: {trace_parsed}/{total}
- Schema invalid: {schema_invalid}
- Provider output not JSON: {not_json}
- Protocol errors: {protocol_errors}

Success means only that provider output parsed as the requested trace syntax. No trace was
replayed or scored for semantic correctness, proof validity, or solved-state acceptance.
"""
    (output / "summary.md").write_text(summary, encoding="utf-8")

    stage4_manifest_path = stage4_dir / "manifest.json"
    stage4_manifest = json.loads(stage4_manifest_path.read_text(encoding="utf-8"))
    stage4_manifest["provider_validation"] = {
        "status": status,
        "model": model,
        "total_samples": total,
        "trace_parsed": trace_parsed,
        "trace_parsed_rate": trace_parsed / total,
        "parseability_only": True,
        "artifact_path": "provider_validation",
    }
    stage4_manifest_path.write_text(
        json.dumps(stage4_manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    stage4_summary_path = stage4_dir / "summary.md"
    stage4_summary_lines = stage4_summary_path.read_text(encoding="utf-8").splitlines()
    provider_line = (
        f"Provider trace-shape validation: {status.upper()} "
        f"({trace_parsed}/{total} TRACE_PARSED; parseability only)"
    )
    stage4_summary_lines = [
        provider_line if line.startswith("Provider trace-shape validation:") else line
        for line in stage4_summary_lines
    ]
    stage4_summary_path.write_text(
        "\n".join(stage4_summary_lines) + "\n", encoding="utf-8"
    )
    return manifest
