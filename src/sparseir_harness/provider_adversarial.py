"""Stage 4 provider-backed positive and adversarial trace parser validation."""

from __future__ import annotations

import json
import os
import random
import shutil
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable

from sparseir_harness.provider_diagnosis import extract_top_level_json, unexpected_field_paths
from sparseir_harness.provider_feature_validation import FEATURE_OPS
from sparseir_harness.trace_parser_gate import ROOT, _invoke_lean, _write_jsonl, call_provider


POSITIVE_BUCKETS = {
    "valid_assign_all": "assign_all",
    "valid_place": "place",
    "valid_eliminate": "eliminate",
    "valid_conclude": "conclude",
    "valid_justify": "justify",
    "valid_justify_from": "justify_from",
    "valid_mixed_trace": "mixed_traces",
}

ADVERSARIAL_EXPECTATIONS: dict[str, tuple[str, str]] = {
    "missing_ops": ("missing_ops", "$.ops"),
    "unknown_op": ("unknown_op", "$.ops[0].op"),
    "unexpected_top_level_field": ("unexpected_field", "$.extra"),
    "malformed_assign_all_solution": (
        "assign_all_malformed_solution",
        "$.ops[0].solution",
    ),
    "missing_justify": ("missing_justify", "$.ops[0].justify"),
    "malformed_justify": ("malformed_justify", "$.ops[0].justify"),
    "malformed_justify_from": ("malformed_from_cell", "$.ops[0].justify.from"),
    "bad_conclude_status": ("conclude_bad_status", "$.ops[0].status"),
    "wrapper_object": ("unexpected_wrapper_object", "$.trace"),
    "missing_schema_version": ("missing_schema_version", "$.schema_version"),
    "unsupported_schema_version": ("unsupported_schema_version", "$.schema_version"),
    "missing_problem_id": ("missing_problem_id", "$.problem_id"),
}


def _trace(problem_id: str, ops: list[dict[str, Any]]) -> dict[str, Any]:
    return {"schema_version": "0.2", "problem_id": problem_id, "ops": deepcopy(ops)}


def _relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def bucket_exemplar(bucket: str, problem_id: str) -> dict[str, Any]:
    if bucket in POSITIVE_BUCKETS:
        return _trace(problem_id, FEATURE_OPS[POSITIVE_BUCKETS[bucket]])
    base = _trace(problem_id, [{"op": "conclude", "status": "solved"}])
    if bucket == "missing_ops":
        base.pop("ops")
    elif bucket == "unknown_op":
        base["ops"] = [{"op": "guess"}]
    elif bucket == "unexpected_top_level_field":
        base["extra"] = True
    elif bucket == "malformed_assign_all_solution":
        base["ops"] = [{"op": "assign_all", "solution": []}]
    elif bucket == "missing_justify":
        base["ops"] = [{"op": "place", "cat": "Color", "house": 1, "val": "red"}]
    elif bucket == "malformed_justify":
        base["ops"] = [
            {"op": "place", "cat": "Color", "house": 1, "val": "red", "justify": []}
        ]
    elif bucket == "malformed_justify_from":
        base["ops"] = [
            {
                "op": "eliminate",
                "cat": "Drink",
                "house": 1,
                "val": "tea",
                "justify": {"clue": "c1", "from": {}},
            }
        ]
    elif bucket == "bad_conclude_status":
        base["ops"] = [{"op": "conclude", "status": "unknown"}]
    elif bucket == "wrapper_object":
        base = {"trace": base}
    elif bucket == "missing_schema_version":
        base.pop("schema_version")
    elif bucket == "unsupported_schema_version":
        base["schema_version"] = "9"
    elif bucket == "missing_problem_id":
        base.pop("problem_id")
    else:
        raise KeyError(bucket)
    return base


def bucket_prompt(bucket: str, problem_id: str, adversarial: bool) -> list[dict[str, str]]:
    exemplar = bucket_exemplar(bucket, problem_id)
    compact = json.dumps(exemplar, separators=(",", ":"), sort_keys=True)
    purpose = (
        "Emit the deliberately malformed exemplar exactly. The expected successful outcome for "
        "this test is a structured parser rejection; do not repair it."
        if adversarial
        else "Emit the valid exemplar exactly. The expected outcome is TRACE_PARSED."
    )
    return [
        {
            "role": "system",
            "content": (
                "Return only one raw JSON object with no Markdown, commentary, or "
                "reasoning. This tests parser behavior only, never trace correctness. "
                f"{purpose} Bucket: {bucket}. Exemplar: {compact}"
            ),
        },
        {"role": "user", "content": f"Emit exactly the {bucket} exemplar for {problem_id}."},
    ]


