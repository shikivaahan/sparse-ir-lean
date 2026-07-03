#!/usr/bin/env python3
"""Stage 6 cheap-mode0 smoke harness with reasoning ON.

Runs a balanced sample (~6 puzzles per house bin 2..6) with the corrected
reasoning-ON config, scores each candidate with the Lean binary, and
reports the blocking sanity gate metrics: pct rows with reasoning>0,
median reasoning tokens, median content tokens, Mode-0 coverage, and
malformed rate. Exits non-zero if any gate is missed.

Usage:
    python scripts/run_stage6_cheap_smoke.py --output-dir <gate> [--per-bin 6]
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sparseir_harness.stage6_h5_cleanup import (  # noqa: E402
    CHEAP_ARM,
    CHEAP_MODEL,
    CHEAP_TOKEN_CAPS,
    SEED,
    _house_candidates,
    cheap_working_set,
    evaluate_one,
    load_compiled_problems,
    OpenRouterProvider,
    _write_jsonl,
)

COMPILED = ROOT / "eval/gates/stage2_gate_a_compile_all/compiled_problems.jsonl"
EXECUTABLE = ROOT / ".lake/build/bin/sparse-ir-lean"

REASONING_PRESENT_GATE = 0.90
COVERAGE_GATE = 0.30
MALFORMED_GATE = 0.05


def _balanced_per_bin(problems: list[dict[str, Any]], per_bin: int, seed: int) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for house in range(2, 7):
        candidates = _house_candidates(problems, house, seed)
        selected.extend(candidates[:per_bin])
    return selected


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--per-bin", type=int, default=6)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--use-cheap-order", action="store_true",
                        help="Slice the first N*25 puzzles from cheap_working_set (1000-order)")
    parser.add_argument("--offset", type=int, default=30,
                        help="Skip this many puzzles from the cheap_working_set order")
    args = parser.parse_args()

    output = args.output_dir
    output.mkdir(parents=True, exist_ok=True)
    raw_dir = output / "raw"
    raw_dir.mkdir(exist_ok=True)

    problems = load_compiled_problems(COMPILED)
    if args.use_cheap_order:
        full_order = cheap_working_set(problems, 1000, SEED)
        n = args.per_bin * 5
        selected = full_order[args.offset:args.offset + n]
    else:
        selected = _balanced_per_bin(problems, args.per_bin, SEED)
    print(f"smoke: selected {len(selected)} puzzles", flush=True)

    provider = OpenRouterProvider(CHEAP_MODEL, SEED)
    rows: list[dict[str, Any]] = []
    completed = 0
    if args.workers <= 1:
        for index, problem in enumerate(selected, start=1):
            row = evaluate_one(problem, output, EXECUTABLE, provider, CHEAP_ARM, SEED)
            rows.append(row)
            completed += 1
            print(f"smoke {completed}/{len(selected)}: {row['id']} "
                  f"correct={row['correct']} lean={row['lean_kind']} "
                  f"reasoning={row['reasoning_tokens']} tokens_out={row['tokens_out']}",
                  flush=True)
    else:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = {
                pool.submit(evaluate_one, problem, output, EXECUTABLE, provider, CHEAP_ARM, SEED): problem
                for problem in selected
            }
            for future in as_completed(futures):
                row = future.result()
                rows.append(row)
                completed += 1
                print(f"smoke {completed}/{len(selected)}: {row['id']} "
                      f"correct={row['correct']} lean={row['lean_kind']} "
                      f"reasoning={row['reasoning_tokens']} tokens_out={row['tokens_out']}",
                      flush=True)

    rows.sort(key=lambda r: (r["houses"], r["id"]))
    _write_jsonl(output / "smoke_results.jsonl", rows)

    n = len(rows)
    correct = sum(bool(r["correct"]) for r in rows)
    malformed = sum(r["lean_status"] == "malformed" for r in rows)
    reasoning_tokens = [int(r["reasoning_tokens"] or 0) for r in rows]
    reasoning_pos = sum(1 for t in reasoning_tokens if t > 0)
    content_tokens = [int(r["tokens_out"] or 0) - int(r["reasoning_tokens"] or 0)
                      for r in rows]

    metrics = {
        "n": n,
        "correct": correct,
        "coverage": correct / n if n else 0.0,
        "malformed": malformed,
        "malformed_rate": malformed / n if n else 0.0,
        "reasoning_present_count": reasoning_pos,
        "reasoning_present_pct": reasoning_pos / n if n else 0.0,
        "median_reasoning_tokens": int(statistics.median(reasoning_tokens)) if reasoning_tokens else 0,
        "median_content_tokens": int(statistics.median(content_tokens)) if content_tokens else 0,
        "max_reasoning_tokens": max(reasoning_tokens) if reasoning_tokens else 0,
        "token_caps": CHEAP_TOKEN_CAPS,
        "model": CHEAP_MODEL,
    }
    (output / "smoke_metrics.json").write_text(
        json.dumps(metrics, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    print(json.dumps(metrics, indent=2, sort_keys=True))

    gates_passed = (
        metrics["reasoning_present_pct"] >= REASONING_PRESENT_GATE
        and metrics["coverage"] >= COVERAGE_GATE
        and metrics["malformed_rate"] <= MALFORMED_GATE
    )
    metrics["gates_passed"] = gates_passed
    metrics["gates"] = {
        "reasoning_present_min_pct": REASONING_PRESENT_GATE,
        "coverage_min": COVERAGE_GATE,
        "malformed_max_rate": MALFORMED_GATE,
    }
    (output / "smoke_metrics.json").write_text(
        json.dumps(metrics, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    if not gates_passed:
        print(
            f"SMOKE FAILED: reasoning_present_pct={metrics['reasoning_present_pct']:.2f} "
            f"(< {REASONING_PRESENT_GATE}); coverage={metrics['coverage']:.2f} "
            f"(< {COVERAGE_GATE}); malformed_rate={metrics['malformed_rate']:.2f} "
            f"(> {MALFORMED_GATE})",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())