"""Stage 6 reasoning-budget sweep.

Measures verifier value vs inference-time compute for deepseek/deepseek-v4-flash.
A single 200-puzzle balanced subset is evaluated at eight reasoning-budget levels.
Lean check_candidate is the sole correctness judge.
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import re
import statistics
import threading
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from openai import OpenAI

from sparseir_harness.stage6_contamination import (
    PROMPT_TEXT,
    extract_final_json,
)
from sparseir_harness.stage6_h5_cleanup import (
    CHEAP_MODEL,
    CHEAP_TOKEN_CAPS,
    OPENROUTER_ENDPOINT,
    SYSTEM_PROMPT,
    USER_TEMPLATE,
    _compact,
    load_compiled_problems,
)
from sparseir_harness.stage6_mode0 import check_candidate


GATE = "stage6_budget_sweep"
SEED = 20260702
SELECTION_SEED = 20260702

BUDGETS: list[int | None] = [0, 256, 512, 1024, 2048, 4096, 8192, None]
FULL_REASONING_BUDGET = CHEAP_TOKEN_CAPS["reasoning_tokens"]
ANSWER_BUDGET = CHEAP_TOKEN_CAPS["answer_tokens"]
REQUEST_MAX_TOKENS = CHEAP_TOKEN_CAPS["request_max_tokens"]
N_PUZZLES = 200
WORKERS_DEFAULT = 12
SMOKE_BUDGETS: list[int | None] = [0, 1024, None]
SMOKE_N = 6


@dataclass(frozen=True)
class BudgetSpec:
    label: str
    reasoning_max_tokens: int | None
    extra_body: dict

    @classmethod
    def from_value(cls, value):
        if value is None:
            return cls("full", FULL_REASONING_BUDGET, {"reasoning": {"max_tokens": FULL_REASONING_BUDGET, "exclude": False}})
        if value == 0:
            return cls("0", 0, {"reasoning": {"effort": "none"}})
        return cls(str(value), value, {"reasoning": {"max_tokens": value, "exclude": False}})


def _budget_label(value):
    return BudgetSpec.from_value(value).label


def _budget_sort_key(label):
    if label == "full":
        return FULL_REASONING_BUDGET
    return int(label)


def _json_hash(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def select_puzzles(problems, n, seed):
    per_house = n // 5
    if n % 5:
        raise ValueError("budget sweep N must be divisible by five for house-bin balance")
    groups = defaultdict(list)
    for problem in problems:
        key = (int(problem["size"]["houses"]), int(problem["size"]["categories"]))
        groups[key].append(problem)
    categories = sorted({key[1] for key in groups})
    if not categories:
        raise ValueError("no categories available")
    quota = per_house // len(categories)
    if per_house % len(categories):
        raise ValueError("n must split evenly across (house, category) bins")
    selected = []
    for house in range(2, 7):
        rng = random.Random(seed + house * 1009)
        for category in categories:
            pool = sorted(groups.get((house, category), []), key=lambda p: p["id"])
            rng.shuffle(pool)
            chosen = pool[:quota]
            if len(chosen) != quota:
                raise ValueError(
                    f"not enough puzzles for house={house} category={category}: "
                    f"have {len(pool)}, need {quota}"
                )
            selected.extend(chosen)
    if len(selected) != n:
        raise ValueError(f"selected {len(selected)} puzzles, expected {n}")
    return selected


class Provider:
    """OpenRouter client that exposes the reasoning-budget knob."""

    def __init__(self, model, spec, request_max_tokens, temperature, seed):
        if not os.environ.get("OPENROUTER_API_KEY"):
            raise RuntimeError("OPENROUTER_API_KEY is not set")
        self.model = model
        self.spec = spec
        self.request_max_tokens = request_max_tokens
        self.temperature = temperature
        self.seed = seed
        self._local = threading.local()

    def _client(self):
        client = getattr(self._local, "client", None)
        if client is None:
            client = OpenAI(
                api_key=os.environ["OPENROUTER_API_KEY"],
                base_url=OPENROUTER_ENDPOINT,
                max_retries=0,
                timeout=300.0,
            )
            self._local.client = client
        return client

    def call(self, problem):
        response = self._client().chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": USER_TEMPLATE.format(problem_json=_compact(problem))},
            ],
            temperature=self.temperature,
            seed=self.seed,
            max_tokens=self.request_max_tokens,
            extra_body=self.spec.extra_body,
        )
        usage = response.usage.model_dump() if response.usage else {}
        extra = getattr(response.usage, "model_extra", None) or {}
        details = usage.get("completion_tokens_details") or {}
        choice = response.choices[0]
        return {
            "text": choice.message.content or "",
            "response": response.model_dump(mode="json"),
            "finish_reason": choice.finish_reason,
            "provider_model_id": response.model,
            "tokens_in": int(usage.get("prompt_tokens") or 0),
            "tokens_out": int(usage.get("completion_tokens") or 0),
            "reasoning_tokens": int(details.get("reasoning_tokens") or 0),
            "cost_usd": float(usage.get("cost", extra.get("cost", 0.0)) or 0.0),
        }


def evaluate(problem, budget_value, run_dir, executable, provider):
    started = time.monotonic()
    spec = BudgetSpec.from_value(budget_value)
    raw_path = run_dir / "raw" / f"{spec.label}__{problem['id']}.json"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    call = None
    errors = []
    try:
        call = provider.call(problem)
    except Exception as exc:
        errors.append({"type": type(exc).__name__, "message": str(exc)})
    raw = {
        "problem_id": problem["id"],
        "budget": spec.label,
        "budget_reasoning_max_tokens": spec.reasoning_max_tokens,
        "provider": call,
        "errors": errors,
    }
    raw_path.write_text(json.dumps(raw, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    text = call["text"] if call else ""
    parsed, final_json, candidate_text, think_stripped = extract_final_json(text)
    lean_kind, lean_status, correct, lean_result = check_candidate(executable, problem, candidate_text)

    finish_reason = call["finish_reason"] if call else None
    provider_error = bool(errors)
    rate_limit_error = any("429" in e["message"] or "rate" in e["type"].lower() for e in errors)
    if correct:
        category = "solved"
    elif provider_error:
        category = "rate_limit_error" if rate_limit_error else "provider_error"
    elif finish_reason == "length":
        category = "truncation"
    else:
        category = lean_status

    raw.update({"parsed_final_json": final_json, "lean_verdict": lean_result})
    raw_path.write_text(json.dumps(raw, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {
        "id": problem["id"],
        "grid": problem["source"]["grid"],
        "houses": problem["size"]["houses"],
        "categories": problem["size"]["categories"],
        "budget": spec.label,
        "budget_reasoning_max_tokens": spec.reasoning_max_tokens,
        "model": provider.model,
        "provider_model_id": call["provider_model_id"] if call else None,
        "prompt_hash": hashlib.sha256(PROMPT_TEXT.encode()).hexdigest(),
        "config_hash": _json_hash({"budget": spec.label, "extra_body": spec.extra_body}),
        "raw_path": str(raw_path.relative_to(run_dir.parent)),
        "candidate_parsed": parsed,
        "think_stripped": think_stripped,
        "parsed_final_json": final_json,
        "lean_kind": lean_kind,
        "lean_status": lean_status,
        "lean_verdict": lean_result,
        "correct": correct,
        "failure_category": category,
        "finish_reason": finish_reason,
        "reasoning_tokens": call["reasoning_tokens"] if call else 0,
        "tokens_in": call["tokens_in"] if call else 0,
        "tokens_out": call["tokens_out"] if call else 0,
        "cost_usd": call["cost_usd"] if call else 0.0,
        "provider_error": provider_error,
        "rate_limit_error": rate_limit_error,
        "elapsed_seconds": time.monotonic() - started,
    }


def run_one_budget(
    problems,
    budget_value,
    run_dir,
    executable,
    workers,
    model,
    request_max_tokens,
    temperature,
    seed,
    outer_progress,
    total_units,
    outer_lock,
    started,
):
    spec = BudgetSpec.from_value(budget_value)
    label = spec.label
    budget_results_path = run_dir / "results" / f"{label}.jsonl"
    budget_results_path.parent.mkdir(parents=True, exist_ok=True)
    if budget_results_path.exists() and budget_results_path.stat().st_size:
        raise FileExistsError(f"refusing to overwrite prior budget run: {budget_results_path}")
    budget_results_path.write_text("", encoding="utf-8")

    provider = Provider(model, spec, request_max_tokens, temperature, seed)
    rows = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(evaluate, problem, budget_value, run_dir, executable, provider): problem for problem in problems}
        for future in as_completed(futures):
            row = future.result()
            rows.append(row)
            rows.sort(key=lambda r: (r["houses"], r["categories"], r["id"]))
            budget_results_path.write_text(
                "".join(json.dumps(r, sort_keys=True) + "\n" for r in rows),
                encoding="utf-8",
            )
            with outer_lock:
                outer_progress["completed"] += 1
            _write_status(
                run_dir / "status.md",
                outer_progress["completed"],
                total_units,
                workers,
                time.monotonic() - started,
                current_budget=label,
            )
            print(f"{GATE}/{label}: {len(rows)}/{len(problems)} {row['id']}", flush=True)
    return rows


def run(output, run_dir, executable, workers, budgets=None, model=CHEAP_MODEL,
        request_max_tokens=REQUEST_MAX_TOKENS, temperature=0.1, seed=SEED):
    selected_budgets = list(budgets) if budgets is not None else list(BUDGETS)
    run_dir.mkdir(parents=True, exist_ok=True)
    puzzles_path = output / "configs" / "puzzles.jsonl"
    problems = [json.loads(line) for line in puzzles_path.read_text().splitlines() if line.strip()]
    outer_lock = threading.Lock()
    started = time.monotonic()
    outer_progress = {"completed": 0}
    total_units = len(problems) * len(selected_budgets)
    _write_status(run_dir / "status.md", 0, total_units, workers, 0.0, current_budget="starting")
    all_rows = []
    for budget_value in selected_budgets:
        rows = run_one_budget(
            problems,
            budget_value,
            run_dir,
            executable,
            workers,
            model,
            request_max_tokens,
            temperature,
            seed,
            outer_progress,
            total_units,
            outer_lock,
            started,
        )
        all_rows.extend(rows)
    _write_jsonl(run_dir / "results.jsonl", all_rows)
    _write_jsonl(run_dir / "failures.jsonl", [row for row in all_rows if not row["correct"]])
    _write_json(run_dir / "run_metadata.json", {
        "workers": workers,
        "wall_seconds": time.monotonic() - started,
        "completed": len(all_rows),
        "budgets": [_budget_label(v) for v in selected_budgets],
    })
    return all_rows


def _read_jsonl(path):
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")
    temp.replace(path)


def _write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_status(path, completed, total, workers, elapsed, current_budget="", complete=False):
    rate = completed / elapsed * 60 if elapsed else 0.0
    eta = (total - completed) / rate if rate else None
    eta_text = f"{eta:.1f}" if eta is not None else "?"
    text = f"""# {GATE} status