def score_sample(
    adversarial: bool,
    bucket: str,
    model_complied: bool,
    extraction_status: str,
    lean_result: dict[str, Any],
) -> dict[str, Any]:
    actual_code = lean_result.get("failure", {}).get("failure_code")
    actual_path = lean_result.get("failure", {}).get("path")
    if not adversarial:
        passed = lean_result.get("kind") == "TRACE_PARSED"
        expected_code = expected_path = None
    else:
        expected_code, expected_path = ADVERSARIAL_EXPECTATIONS[bucket]
        if bucket == "wrapper_object":
            expected = (
                extraction_status == "unexpected_wrapper_object"
                and lean_result.get("kind") == "REJECT"
            )
        else:
            expected = (
                lean_result.get("kind") == "REJECT"
                and actual_code == expected_code
                and actual_path == expected_path
            )
        passed = model_complied and expected
    return {
        "passed": passed,
        "model_complied": model_complied,
        "expected_result": "parse_rejection" if adversarial else "TRACE_PARSED",
        "expected_code": expected_code,
        "expected_path": expected_path,
        "actual_kind": lean_result.get("kind"),
        "actual_code": actual_code,
        "actual_path": actual_path,
    }


def gate_status(
    positive_total: int,
    positive_passed: int,
    adversarial_total: int,
    adversarial_passed: int,
    protocol_error: int,
    coverage: dict[str, int],
    pass_counts: dict[str, int],
) -> str:
    if positive_total + adversarial_total == 0:
        return "blocked"
    positive_ok = all(
        coverage.get(bucket, 0) >= 20
        and pass_counts.get(bucket, 0) / coverage[bucket] >= 0.8
        for bucket in POSITIVE_BUCKETS
    )
    adversarial_ok = all(
        coverage.get(bucket, 0) >= 10
        and pass_counts.get(bucket, 0) / coverage[bucket] >= 0.8
        for bucket in ADVERSARIAL_EXPECTATIONS
    )
    if (
        positive_total >= 140
        and adversarial_total >= 120
        and positive_ok
        and adversarial_ok
        and positive_passed / positive_total >= 0.8
        and adversarial_passed / adversarial_total >= 0.8
        and protocol_error == 0
    ):
        return "pass"
    if positive_passed + adversarial_passed == 0:
        return "fail"
    return "partial"


