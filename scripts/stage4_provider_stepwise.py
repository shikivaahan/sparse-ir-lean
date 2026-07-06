#!/usr/bin/env python3
"""Stage 4 stepwise trace-shape provider diagnostic.

This is a Stage 4 *parseability* diagnostic — it does NOT score the trace for
semantic correctness. It picks real ZebraLogic-derived compiled problems and
asks a model to emit stepwise traces using ONLY the public justification
contract (clue/from or bijection/from).

Goals:
* Measure schema-following for the new public justification contract on a
  realistic stepwise surface.
* Catch private-kernel-rule leakage (the model must not emit one of the 22
  internal StepKernel.supportedRules names).
* Surface unknown-field / wrapper / Markdown drift.
* Surface conclusion-shape drift.

Outputs are stored raw under
    eval/gates/stage4_trace_parser/provider_stepwise/

A trace is recorded, the JSON is extracted, validated by both the JSON Schema
and the trusted Lean verifier. Each row includes the raw provider output,
extracted JSON, parse result, and any failure code.
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
    # (scenario_id, prompt_suffix describing the puzzle)
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


def _classify(raw: str, result: dict[str, object]) -> tuple[str, str, str]:
    """Return (parse_status, fail_code, notes). parse_status in
    {parsed, schema_rejected, invalid_json, extraction_failed}."""
    text = (raw or "").strip()
    if not text:
        return "invalid_json", "provider_error", "empty output"
    try:
        decoded = json.loads(text)
    except Exception:
        return "invalid_json", "invalid_json", "raw output was not JSON"
    if not isinstance(decoded, dict):
        return "invalid_json", "invalid_json", "raw output was not a top-level object"
    kind = result.get("kind")
    if kind == "TRACE_PARSED":
        return "parsed", "", ""
    if kind == "REJECT":
        code = result.get("failure", {}).get("failure_code", "schema_invalid")
        return "schema_rejected", code, ""
    return "extraction_failed", "protocol_error", f"unexpected response: {result}"


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
        help="Per-scenario sample size across the compiled-problems pool.",
    )
    p.add_argument(
        "--seed-pool", type=int, default=42,
        help="Index of the first compiled problem to use; rotates across grid sizes.",
    )
    p.add_argument("--max-workers", type=int, default=4)
    p.add_argument("--require-access", action="store_true", default=False)
    args = p.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)

    if not os.environ.get("OPENROUTER_API_KEY"):
        if args.require_access:
            print(json.dumps({"status": "blocked", "reason": "missing OPENROUTER_API_KEY"}))
            return 2
        # In offline mode (used by tests / dry runs), just emit a skeleton manifest.
        (args.output / "manifest.json").write_text(
            json.dumps(
                {
                    "status": "blocked",
                    "model": args.model,
                    "reason": "no OPENROUTER_API_KEY; offline mode",
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        print(json.dumps({"status": "blocked"}))
        return 2

    problems = _load_compiled_problems(args.compiled_problems)
    if not problems:
        raise FileNotFoundError(
            f"no compiled problems in {args.compiled_problems}; cannot run diagnostic"
        )

    # Pick a sample-distinct selection across grid sizes.
    seen_grids: dict[str, int] = {}
    selected: list[dict[str, object]] = []
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

    executable = ROOT / ".lake" / "build" / "bin" / "sparse-ir-lean"
    executable_arg = executable if executable.is_file() else None

    tasks: list[tuple[int, str, str, str, list[dict[str, str]]]] = []
    prompt_rows: list[dict[str, object]] = []
    for scenario_id, suffix in SCENARIOS:
        per = [selected[i] for i in range(len(selected)) if (i % len(SCENARIOS)) == SCENARIOS.index((scenario_id, suffix))]
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
    parse_rows: list[dict[str, object]] = []
    parse_status_counts: Counter[str] = Counter()
    fail_code_counts: Counter[str] = Counter()
    scenario_status_counts: dict[str, Counter[str]] = {}
    valid_json = trace_parsed = 0
    protocol_error = 0

    private_rule_name_hits: list[dict[str, object]] = []
    PRIVATE_RULES = (
        "given_found_at_place",
        "bijection_place_eliminates_same_value_other_houses",
        "same_house_place_from_placed",
        "direct_left_place_from_fixed",
        "direct_right_place_from_fixed",
        "side_by_side_place_from_single_neighbor",
        "one_between_place_from_fixed",
        "two_between_place_from_fixed",
        "given_not_at_eliminate",
        "bijection_place_eliminates_other_values_same_house",
        "bijection_cell_singleton_forces_place",
        "bijection_value_singleton_forces_place",
        "same_house_eliminate_no_possible_match",
        "direct_left_eliminate_no_possible_partner",
        "direct_right_eliminate_no_possible_partner",
        "side_by_side_eliminate_no_possible_neighbor",
        "left_of_eliminate_impossible_order",
        "right_of_eliminate_impossible_order",
        "one_between_eliminate_no_possible_partner",
        "two_between_eliminate_no_possible_partner",
        "solved_conclusion",
        "contradiction_detection",
    )

    for index, sample_id, scenario_id, problem_id, _ in tasks:
        raw, provider_error = raw_results[index]
        base = {"sample_id": sample_id, "scenario": scenario_id, "problem_id": problem_id}
        if provider_error is not None:
            raw_rows.append({**base, "provider_error": provider_error})
            fail_code_counts["provider_error"] += 1
            parse_status_counts["provider_error"] += 1
            protocol_error += 1
            scenario_status_counts.setdefault(scenario_id, Counter())["provider_error"] += 1
            continue
        assert raw is not None
        raw_rows.append({**base, "raw_output": raw})
        try:
            result = _invoke_lean_for(raw, sample_id, executable_arg)
        except Exception as exc:
            protocol_error += 1
            fail_code_counts["protocol_error"] += 1
            parse_status_counts["protocol_error"] += 1
            parse_rows.append({**base, "result": {"kind": "PROTOCOL_ERROR", "message": str(exc)}})
            continue
        parse_rows.append({**base, "result": result})
        status, fail_code, notes = _classify(raw, result)
        parse_status_counts[status] += 1
        scenario_status_counts.setdefault(scenario_id, Counter())[status] += 1
        if fail_code:
            fail_code_counts[fail_code] += 1
        if status == "parsed":
            trace_parsed += 1
            valid_json += 1
        elif status == "invalid_json":
            pass
        elif status == "schema_rejected":
            pass
        # private-rule-name leakage detection (cheap string check on raw output)
        for name in PRIVATE_RULES:
            if name in raw:
                private_rule_name_hits.append(
                    {"sample_id": sample_id, "scenario": scenario_id, "rule_name": name}
                )

    total = len(tasks)
    status_overall = "pass" if total and trace_parsed / total >= 0.6 else ("partial" if trace_parsed else "fail")
    manifest = {
        "diagnostic": "stage4_provider_stepwise",
        "model": args.model,
        "status": status_overall,
        "parseability_only": True,
        "total_samples": total,
        "valid_json": valid_json,
        "trace_parsed": trace_parsed,
        "protocol_error": protocol_error,
        "parse_status_counts": dict(parse_status_counts),
        "scenario_status_counts": {k: dict(v) for k, v in scenario_status_counts.items()},
        "fail_code_counts": dict(fail_code_counts),
        "private_rule_name_leak_count": len(private_rule_name_hits),
        "private_rule_name_leak_samples": private_rule_name_hits[:20],
    }
    _write_jsonl(args.output / "prompts.jsonl", prompt_rows)
    _write_jsonl(args.output / "raw_outputs.jsonl", raw_rows)
    _write_jsonl(args.output / "parse_results.jsonl", parse_rows)
    (args.output / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    summary = (
        f"# Stage 4 provider stepwise trace-shape diagnostic\n\n"
        f"Status: **{status_overall.upper()}** (parseability only)\n\n"
        f"- Model: `{args.model}`\n"
        f"- Samples: {total}\n"
        f"- TRACE_PARSED: {trace_parsed}/{total}\n"
        f"- Valid JSON: {valid_json}/{total}\n"
        f"- Provider errors: {protocol_error}\n"
        f"- Private-rule-name leakage count: {len(private_rule_name_hits)}\n\n"
        f"Success means raw provider outputs parsed under the trusted Lean verifier and the "
        f"published JSON Schema. The trace did NOT have to be semantically sound.\n"
    )
    (args.output / "summary.md").write_text(summary, encoding="utf-8")
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0 if status_overall in {"pass", "partial"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