- state: {'complete' if complete else 'running'}
- model/budget: `{CHEAP_MODEL}`, current budget `{current_budget}`, request max {REQUEST_MAX_TOKENS}
- completed: {completed}/{total}
- examples/min: {rate:.2f}
- elapsed: {elapsed / 60:.1f} min
- ETA: {eta_text} min
- workers: {workers}
"""
    path.write_text(text, encoding="utf-8")


def _group_metrics(rows, key):
    result = {}
    for value in sorted({str(row[key]) for row in rows}):
        group = [row for row in rows if str(row[key]) == value]
        n = len(group)
        solved = sum(bool(row["correct"]) for row in group)
        result[value] = {
            "n": n,
            "solved": solved,
            "coverage": solved / n if n else 0.0,
            "malformed": sum(row["lean_status"] == "malformed" for row in group),
            "clue_violation": sum(row["lean_status"] == "clue_violation" for row in group),
        }
    return result


def _budget_metrics(rows, wall_seconds):
    n = len(rows)
    if n == 0:
        return {"n": 0}
    reasoning = [int(row["reasoning_tokens"] or 0) for row in rows]
    finish = Counter(str(row["finish_reason"]) for row in rows)
    outcomes = Counter(row["lean_status"] for row in rows)
    solved = sum(bool(row["correct"]) for row in rows)
    elapsed_sum = sum(float(row["elapsed_seconds"]) for row in rows)
    wall = wall_seconds or elapsed_sum
    return {
        "n": n,
        "solved": solved,
        "coverage": solved / n,
        "confident_wrong": 0,
        "malformed": outcomes["malformed"],
        "clue_violation": outcomes["clue_violation"],
        "truncation": finish["length"],
        "provider_error": sum(bool(row["provider_error"]) for row in rows),
        "rate_limit_error": sum(bool(row["rate_limit_error"]) for row in rows),
        "finish_reasons": dict(sorted(finish.items())),
        "lean_outcomes": dict(sorted(outcomes.items())),
        "reasoning_tokens": {
            "positive_count": sum(value > 0 for value in reasoning),
            "positive_rate": sum(value > 0 for value in reasoning) / n,
            "min": min(reasoning),
            "median": statistics.median(reasoning),
            "p90": sorted(reasoning)[max(0, int(0.9 * len(reasoning)) - 1)],
            "max": max(reasoning),
        },
        "tokens": {"input": sum(row["tokens_in"] for row in rows), "output_including_reasoning": sum(row["tokens_out"] for row in rows)},
        "cost_usd": sum(float(row["cost_usd"]) for row in rows),
        "wall_seconds": wall,
        "examples_per_minute": n / wall * 60 if wall else 0.0,
        "cost_per_verified_correct": (sum(float(row["cost_usd"]) for row in rows) / solved) if solved else None,
        "by_grid": _group_metrics(rows, "grid"),
        "by_house": _group_metrics(rows, "houses"),
    }


def compute_metrics(run_dir):
    by_budget = {}
    for value in BUDGETS:
        label = _budget_label(value)
        path = run_dir / "results" / f"{label}.jsonl"
        if not path.exists():
            raise FileNotFoundError(f"missing per-budget results: {path}")
        by_budget[label] = _read_jsonl(path)
    per_budget = {
        label: _budget_metrics(rows, sum(float(r["elapsed_seconds"]) for r in rows))
        for label, rows in by_budget.items()
    }
    curve = []
    cost_per_verified = {}
    coverage_by_budget = {}
    for label in sorted(per_budget, key=_budget_sort_key):
        m = per_budget[label]
        curve.append({
            "budget": label,
            "coverage": m["coverage"],
            "cost_usd": m["cost_usd"],
            "median_reasoning_tokens": m["reasoning_tokens"]["median"],
            "max_reasoning_tokens": m["reasoning_tokens"]["max"],
            "truncation_count": m["truncation"],
        })
        coverage_by_budget[label] = m["coverage"]
        cost_per_verified[label] = m["cost_per_verified_correct"]
    return {
        "per_budget": per_budget,
        "verifier_value_curve": curve,
        "coverage_by_budget": coverage_by_budget,
        "cost_per_verified_correct": cost_per_verified,
        "totals": {
            "n_problems": len(next(iter(by_budget.values()), [])),
            "budgets": list(by_budget),
            "total_cost_usd": sum(m["cost_usd"] for m in per_budget.values()),
        },
    }


def prepare(compiled, output, executable, n=N_PUZZLES):
    if (output / "configs" / "puzzles.jsonl").exists():
        raise FileExistsError(f"refusing to overwrite prepared gate: {output}")
    output.mkdir(parents=True, exist_ok=True)
    (output / "configs").mkdir(exist_ok=True)
    (output / "raw").mkdir(exist_ok=True)
    problems = load_compiled_problems(compiled)
    selected = select_puzzles(problems, n, SELECTION_SEED)
    _write_jsonl(output / "configs" / "puzzles.jsonl", selected)
    config = {
        "model": CHEAP_MODEL,
        "endpoint": OPENROUTER_ENDPOINT,
        "temperature": 0.1,
        "seed": SEED,
        "workers": WORKERS_DEFAULT,
        "budgets": [_budget_label(v) for v in BUDGETS],
        "request_max_tokens": REQUEST_MAX_TOKENS,
        "answer_budget": ANSWER_BUDGET,
        "full_reasoning_budget": FULL_REASONING_BUDGET,
        "mode": "Mode-0 single-shot",
    }
    _write_json(output / "configs" / "config.json", config)
    (output / "configs" / "prompt_template.txt").write_text(PROMPT_TEXT, encoding="utf-8")
    for name in ("results.jsonl", "failures.jsonl"):
        (output / name).write_text("", encoding="utf-8")
    house_bins = dict(sorted(Counter(str(p["size"]["houses"]) for p in selected).items()))
    grid_bins = dict(sorted(Counter(p["source"]["grid"] for p in selected).items()))
    (output / "status.md").write_text(
        f"# {GATE}\n\nPrepared {n} balanced puzzles across budgets {[_budget_label(v) for v in BUDGETS]}.\n",
        encoding="utf-8",
    )
    _write_json(output / "manifest.json", {
        "gate": GATE,
        "state": "prepared",
        "n": n,
        "model": CHEAP_MODEL,
        "prompt_hash": hashlib.sha256(PROMPT_TEXT.encode()).hexdigest(),
        "config_hash": _json_hash(config),
        "selection_seed": SELECTION_SEED,
        "budgets": [_budget_label(v) for v in BUDGETS],
        "house_bins": house_bins,
        "grid_bins": grid_bins,
        "correctness_judge": "Lean check_candidate only",
    })
    _write_json(output / "metrics.json", {})
    (output / "summary.md").write_text(f"# {GATE}\n\nPrepared; evaluation not yet run.\n", encoding="utf-8")
    return selected


def smoke(run_dir, executable, budgets=None, n=SMOKE_N, workers=8):
    smoke_budgets = list(budgets) if budgets is not None else list(SMOKE_BUDGETS)
    puzzles_path = run_dir / "configs" / "puzzles.jsonl"
    if not puzzles_path.exists():
        raise FileNotFoundError(f"missing prepared puzzles: {puzzles_path}")
    puzzles = _read_jsonl(puzzles_path)[:n]
    started = time.monotonic()
    by_budget = {}
    for budget_value in smoke_budgets:
        budget_rows = run_one_budget(
            puzzles,
            budget_value,
            run_dir,
            executable,
            workers,
            CHEAP_MODEL,
            REQUEST_MAX_TOKENS,
            0.1,
            SEED,
            {"completed": 0},
            len(puzzles) * len(smoke_budgets),
            threading.Lock(),
            started,
        )
        by_budget[_budget_label(budget_value)] = budget_rows
    smoke_metrics = compute_smoke_metrics(by_budget)
    smoke_metrics["wall_seconds"] = time.monotonic() - started
    smoke_metrics["healthy"] = smoke_health(by_budget)
    _write_json(run_dir / "smoke_metrics.json", smoke_metrics)
    return smoke_metrics


def compute_smoke_metrics(by_budget):
    out = {"per_budget": {}}
    for label, rows in by_budget.items():
        n = len(rows)
        if n == 0:
            out["per_budget"][label] = {"n": 0}
            continue
        reasoning = [int(row["reasoning_tokens"] or 0) for row in rows]
        out["per_budget"][label] = {
            "n": n,
            "median_reasoning_tokens": statistics.median(reasoning),
            "max_reasoning_tokens": max(reasoning),
            "truncation_count": sum(row["finish_reason"] == "length" for row in rows),
            "candidate_parsed": sum(bool(row["candidate_parsed"]) for row in rows),
            "lean_checked": sum(bool(row["lean_kind"]) for row in rows),
            "finish_reasons": dict(Counter(str(row["finish_reason"]) for row in rows)),
            "reasoning_positive": sum(value > 0 for value in reasoning),
        }
    return out


def smoke_health(by_budget):
    expected = {BudgetSpec.from_value(v).label for v in SMOKE_BUDGETS}
    actual = set(by_budget)
    if expected != actual:
        return False
    for label, rows in by_budget.items():
        if not rows:
            return False
        for row in rows:
            if not row["candidate_parsed"]:
                return False
            if not row["lean_kind"]:
                return False
            if label == "0" and row["reasoning_tokens"] > 0:
                return False
    return True


def finalize(output, executable, git_commit, n_expected=N_PUZZLES):
    run_dir = output
    for value in BUDGETS:
        label = _budget_label(value)
        rows = _read_jsonl(run_dir / "results" / f"{label}.jsonl")
        if len(rows) != n_expected:
            raise RuntimeError(f"budget {label}: expected {n_expected} rows, found {len(rows)}")
        puzzles = {p["id"]: p for p in _read_jsonl(run_dir / "configs" / "puzzles.jsonl")}
        for row in rows:
            problem = puzzles[row["id"]]
            candidate_text = json.dumps(row["parsed_final_json"]) if row["parsed_final_json"] is not None else ""
            kind, status, correct, verdict = check_candidate(executable, problem, candidate_text)
            row.update(lean_kind=kind, lean_status=status, correct=correct, lean_verdict=verdict)
        _write_jsonl(run_dir / "results" / f"{label}.jsonl", rows)
    all_rows = []
    for value in BUDGETS:
        all_rows.extend(_read_jsonl(run_dir / "results" / f"{_budget_label(value)}.jsonl"))
    _write_jsonl(run_dir / "results.jsonl", all_rows)
    _write_jsonl(run_dir / "failures.jsonl", [row for row in all_rows if not row["correct"]])
    metrics = compute_metrics(run_dir)
    _write_json(run_dir / "metrics.json", metrics)
    metadata_blob = json.loads((run_dir / "run_metadata.json").read_text())
    manifest = json.loads((output / "manifest.json").read_text())
    manifest.update({
        "state": "complete",
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "git_commit_before_results": git_commit,
        "workers": WORKERS_DEFAULT,
        "token_caps": {
            "answer_tokens": ANSWER_BUDGET,
            "reasoning_tokens_full": FULL_REASONING_BUDGET,
            "request_max_tokens": REQUEST_MAX_TOKENS,
        },
        "raw_outputs_stored_before_parsing": True,
        "result_metrics_recomputed_from_results_jsonl": True,
        "commands": {
            "prepare": "PYTHONPATH=src .venv/bin/python scripts/run_stage6_budget_sweep.py prepare --n 200",
            "smoke": "PYTHONPATH=src .venv/bin/python scripts/run_stage6_budget_sweep.py smoke --n 6 --workers 8",
            "full": "PYTHONPATH=src .venv/bin/python scripts/run_stage6_budget_sweep.py run --workers 12",
            "finalize": "PYTHONPATH=src .venv/bin/python scripts/run_stage6_budget_sweep.py finalize",
        },
    })
    _write_json(output / "manifest.json", manifest)
    (output / "summary.md").write_text(_render_summary(all_rows, metrics, metadata_blob, run_dir), encoding="utf-8")
    _write_status(run_dir / "status.md", len(all_rows), len(all_rows), WORKERS_DEFAULT, metadata_blob.get("wall_seconds", 0.0), complete=True)
    return metrics


def _reasoning_excerpt(row, run_dir):
    rel = Path(row["raw_path"])
    candidates = [run_dir.parent / rel,
                  run_dir / rel.name,
                  Path.cwd() / rel,
                  Path.cwd() / rel.name]
    path = next((c for c in candidates if c.exists()), None)
    if path is None:
        return "(reasoning content unavailable; token metadata is retained)"
    try:
        raw = json.loads(path.read_text())
        message = raw["provider"]["response"]["choices"][0]["message"]
        reasoning = message.get("reasoning") or message.get("reasoning_content") or ""
        return re.sub(r"\s+", " ", reasoning).strip()[:500]
    except Exception:
        return "(reasoning content unavailable; token metadata is retained)"


def _render_summary(all_rows, metrics, metadata, run_dir):
    per_budget = metrics["per_budget"]
    curve = metrics["verifier_value_curve"]
    cost_per_verified = metrics["cost_per_verified_correct"]
    total_cost = metrics["totals"]["total_cost_usd"]
    wall = metadata.get("wall_seconds", 0.0)
    n_probs = metrics["totals"]["n_problems"]
    lines = [
        f"# {GATE}",
        "",
        "Verdict: budget sweep complete; coverage and cost as a function of reasoning budget.",
        "",
        f"- Problems evaluated per budget: {n_probs}.",
        f"- Budgets evaluated: {', '.join(metrics['totals']['budgets'])}.",
        f"- Wall-clock time: {wall / 60:.1f} min.",
        f"- Total cost: ${total_cost:.6f}.",
        "",
        "## Verifier-value-vs-budget",
        "",
        "| budget | coverage | cost USD | median reason tok | max reason tok | truncations |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for row in curve:
        lines.append(
            f"| {row['budget']} | {row['coverage']:.1%} | {row['cost_usd']:.6f} | "
            f"{row['median_reasoning_tokens']:.0f} | {row['max_reasoning_tokens']:.0f} | "
            f"{row['truncation_count']} |"
        )
    lines += ["", "## Cost per verified-correct", ""]
    for label in sorted(cost_per_verified, key=_budget_sort_key):
        cpc = cost_per_verified[label]
        lines.append(f"- budget `{label}`: {('$%.6f' % cpc) if cpc is not None else 'undefined (no verified-correct)'}")
    lines += ["", "## Budget x house bin", "",
              "| budget \\ houses | " + " | ".join(str(h) for h in range(2, 7)) + " |",
              "| --- | " + " | ".join("---" for _ in range(5)) + " |"]
    for label in sorted(per_budget, key=_budget_sort_key):
        by_house = per_budget[label]["by_house"]
        row_cells = []
        for house in range(2, 7):
            cell = by_house.get(str(house), {})
            row_cells.append(f"{cell.get('solved', 0)}/{cell.get('n', 0)}")
        lines.append(f"| {label} | " + " | ".join(row_cells) + " |")
    grids = sorted({k for m in per_budget.values() for k in m["by_grid"]})
    lines += ["", "## Budget x grid", "",
              "| budget \\ grid | " + " | ".join(grids) + " |",
              "| --- | " + " | ".join("---" for _ in grids) + " |"]
    for label in sorted(per_budget, key=_budget_sort_key):
        by_grid = per_budget[label]["by_grid"]
        cells = []
        for grid in grids:
            cell = by_grid.get(grid, {})
            cells.append(f"{cell.get('solved', 0)}/{cell.get('n', 0)}")
        lines.append(f"| {label} | " + " | ".join(cells) + " |")
    lines += ["", "## Readable samples", ""]
    for label in metrics["totals"]["budgets"]:
        rows_for_label = [row for row in all_rows if row["budget"] == label]
        solved_row = next((row for row in rows_for_label if row["correct"]), None)
        if solved_row is None:
            continue
        lines += [
            f"### budget `{label}` solved `{solved_row['id']}`",
            "",
            f"Lean verdict: `{solved_row['lean_kind']}/{solved_row['lean_status']}`.",
            "",
            f"Reasoning excerpt: {_reasoning_excerpt(solved_row, run_dir)}",
            "",
        ]
    return "\n".join(lines)
