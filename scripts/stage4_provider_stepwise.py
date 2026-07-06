#!/usr/bin/env python3
"""Stage 4 stepwise trace-shape provider diagnostic.

This is a Stage 4 *parseability* diagnostic — it does NOT score the trace for
semantic correctness. It picks real ZebraLogic-derived compiled problems and
asks a model to emit stepwise traces using ONLY the public justification
contract (clue/from or bijection/from).

Each provider output is independently evaluated on four layers:

    1. did the provider call return any text?
    2. does the returned text parse as JSON with a top-level object?
    3. does that object satisfy schemas/zebra-trace.schema.json?
    4. does that object satisfy the trusted Lean parse_trace verdict?

The (3) and (4) verdicts are compared per sample to record a real schema<->Lean
disagreement count on actual provider outputs (not inferred from the 122-case
differential corpus).

Outputs are stored raw under
    eval/gates/stage4_trace_parser/provider_stepwise/
"""

from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


from sparseir_harness.trace_parser_gate import (  # noqa: E402  (sys.path set above)
    _invoke_lean,
    _write_jsonl,
    call_provider,
    ROOT,
)


# The 22 private kernel rule names. The public trace surface MUST NOT
# contain any of these. They are scanned for in the raw provider output as
# a cheap "is the model trying to expose kernel internals?" diagnostic.
PRIVATE_KERNEL_RULE_NAMES: tuple[str, ...] = (
    "given_found_at_place",
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
)


PROMPT_TEMPLATE = (
    "You are emitting a single ZebraLogic stepwise reasoning trace as raw JSON. "
    "Return ONLY one raw JSON object; do not wrap it in Markdown or add commentary.\n\n"
    "Top-level shape (exact keys):\n"
    '{{"schema_version": "0.2", "problem_id": "<id>", "ops": [...]}}\n\n'
    "Allowed ops: 'place', 'eliminate', 'conclude'.\n"
    "Each 'place' or 'eliminate' op MUST have: cat, house, val, justify.\n"
    "'conclude' MUST have: status (which must equal exactly the string \"solved\").\n\n"
    "justify is a tagged union; pick exactly one form:\n"
    "  clue-based:    {{\"clue\": \"<clue id from the problem>\", \"from\": [...]?}}\n"
    "  structural:    {{\"rule\": \"bijection\", \"from\": [...]?}}\n"
    "The 22 internal Lean consequence-rule names (e.g. given_found_at_place, "
    "direct_left_place_from_fixed, one_between_eliminate_no_possible_partner) are "
    "FORBIDDEN on the public surface and will be rejected.\n"
    "from entries (when present) must look like {{'cat': str, 'house': int>=1, "
    "'val': str}}.\n\n"
    "Use ONLY place / eliminate / conclude with the public justification shapes "
    "above. Do NOT produce a full candidate assignment trace (no assign_all). Do NOT "
    "produce an empty ops list. The trace does NOT need to be semantically correct — "
    "this diagnostic tests syntax and shape only."
)


SCENARIOS: list[tuple[str, str]] = [
    (
        "stepwise_clue_only",
        "Use ONLY clue-based justifications.",
    ),
    (
        "stepwise_bijection_or_clue",
        "Mix clue-based justifications with the structural bijection form "
        '({"rule": "bijection", "from": ...?}) where appropriate.',
    ),
    (
        "stepwise_bijection_only",
        "Use ONLY the structural bijection justification form "
        '({"rule": "bijection", "from": ...?}).',
    ),
]