def run_provider_adversarial(
    stage4_dir: Path,
    output: Path,
    model: str,
    positive_samples_per_feature: int,
    adversarial_samples_per_feature: int,
    seed: int,
    *,
    provider_call: Callable[[list[dict[str, str]], str], str] = call_provider,
    lean_invoke: Callable[[dict[str, Any], Path | None], dict[str, Any]] = _invoke_lean,
    require_access: bool = True,
) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    trace_dir = output / "trace_json"
    if trace_dir.exists():
        shutil.rmtree(trace_dir)
    trace_dir.mkdir()
    buckets = [(bucket, False) for bucket in POSITIVE_BUCKETS] + [
        (bucket, True) for bucket in ADVERSARIAL_EXPECTATIONS
    ]
    if require_access and not os.environ.get("OPENROUTER_API_KEY"):
        manifest = {
            "stage": "stage4_provider_adversarial",
            "status": "blocked",
            "model": model,
            "total_samples": 0,
            "positive_samples": 0,
            "adversarial_samples": 0,
            "valid_json": 0,
            "trace_parsed": 0,
            "parse_rejected": 0,
            "expected_rejections": 0,
            "unexpected_accepts": 0,
            "unexpected_rejections": 0,
            "protocol_error": 0,
            "feature_coverage": {},
            "feature_pass_counts": {},
            "parse_error_coverage": {},
            "failure_codes": {},
        }
        (output / "manifest.json").write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
        )
        return manifest

    random.seed(seed)
    tasks: list[dict[str, Any]] = []
    prompt_rows: list[dict[str, Any]] = []
    task_index = 0
    for bucket, adversarial in buckets:
        count = adversarial_samples_per_feature if adversarial else positive_samples_per_feature
        for index in range(count):
            sample_id = f"{bucket}-{index:03d}"
            problem_id = f"zl_stage4_{bucket}_{index:03d}"
            exemplar = bucket_exemplar(bucket, problem_id)
            messages = bucket_prompt(bucket, problem_id, adversarial)
            task = {
                "index": task_index,
                "sample_id": sample_id,
                "bucket": bucket,
                "adversarial": adversarial,
                "problem_id": problem_id,
                "exemplar": exemplar,
                "messages": messages,
            }
            tasks.append(task)
            prompt_rows.append(
                {
                    "sample_id": sample_id,
                    "bucket": bucket,
                    "adversarial": adversarial,
                    "model": model,
                    "messages": messages,
                    "expected_result": "parse_rejection" if adversarial else "TRACE_PARSED",
                }
            )
            task_index += 1

    provider_results: dict[int, tuple[str | None, str | None]] = {}
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {
            executor.submit(provider_call, task["messages"], model): task["index"]
            for task in tasks
        }
        for future in as_completed(futures):
            try:
                provider_results[futures[future]] = (future.result(), None)
            except Exception as exc:
                provider_results[futures[future]] = (None, str(exc))

    executable = ROOT / ".lake" / "build" / "bin" / "sparse-ir-lean"
    executable_arg = executable if executable.is_file() else None
    raw_rows: list[dict[str, Any]] = []
    extracted_rows: list[dict[str, Any]] = []
    parse_rows: list[dict[str, Any]] = []
    lean_rows: list[dict[str, Any]] = []
    unexpected_rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    coverage: Counter[str] = Counter()
    pass_counts: Counter[str] = Counter()
    parse_error_coverage: Counter[str] = Counter()
    failure_codes: Counter[str] = Counter()
    valid_json = trace_parsed = parse_rejected = protocol_errors = 0
    expected_rejections = unexpected_accepts = unexpected_rejections = 0

    for task in tasks:
        sample_id = task["sample_id"]
        bucket = task["bucket"]
        adversarial = task["adversarial"]
        coverage[bucket] += 1
        raw, provider_error = provider_results[task["index"]]
        if raw is None:
            raw = ""
        trace_path = trace_dir / f"{sample_id}.trace.json"
        trace_path.write_text(raw + "\n", encoding="utf-8")
        raw_rows.append(
            {
                "sample_id": sample_id,
                "bucket": bucket,
                "raw_output": raw,
                "provider_error": provider_error,
                "trace_path": _relative(trace_path),
            }
        )
        extraction = extract_top_level_json(raw)
        extracted = extraction["extracted_json"]
        if extraction["status"] not in {"invalid_json", "extraction_failure"}:
            valid_json += 1
        model_complied = extracted == task["exemplar"]
        extracted_rows.append(
            {
                "sample_id": sample_id,
                "bucket": bucket,
                "status": extraction["status"],
                "model_complied": model_complied,
                "extracted_json": extracted,
            }
        )
        paths = unexpected_field_paths(extracted) if isinstance(extracted, dict) else []
        if bucket == "wrapper_object" and "$.trace" not in paths:
            paths.append("$.trace")
        for path in sorted(paths):
            unexpected_rows.append({"sample_id": sample_id, "bucket": bucket, "path": path})
        request = {
            "protocol_version": "0.1.0",
            "request_id": sample_id,
            "command": "parse_trace",
            "payload": {"trace": raw},
        }
        try:
            response = lean_invoke(request, executable_arg)
            result = response["result"]
        except Exception as exc:
            protocol_errors += 1
            response = {"kind": "PROTOCOL_ERROR", "message": str(exc)}
            result = response
        lean_rows.append(
            {
                "sample_id": sample_id,
                "bucket": bucket,
                "lean_input": request,
                "lean_output": response,
                "raw_lean_output": json.dumps(response, separators=(",", ":")),
            }
        )
        if result.get("kind") == "TRACE_PARSED":
            trace_parsed += 1
        elif result.get("kind") == "REJECT":
            parse_rejected += 1
            code = result.get("failure", {}).get("failure_code", "unknown_rejection")
            failure_codes[code] += 1
            parse_error_coverage[code] += 1
        score = score_sample(adversarial, bucket, model_complied, extraction["status"], result)
        parse_rows.append(
            {
                "sample_id": sample_id,
                "bucket": bucket,
                "adversarial": adversarial,
                "model_complied": model_complied,
                "passed": score["passed"],
                "score": score,
                "lean_result": result,
            }
        )
        if score["passed"]:
            pass_counts[bucket] += 1
            if adversarial:
                expected_rejections += 1
        else:
            if adversarial and result.get("kind") == "TRACE_PARSED":
                unexpected_accepts += 1
            if not adversarial and result.get("kind") != "TRACE_PARSED":
                unexpected_rejections += 1
            failures.append(
                {
                    "sample_id": sample_id,
                    "bucket": bucket,
                    "provider_error": provider_error,
                    "score": score,
                    "lean_result": result,
                }
            )

    positive_total = len(POSITIVE_BUCKETS) * positive_samples_per_feature
    adversarial_total = len(ADVERSARIAL_EXPECTATIONS) * adversarial_samples_per_feature
    positive_passed = sum(pass_counts[bucket] for bucket in POSITIVE_BUCKETS)
    adversarial_passed = sum(pass_counts[bucket] for bucket in ADVERSARIAL_EXPECTATIONS)
    status = gate_status(
        positive_total,
        positive_passed,
        adversarial_total,
        adversarial_passed,
        protocol_errors,
        coverage,
        pass_counts,
    )
    manifest = {
        "stage": "stage4_provider_adversarial",
        "status": status,
        "model": model,
        "seed": seed,
        "total_samples": len(tasks),
        "positive_samples": positive_total,
        "adversarial_samples": adversarial_total,
        "valid_json": valid_json,
        "trace_parsed": trace_parsed,
        "parse_rejected": parse_rejected,
        "expected_rejections": expected_rejections,
        "unexpected_accepts": unexpected_accepts,
        "unexpected_rejections": unexpected_rejections,
        "protocol_error": protocol_errors,
        "feature_coverage": dict(coverage),
        "feature_pass_counts": dict(pass_counts),
        "parse_error_coverage": dict(parse_error_coverage),
        "failure_codes": dict(failure_codes),
    }
    matrix = {
        bucket: {
            "kind": "adversarial" if adversarial else "positive",
            "samples": coverage[bucket],
            "passed": pass_counts[bucket],
            "pass_rate": pass_counts[bucket] / coverage[bucket],
            "expected_code": ADVERSARIAL_EXPECTATIONS.get(bucket, (None, None))[0],
            "expected_path": ADVERSARIAL_EXPECTATIONS.get(bucket, (None, None))[1],
            "exemplar": bucket_exemplar(bucket, f"zl_{bucket}_example"),
        }
        for bucket, adversarial in buckets
    }
    _write_jsonl(output / "prompts.jsonl", prompt_rows)
    _write_jsonl(output / "raw_outputs.jsonl", raw_rows)
    _write_jsonl(output / "extracted_json.jsonl", extracted_rows)
    _write_jsonl(output / "parse_results.jsonl", parse_rows)
    _write_jsonl(output / "lean_outputs.jsonl", lean_rows)
    _write_jsonl(output / "unexpected_fields.jsonl", unexpected_rows)
    _write_jsonl(output / "failures.jsonl", failures)
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (output / "feature_matrix.json").write_text(
        json.dumps(matrix, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    examples = ["# Stage 4 provider adversarial examples", ""]
    for bucket, _ in buckets:
        row = next(item for item in parse_rows if item["bucket"] == bucket)
        examples.extend([f"## {bucket}", "", "```json", json.dumps(row, indent=2), "```", ""])
    (output / "examples.md").write_text("\n".join(examples), encoding="utf-8")
    summary = f"""# Stage 4 provider positive and adversarial parser validation

Status: **{status.upper()}**

- Model: `{model}`
- Total samples: {len(tasks)}
- Positive TRACE_PARSED: {positive_passed}/{positive_total}
- Adversarial expected rejections: {adversarial_passed}/{adversarial_total}
- Raw Lean outputs stored: {len(lean_rows)}/{len(tasks)}
- Unexpected accepts: {unexpected_accepts}
- Unexpected rejections: {unexpected_rejections}
- Protocol errors: {protocol_errors}

This gate scores only trace syntax and requested parser rejection behavior. It does not
replay traces or evaluate semantic correctness, proof validity, candidates, or solved state.
"""
    (output / "summary.md").write_text(summary, encoding="utf-8")
    return manifest