def _load_compiled_problems(path: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rows.append(json.loads(line))
    return rows


def _prompt_for(problem: dict[str, object], scenario_suffix: str) -> list[dict[str, str]]:
    pj = {
        "problem_id": problem["problem_id"],
        "size": {"houses": problem["houses"], "categories": len(problem["compiled_categories"])},
        "categories": [
            {"name": cat["name"], "values": cat["values"]}
            for cat in problem["compiled_categories"]
        ],
        "clues": [
            {k: v for k, v in clue.items() if k in ("id", "type", "cat", "val", "house", "a", "b")}
            for clue in problem["compiled_clues"]
        ],
    }
    return [
        {
            "role": "system",
            "content": PROMPT_TEMPLATE + " " + scenario_suffix,
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "task": "Emit one stepwise trace.json for the puzzle below. "
                    "Do not produce a full candidate assignment.",
                    "puzzle": pj,
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
        },
    ]


def _invoke_lean_for(raw: str, sample_id: str, executable: Path | None) -> dict[str, object]:
    return _invoke_lean(
        {
            "protocol_version": "0.1.0",
            "request_id": sample_id,
            "command": "parse_trace",
            "payload": {"trace": raw},
        },
        executable,
    )["result"]


def _validate_schema(
    raw_text: str, schema_validator: "object"
) -> tuple[bool, str | None]:
    try:
        decoded = json.loads(raw_text)
    except Exception as exc:
        return False, f"raw text is not JSON: {exc!s:.200}"
    if not isinstance(decoded, dict):
        return False, "top-level value is not a JSON object"
    errors = list(schema_validator.iter_errors(decoded))
    if not errors:
        return True, None
    first = errors[0]
    path = "/".join(str(p) for p in first.absolute_path) or "(root)"
    return False, f"{first.message!s:.200} at {path}"


def analyze_outputs(
    output: Path,
    *,
    lean_executable: Path | None,
    schema_validator: "object",
    model: str,
) -> dict[str, object]:
    raw_rows = [
        json.loads(line)
        for line in (output / "raw_outputs.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    prompts: dict[str, dict[str, object]] = {}
    for line in (output / "prompts.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        prompts[row["sample_id"]] = row

    analyze_rows: list[dict[str, object]] = []
    fail_code_counts: Counter[str] = Counter()
    scenario_layer_counts: dict[str, Counter[str]] = {}

    provider_output_present = raw_json_valid = schema_valid = lean_trace_parsed = 0
    schema_lean_disagreement_count = 0
    provider_error_count = 0

    for raw_row in raw_rows:
        sample_id = raw_row["sample_id"]
        scenario_id = raw_row.get("scenario") or prompts.get(sample_id, {}).get("scenario")
        prompt_row = prompts.get(sample_id, {})

        analyze: dict[str, object] = {
            "sample_id": sample_id,
            "scenario": scenario_id,
            "problem_id": raw_row.get("problem_id") or prompt_row.get("problem_id"),
        }

        provider_error = raw_row.get("provider_error")
        if provider_error is not None:
            analyze["provider_error"] = provider_error
            analyze["provider_output_present"] = False
            analyze["raw_json_valid"] = False
            analyze["schema_valid"] = False
            analyze["lean_trace_parsed"] = False
            analyze["schema_lean_agreement"] = True
            analyze_rows.append(analyze)
            provider_error_count += 1
            fail_code_counts["provider_error"] += 1
            scenario_layer_counts.setdefault(scenario_id or "?", Counter())["provider_error"] += 1
            continue

        raw_text: str = raw_row.get("raw_output", "") or ""
        analyze["raw_output_present"] = bool(raw_text.strip())
        if raw_text.strip():
            provider_output_present += 1

        json_error: str | None = None
        decoded: object | None = None
        try:
            decoded = json.loads(raw_text)
        except Exception as exc:
            json_error = f"{exc!s:.200}"
        is_object = isinstance(decoded, dict)
        analyze["raw_json_valid"] = is_object
        analyze["raw_json_error"] = json_error
        if is_object:
            raw_json_valid += 1

        schema_ok, schema_msg = _validate_schema(raw_text, schema_validator)
        analyze["schema_valid"] = schema_ok
        analyze["schema_error"] = schema_msg
        if schema_ok:
            schema_valid += 1

        lean_kind = "PROTOCOL_ERROR"
        lean_code: str | None = None
        lean_path: str | None = None
        if not raw_text.strip():
            lean_kind = "EMPTY_OUTPUT"
            analyze["lean_failure_message"] = "no provider text to parse"
        else:
            try:
                lean_result = _invoke_lean_for(raw_text, sample_id, lean_executable)
                lean_kind = lean_result.get("kind")
                failure = lean_result.get("failure") or {}
                lean_code = failure.get("failure_code")
                lean_path = failure.get("path")
                analyze["lean_failure_message"] = failure.get("message")
                analyze["lean_result"] = lean_result
            except Exception as exc:
                lean_kind = "PROTOCOL_ERROR"
                analyze["lean_failure_message"] = str(exc)
        analyze["lean_kind"] = lean_kind
        analyze["lean_failure_code"] = lean_code
        analyze["lean_failure_path"] = lean_path
        analyze["lean_trace_parsed"] = lean_kind == "TRACE_PARSED"
        if lean_kind == "TRACE_PARSED":
            lean_trace_parsed += 1
        elif lean_kind == "REJECT":
            if lean_code:
                fail_code_counts[lean_code] += 1
        elif lean_kind in {"PROTOCOL_ERROR", "EMPTY_OUTPUT"}:
            fail_code_counts[lean_kind.lower()] += 1

        if is_object:
            agreement = (schema_ok == analyze["lean_trace_parsed"])
        else:
            agreement = True
        analyze["schema_lean_agreement"] = agreement
        if is_object and not agreement:
            schema_lean_disagreement_count += 1

        leaks: list[str] = [
            name for name in PRIVATE_KERNEL_RULE_NAMES if name in raw_text
        ]
        analyze["private_rule_name_leakage"] = leaks

        analyze_rows.append(analyze)
        scenario_layer_counts.setdefault(scenario_id or "?", Counter())[lean_kind] += 1

    n_attempted = len(analyze_rows)
    n_with_output = provider_output_present
    n_with_json = raw_json_valid
    manifest: dict[str, object] = {
        "diagnostic": "stage4_provider_stepwise",
        "model": model,
        "status": (
            "pass"
            if n_attempted
            and schema_lean_disagreement_count == 0
            and lean_trace_parsed / n_attempted >= 0.6
            else (
                "partial"
                if lean_trace_parsed
                else "fail"
            )
        ),
        "parseability_only": True,
        "samples_attempted": n_attempted,
        "provider_returned_output": n_with_output,
        "provider_error_count": provider_error_count,
        "raw_json_valid": raw_json_valid,
        "raw_json_valid_rate": (
            raw_json_valid / n_with_output if n_with_output else 0.0
        ),
        "schema_valid": schema_valid,
        "schema_valid_rate": (
            schema_valid / n_with_json if n_with_json else 0.0
        ),
        "lean_trace_parsed": lean_trace_parsed,
        "lean_trace_parsed_rate_of_attempted": (
            lean_trace_parsed / n_attempted if n_attempted else 0.0
        ),
        "lean_trace_parsed_rate_of_returned": (
            lean_trace_parsed / n_with_output if n_with_output else 0.0
        ),
        "schema_lean_disagreement_count": schema_lean_disagreement_count,
        "schema_lean_agreement_rate_of_json": (
            (n_with_json - schema_lean_disagreement_count) / n_with_json
            if n_with_json
            else 1.0
        ),
        "fail_code_counts": dict(fail_code_counts),
        "scenario_layer_counts": {
            k: dict(v) for k, v in scenario_layer_counts.items()
        },
        "private_rule_name_leak_count": sum(
            len(r.get("private_rule_name_leakage") or [])
            for r in analyze_rows
        ),
    }

    _write_jsonl(output / "analyze_results.jsonl", analyze_rows)
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    summary = _summary_text(manifest)
    (output / "summary.md").write_text(summary, encoding="utf-8")
    return manifest


def _summary_text(manifest: dict[str, object]) -> str:
    n_attempted = manifest["samples_attempted"]
    n_returned = manifest["provider_returned_output"]
    n_json = manifest["raw_json_valid"]
    n_schema = manifest["schema_valid"]
    n_lean = manifest["lean_trace_parsed"]
    return (
        f"# Stage 4 provider stepwise trace-shape diagnostic\n\n"
        f"Status: **{manifest['status'].upper()}** (parseability only)\n\n"
        f"- Model: `{manifest['model']}`\n"
        f"- Samples attempted: {n_attempted}\n"
        f"- Provider returned output: {n_returned}/{n_attempted}\n"
        f"- Provider errors: {manifest['provider_error_count']}\n"
        f"- Raw JSON (top-level object) valid: {n_json}/{n_returned} "
        f"({manifest['raw_json_valid_rate']:.1%})\n"
        f"- JSON Schema valid: {n_schema}/{n_json} "
        f"({manifest['schema_valid_rate']:.1%})\n"
        f"- Lean TRACE_PARSED: {n_lean}/{n_attempted} "
        f"({manifest['lean_trace_parsed_rate_of_attempted']:.1%} of attempted; "
        f"{manifest['lean_trace_parsed_rate_of_returned']:.1%} of returned)\n"
        f"- Schema<->Lean disagreements (on actual provider outputs): "
        f"{manifest['schema_lean_disagreement_count']}\n"
        f"- Private kernel rule name leakage (raw-output substring scan): "
        f"{manifest['private_rule_name_leak_count']}\n\n"
        f"Each provider output is independently evaluated on four layers:\n"
        f"provider call -> raw JSON -> JSON Schema -> Lean parse_trace.\n"
        f"Trace validity claims are DENOMINATED on the layer above them, "
        f"not on `samples attempted`. The 122-case "
        f"`src/sparseir_harness/trace_parity_corpus.py` is separate hand-"
        f"curated evidence and does not prove provider-output parity; this "
        f"script's `schema_lean_disagreement_count` is the per-output "
        f"evidence.\n"
    )


def _live_run(args: argparse.Namespace) -> dict[str, object]:

    problems = _load_compiled_problems(args.compiled_problems)
    if not problems:
        raise FileNotFoundError(
            f"no compiled problems in {args.compiled_problems}; cannot run diagnostic"
        )

    selected: list[dict[str, object]] = []
    seen_grids: dict[str, int] = {}
    idx = args.seed_pool % len(problems)
    while len(selected) < args.samples_per_scenario * len(SCENARIOS):
        candidate = problems[idx % len(problems)]
        grid = candidate.get("grid") or "?"
        if seen_grids.get(grid, 0) < args.samples_per_scenario:
            selected.append(candidate)
            seen_grids[grid] = seen_grids.get(grid, 0) + 1
        idx += 1
        if idx - args.seed_pool >= len(problems):
            break

    tasks: list[tuple[int, str, str, str, list[dict[str, str]]]] = []
    prompt_rows: list[dict[str, object]] = []
    for scenario_idx, (scenario_id, suffix) in enumerate(SCENARIOS):
        per = [
            selected[i]
            for i in range(len(selected))
            if (i % len(SCENARIOS)) == scenario_idx
        ]
        for index, problem in enumerate(per[: args.samples_per_scenario]):
            sample_id = f"{scenario_id}-{index:02d}"
            problem_id = problem["problem_id"]
            messages = _prompt_for(problem, suffix)
            tasks.append((len(tasks), sample_id, scenario_id, problem_id, messages))
            prompt_rows.append(
                {
                    "sample_id": sample_id,
                    "scenario": scenario_id,
                    "problem_id": problem_id,
                    "grid": problem.get("grid"),
                    "model": args.model,
                    "messages": messages,
                }
            )

    raw_results: dict[int, tuple[str | None, str | None]] = {}
    with ThreadPoolExecutor(max_workers=args.max_workers) as executor:
        futures = {
            executor.submit(call_provider, messages, args.model): index
            for index, _sample, _scenario, _pid, messages in tasks
        }
        for future in as_completed(futures):
            index = futures[future]
            try:
                raw_results[index] = (future.result(), None)
            except Exception as exc:
                raw_results[index] = (None, str(exc))

    raw_rows: list[dict[str, object]] = []
    for index, sample_id, scenario_id, problem_id, _ in tasks:
        raw, err = raw_results[index]
        base = {
            "sample_id": sample_id,
            "scenario": scenario_id,
            "problem_id": problem_id,
        }
        if err is not None:
            raw_rows.append({**base, "provider_error": err})
        else:
            raw_rows.append({**base, "raw_output": raw})
    _write_jsonl(args.output / "raw_outputs.jsonl", raw_rows)
    _write_jsonl(args.output / "prompts.jsonl", prompt_rows)
    return _reanalyze(args)


def _reanalyze(args: argparse.Namespace) -> dict[str, object]:
    import jsonschema

    schema_path = ROOT / "schemas" / "zebra-trace.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    schema_validator = jsonschema.Draft202012Validator(schema)
    executable = ROOT / ".lake" / "build" / "bin" / "sparse-ir-lean"
    executable_arg = executable if executable.is_file() else None
    return analyze_outputs(
        args.output,
        lean_executable=executable_arg,
        schema_validator=schema_validator,
        model=args.model,
    )


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--compiled-problems",
        type=Path,
        default=ROOT / "eval/gates/stage2_gate_a_compile_all/compiled_problems.jsonl",
    )
    p.add_argument(
        "--output",
        type=Path,
        default=ROOT / "eval/gates/stage4_trace_parser/provider_stepwise",
    )
    p.add_argument("--model", default="deepseek/deepseek-v4-flash")
    p.add_argument(
        "--samples-per-scenario", type=int, default=10,
    )
    p.add_argument("--seed-pool", type=int, default=42)
    p.add_argument("--max-workers", type=int, default=4)
    p.add_argument(
        "--reanalyze-from",
        type=Path,
        default=None,
        help=(
            "Path to an existing provider_stepwise output directory. If "
            "supplied, the script does NOT call the provider; it just "
            "re-evaluates raw_outputs.jsonl on the four validator layers."
        ),
    )
    args = p.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)

    if args.reanalyze_from is not None:
        if not (args.reanalyze_from / "raw_outputs.jsonl").is_file():
            raise FileNotFoundError(
                f"{args.reanalyze_from}/raw_outputs.jsonl not found; "
                f"cannot reanalyze without raw outputs"
            )
        args.output = args.reanalyze_from
        manifest = _reanalyze(args)
        print(json.dumps(manifest, indent=2, sort_keys=True))
        return 0

    if not os.environ.get("OPENROUTER_API_KEY"):
        manifest = {
            "diagnostic": "stage4_provider_stepwise",
            "model": args.model,
            "status": "blocked",
            "reason": "no OPENROUTER_API_KEY; run with --reanalyze-from "
            "after a successful live run.",
            "parseability_only": True,
        }
        (args.output / "manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(json.dumps(manifest, indent=2, sort_keys=True))
        return 2

    manifest = _live_run(args)
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0 if manifest["status"] in {"pass", "partial"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
