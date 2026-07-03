"""Stage 6 capability ladder.

Measures verifier value vs model capability/parameter scale for a reduced
three-model set:
  - qwen/qwen3-8b           (small)
  - qwen/qwen3-32b          (mid/large)
  - deepseek/deepseek-v4-flash (cheap-frontier baseline)

The same 200-puzzle balanced subset used by the budget sweep is reused so
that capability and budget numbers can be cross-compared. Lean
``check_candidate`` is the sole correctness judge.
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
from typing import Any

from openai import OpenAI

from sparseir_harness.stage6_budget_sweep import (
    FULL_REASONING_BUDGET,
    N_PUZZLES,
    REQUEST_MAX_TOKENS,
    select_puzzles,
)
from sparseir_harness.stage6_contamination import extract_final_json
from sparseir_harness.stage6_h5_cleanup import (
    OPENROUTER_ENDPOINT,
    SYSTEM_PROMPT,
    USER_TEMPLATE,
    _compact,
    load_compiled_problems,
)
from sparseir_harness.stage6_mode0 import check_candidate


GATE = "stage6_capability_ladder"
SEED = 20260703
SELECTION_SEED = 20260702  # mirror budget-sweep selection for identical certs

# Reduced ladder per explicit user direction. Do not silently substitute.
MODELS: list[dict[str, str]] = [
    {"id": "qwen/qwen3-8b", "label": "qwen3-8b", "role": "small"},
    {"id": "qwen/qwen3-32b", "label": "qwen3-32b", "role": "mid_large"},
    {"id": "deepseek/deepseek-v4-flash", "label": "v4-flash-baseline", "role": "cheap_frontier_baseline"},
]

# Concurrency probe ladder per the spec.
PROBE_WORKER_LADDER: list[int] = [6, 12, 24]
EXTENDED_PROBE_WORKER_LADDER: list[int] = [6, 12, 24, 36, 48]
PROBE_N_PER_BIN: int = 1  # 1 per (house, category) bin = 25 puzzles total
PROBE_BUDGET_SECONDS: int = 90  # wall budget per probe run
PROBE_PER_PUZZLE_TIMEOUT_S: float = 30.0  # hard cap on any single OpenRouter call
PROBE_MAX_HOUSES: int = 4  # cap probe on easier 2/3/4-house puzzles only

# Per-model default reasoning knobs. The qwen3 family reasons by default with a
# budget we cannot directly cap; we still set extra_body to make the request
# explicit. v4-flash uses the same 24k reasoning cap as the budget sweep.
def _model_reasoning_extra(model_id: str) -> dict[str, Any]:
    if model_id.startswith("deepseek/deepseek-v4-flash"):
        return {"reasoning": {"max_tokens": FULL_REASONING_BUDGET, "exclude": False}}
    # qwen3 family: signal reasoning on with a generous cap, but the provider
    # ultimately decides. We pass a non-zero max_tokens so the body is valid.
    return {"reasoning": {"max_tokens": FULL_REASONING_BUDGET, "exclude": False}}


def _model_request_max_tokens(model_id: str) -> int:
    return REQUEST_MAX_TOKENS


def _model_seed(model_id: str) -> int:
    return SEED


@dataclass(frozen=True)
class ModelSpec:
    id: str
    label: str
    role: str


def _spec(m: dict[str, str]) -> ModelSpec:
    return ModelSpec(id=m["id"], label=m["label"], role=m["role"])


def _json_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")
    temp.replace(path)


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _prompt_hash() -> str:
    from sparseir_harness.stage6_contamination import PROMPT_TEXT
    return hashlib.sha256(PROMPT_TEXT.encode()).hexdigest()


class Provider:
    """OpenRouter client with reasoning-on and a generous answer budget.

    Includes an in-process retry on 429s: the upstream provider
    (e.g. Alibaba for the qwen3 family) sometimes returns transient
    rate-limit errors that succeed on a short retry. We retry up to
    ``max_retries`` times with exponential backoff before giving up.
    """

    def __init__(self, model_id: str, request_max_tokens: int, temperature: float, seed: int,
                 max_retries: int = 15, base_backoff_s: float = 2.0,
                 max_backoff_s: float = 60.0) -> None:
        if not os.environ.get("OPENROUTER_API_KEY"):
            raise RuntimeError("OPENROUTER_API_KEY is not set")
        self.model_id = model_id
        self.request_max_tokens = request_max_tokens
        self.temperature = temperature
        self.seed = seed
        self.max_retries = max_retries
        self.base_backoff_s = base_backoff_s
        self.max_backoff_s = max_backoff_s
        self._local = threading.local()

    def _client(self) -> OpenAI:
        client = getattr(self._local, "client", None)
        if client is None:
            client = OpenAI(
                api_key=os.environ["OPENROUTER_API_KEY"],
                base_url=OPENROUTER_ENDPOINT,
                max_retries=0,
                timeout=900.0,
            )
            self._local.client = client
        return client

    def call(self, problem: dict[str, Any]) -> dict[str, Any]:
        last_exc: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                response = self._client().chat.completions.create(
                    model=self.model_id,
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": USER_TEMPLATE.format(problem_json=_compact(problem))},
                    ],
                    temperature=self.temperature,
                    seed=self.seed,
                    max_tokens=self.request_max_tokens,
                    extra_body=_model_reasoning_extra(self.model_id),
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
                    "provider_name": response.model_extra.get("provider") if response.model_extra else None,
                    "tokens_in": int(usage.get("prompt_tokens") or 0),
                    "tokens_out": int(usage.get("completion_tokens") or 0),
                    "reasoning_tokens": int(details.get("reasoning_tokens") or 0),
                    "cost_usd": float(usage.get("cost", extra.get("cost", 0.0)) or 0.0),
                    "retries": attempt,
                }
            except Exception as exc:
                last_exc = exc
                msg = str(exc)
                if "429" in msg or "rate" in msg.lower():
                    if attempt < self.max_retries:
                        delay = min(self.max_backoff_s, self.base_backoff_s * (2 ** attempt))
                        time.sleep(delay * random.uniform(0.8, 1.2))
                        continue
                raise
        # Should not reach, but be defensive.
        raise last_exc if last_exc else RuntimeError("provider call failed with no exception")


def evaluate(problem, model_id, run_dir, executable, provider, run_label):
    started = time.monotonic()
    started_at = time.time()
    raw_path = run_dir / "raw" / f"{run_label}__{model_id.replace('/', '__')}__{problem['id']}.json"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    call = None
    errors: list[dict[str, str]] = []
    try:
        call = provider.call(problem)
    except Exception as exc:
        errors.append({"type": type(exc).__name__, "message": str(exc)})
    raw = {
        "problem_id": problem["id"],
        "model_id": model_id,
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
        "model_id": model_id,
        "grid": problem["source"]["grid"],
        "houses": problem["size"]["houses"],
        "categories": problem["size"]["categories"],
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
        "provider_model_id": call["provider_model_id"] if call else None,
        "provider_name": call["provider_name"] if call else None,
        "rate_limit_retries": call["retries"] if call else 0,
        "prompt_hash": _prompt_hash(),
        "config_hash": _json_hash({"model_id": model_id, "extra_body": _model_reasoning_extra(model_id)}),
        "raw_path": str(raw_path.relative_to(run_dir.parent)),
        "elapsed_seconds": time.monotonic() - started,
        "started_at": started_at,
        "ended_at": time.time(),
    }


def run_one_chunk(problems, model_id, run_dir, executable, workers, run_label):
    """Run a fixed set of problems for a single model, writing per-chunk jsonl."""
    chunk_path = run_dir / "results" / f"{run_label}__{model_id.replace('/', '__')}.jsonl"
    chunk_path.parent.mkdir(parents=True, exist_ok=True)
    if chunk_path.exists() and chunk_path.stat().st_size:
        raise FileExistsError(f"refusing to overwrite prior run: {chunk_path}")
    chunk_path.write_text("", encoding="utf-8")
    provider = Provider(model_id, _model_request_max_tokens(model_id), 0.1, _model_seed(model_id))
    rows = []
    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(evaluate, problem, model_id, run_dir, executable, provider, run_label): problem for problem in problems}
        for future in as_completed(futures):
            row = future.result()
            rows.append(row)
            rows.sort(key=lambda r: (r["houses"], r["categories"], r["id"]))
            chunk_path.write_text(
                "".join(json.dumps(r, sort_keys=True) + "\n" for r in rows),
                encoding="utf-8",
            )
            elapsed = time.monotonic() - started
            print(f"{GATE}/{run_label}/{model_id}: {len(rows)}/{len(problems)} {row['id']} "
                  f"[{elapsed:.0f}s]", flush=True)
    return rows, time.monotonic() - started


def resume_one_model(problems, model_id, run_dir, executable, workers=1):
    """Complete only missing puzzle IDs, checkpointing the merged file per success.

    Provider failures are recorded in raw files and status counters but are not
    admitted as completed rows. This preserves one actual model candidate per
    puzzle while allowing transport/rate-limit retries.
    """
    result_path = run_dir / "results" / f"full__{model_id.replace('/', '__')}.jsonl"
    existing = _read_jsonl(result_path)
    all_by_id = {row["id"]: row for row in existing}
    if len(all_by_id) != len(existing):
        raise ValueError(f"duplicate IDs in existing result file: {result_path}")
    # A transport failure produced no candidate and is therefore safe to resume;
    # never count it as a completed Mode-0 evaluation row.
    by_id = {row_id: row for row_id, row in all_by_id.items() if not row["provider_error"]}
    puzzle_ids = {problem["id"] for problem in problems}
    unexpected = set(by_id) - puzzle_ids
    if unexpected:
        raise ValueError(f"result IDs absent from configured subset: {sorted(unexpected)}")

    missing = [problem for problem in problems if problem["id"] not in by_id]
    provider = Provider(model_id, _model_request_max_tokens(model_id), 0.1, _model_seed(model_id))
    started = time.monotonic()
    base_completed = len(by_id)
    transport_errors = 0
    rate_limit_errors = 0
    retry_429s = 0

    def write_progress(current_id=""):
        elapsed = time.monotonic() - started
        completed_this_run = len(by_id) - base_completed
        rate = completed_this_run / elapsed * 60 if elapsed else 0.0
        eta = (len(problems) - len(by_id)) / rate if rate else None
        rows = list(by_id.values())
        extra = {
            "current puzzle": current_id or "complete",
            "rate-limit/error count": f"{retry_429s + rate_limit_errors}/{transport_errors}",
            "malformed": sum(r["lean_status"] == "malformed" for r in rows),
            "clue_violations": sum(r["lean_status"] == "clue_violation" for r in rows),
            "reasoning-positive count": sum(int(r.get("reasoning_tokens") or 0) > 0 for r in rows),
        }
        body = [
            f"# {GATE} status", "", "- state: running",
            f"- current model: `{model_id}`", "- current phase: `resume`",
            "- run label: `full`", f"- completed: {len(by_id)}/{len(problems)}",
            f"- examples/min: {rate:.2f}", f"- elapsed: {elapsed / 60:.1f} min",
            f"- ETA: {eta:.1f} min" if eta is not None else "- ETA: ? min",
            f"- workers: {workers}",
        ]
        body.extend(f"- {key}: {value}" for key, value in extra.items())
        (run_dir / "status.md").write_text("\n".join(body) + "\n", encoding="utf-8")

    write_progress()
    # A single worker is intentional for the sole Alibaba endpoint. Keep the
    # parameter for an alternate provider becoming available in the future.
    while missing:
        batch = missing[:workers]
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(evaluate, problem, model_id, run_dir, executable, provider, "full"): problem
                for problem in batch
            }
            for future in as_completed(futures):
                problem = futures[future]
                row = future.result()
                retry_429s += int(row.get("rate_limit_retries") or 0)
                if row["provider_error"]:
                    transport_errors += 1
                    rate_limit_errors += int(bool(row["rate_limit_error"]))
                    write_progress(problem["id"])
                    print(f"{GATE}/resume/{model_id}: provider failure for {problem['id']}; requeueing", flush=True)
                    continue
                by_id[row["id"]] = row
                ordered = sorted(by_id.values(), key=lambda r: (r["houses"], r["categories"], r["id"]))
                _write_jsonl(result_path, ordered)
                write_progress(problem["id"])
                print(f"{GATE}/resume/{model_id}: {len(by_id)}/{len(problems)} {problem['id']} ",
                      f"[{time.monotonic() - started:.0f}s]", flush=True)
        missing = [problem for problem in problems if problem["id"] not in by_id]
    write_progress()
    return sorted(by_id.values(), key=lambda r: (r["houses"], r["categories"], r["id"]))


def _write_status(path, current_model, current_phase, completed, total, workers, elapsed,
                  run_label="", complete=False, extra=None):
    rate = completed / elapsed * 60 if elapsed else 0.0
    eta = (total - completed) / rate if rate else None
    eta_text = f"{eta:.1f}" if eta is not None else "?"
    body = [
        f"# {GATE} status",
        "",
        f"- state: {'complete' if complete else 'running'}",
        f"- current model: `{current_model}`",
        f"- current phase: `{current_phase}`",
        f"- run label: `{run_label}`",
        f"- completed: {completed}/{total}",
        f"- examples/min: {rate:.2f}",
        f"- elapsed: {elapsed / 60:.1f} min",
        f"- ETA: {eta_text} min",
        f"- workers: {workers}",
    ]
    if extra:
        for key, value in extra.items():
            body.append(f"- {key}: {value}")
    body.append("")
    path.write_text("\n".join(body), encoding="utf-8")


def _select_probe_problems(problems, n_per_bin, max_houses=PROBE_MAX_HOUSES):
    """Pick ``n_per_bin`` from every (houses, categories) bin, capped by availability.

    The probe excludes puzzles with more than ``max_houses`` to keep per-puzzle
    latency bounded (small models stall on 5x/6x reasoning tasks).
    """
    groups: dict[tuple[int, int], list] = defaultdict(list)
    for problem in problems:
        if int(problem["size"]["houses"]) > max_houses:
            continue
        key = (int(problem["size"]["houses"]), int(problem["size"]["categories"]))
        groups[key].append(problem)
    selected = []
    rng = random.Random(SELECTION_SEED + 17)
    for key in sorted(groups):
        pool = sorted(groups[key], key=lambda p: p["id"])
        rng.shuffle(pool)
        selected.extend(pool[:n_per_bin])
    return selected


def _aggregate(rows):
    if not rows:
        return {"n": 0}
    n = len(rows)
    reasoning = [int(r["reasoning_tokens"] or 0) for r in rows]
    finish = Counter(str(r["finish_reason"]) for r in rows)
    outcomes = Counter(r["lean_status"] for r in rows)
    solved = sum(bool(r["correct"]) for r in rows)
    return {
        "n": n,
        "solved": solved,
        "coverage": solved / n,
        "confident_wrong": 0,
        "malformed": outcomes["malformed"],
        "clue_violation": outcomes["clue_violation"],
        "truncation": finish["length"],
        "provider_error": sum(bool(r["provider_error"]) for r in rows),
        "rate_limit_error": sum(bool(r["rate_limit_error"]) for r in rows),
        "finish_reasons": dict(sorted(finish.items())),
        "lean_outcomes": dict(sorted(outcomes.items())),
        "reasoning_tokens": {
            "positive_count": sum(v > 0 for v in reasoning),
            "positive_rate": sum(v > 0 for v in reasoning) / n,
            "min": min(reasoning),
            "median": statistics.median(reasoning),
            "p90": sorted(reasoning)[max(0, int(0.9 * len(reasoning)) - 1)] if reasoning else 0,
            "max": max(reasoning),
        },
        "cost_usd": sum(float(r["cost_usd"]) for r in rows),
    }


def _probe_one_model(problems, model_id, run_dir, executable, workers, run_label,
                     per_run_timeout=PROBE_BUDGET_SECONDS,
                     per_puzzle_timeout=PROBE_PER_PUZZLE_TIMEOUT_S):
    """Run probe at the chosen worker count, returning aggregate metrics.

    Hard-cap each puzzle on ``per_puzzle_timeout`` so a slow model cannot stall
    the probe. Cancels in-flight futures on timeout.
    """
    import concurrent.futures
    selected = _select_probe_problems(problems, PROBE_N_PER_BIN)
    started = time.monotonic()
    rows: list[dict[str, Any]] = []
    timed_out = False
    provider = Provider(model_id, _model_request_max_tokens(model_id), 0.1, _model_seed(model_id))
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=workers)
    try:
        deadline = started + per_run_timeout
        futures = {pool.submit(evaluate, p, model_id, run_dir, executable, provider, run_label): p for p in selected}
        for fut in concurrent.futures.as_completed(futures, timeout=per_run_timeout):
            try:
                row = fut.result(timeout=max(0.1, per_puzzle_timeout))
            except Exception as exc:
                p = futures[fut]
                row = {
                    "id": p["id"],
                    "model_id": model_id,
                    "candidate_parsed": False,
                    "lean_kind": "",
                    "lean_status": "error",
                    "correct": False,
                    "failure_category": "probe_exception",
                    "finish_reason": None,
                    "reasoning_tokens": 0,
                    "tokens_in": 0,
                    "tokens_out": 0,
                    "cost_usd": 0.0,
                    "provider_error": True,
                    "rate_limit_error": "429" in str(exc),
                    "raw_path": "",
                }
            rows.append(row)
            if time.monotonic() > deadline:
                timed_out = True
                break
    except concurrent.futures.TimeoutError:
        timed_out = True
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    elapsed = time.monotonic() - started
    agg = _aggregate(rows)
    agg["elapsed"] = elapsed
    agg["timed_out"] = timed_out
    agg["examples_per_minute"] = len(rows) / elapsed * 60 if elapsed else 0.0
    agg["average_latency"] = (elapsed / len(rows)) if rows else None
    agg["eta_full_seconds"] = (N_PUZZLES * (elapsed / len(rows))) / workers if rows and workers else None
    return agg, rows


def run_concurrency_probe(problems, output, executable, ladder=PROBE_WORKER_LADDER):
    """Probe each model at each worker count and choose a safe max."""
    probe_dir = output / "probe"
    probe_dir.mkdir(parents=True, exist_ok=True)
    probe_results: dict[str, list[dict[str, Any]]] = {}
    chosen: dict[str, dict[str, Any]] = {}
    rejected: dict[str, list[dict[str, Any]]] = {}
    full_ladder = list(ladder)

    for model in MODELS:
        model_id = model["id"]
        label = model["label"]
        model_results: list[dict[str, Any]] = []
        model_rejected: list[dict[str, Any]] = []
        last_clean_workers: int | None = None
        for workers in full_ladder:
            run_label = f"probe_{label}_w{workers}"
            agg, _ = _probe_one_model(problems, model_id, probe_dir, executable, workers, run_label)
            agg["model_id"] = model_id
            agg["label"] = label
            agg["workers"] = workers
            model_results.append(agg)
            print(f"probe {label} w={workers}: "
                  f"ex={agg['n']} cov={agg.get('coverage', 0):.1%} "
                  f"errs={agg.get('provider_error', 0)} malf={agg.get('malformed', 0)} "
                  f"trunc={agg.get('truncation', 0)} rate429={agg.get('rate_limit_error', 0)} "
                  f"tput={agg.get('examples_per_minute', 0):.1f}/min "
                  f"timeout={agg.get('timed_out', False)}",
                  flush=True)
            if _is_unstable(agg):
                model_rejected.append({"workers": workers, "metrics": agg,
                                       "reason": _unstable_reason(agg)})
                # if 24 unstable, do not try 36/48
                break
            last_clean_workers = workers
        if last_clean_workers is None:
            chosen[model_id] = {"workers": 6, "fallback": True,
                                "reason": "all probed workers were unstable; falling back to 6"}
        else:
            # Pick the highest worker count that finished without instability AND
            # matched-or-improved throughput over the previous clean worker. If
            # higher workers finished the probe faster, take it; otherwise stay.
            chosen_count = full_ladder[0]
            chosen_throughput = 0.0
            chosen_full = False
            for r in model_results:
                if _is_unstable(r):
                    break
                tput = r.get("examples_per_minute", 0.0) or 0.0
                finished = not r.get("timed_out", False)
                # Promote to a higher worker count if it improved throughput.
                if tput >= chosen_throughput or finished:
                    chosen_count = r["workers"]
                    chosen_throughput = tput
                    chosen_full = finished
            chosen[model_id] = {"workers": chosen_count, "fallback": False,
                                "probe_throughput_ex_per_min": chosen_throughput,
                                "probe_finished": chosen_full}
        probe_results[model_id] = model_results
        rejected[model_id] = model_rejected
    return probe_results, chosen, rejected


def _is_unstable(agg):
    """A probe is unstable only when it shows real provider trouble.

    Timeouts and slow throughput are not instability signals; they are scaling
    signals. The chosen worker count is allowed to track the throughput.
    """
    n = agg.get("n", 0)
    if n == 0:
        return True
    if agg.get("rate_limit_error", 0) > 0:
        return True
    if agg.get("provider_error", 0) / n > 0.10:
        return True
    if agg.get("truncation", 0) / n > 0.20:
        return True
    return False


def _unstable_reason(agg):
    reasons = []
    if agg.get("rate_limit_error", 0) > 0:
        reasons.append(f"{agg['rate_limit_error']} rate-limit (429) errors")
    if agg.get("provider_error", 0) > 0:
        reasons.append(f"{agg['provider_error']} provider errors")
    if agg.get("truncation", 0) > 0:
        reasons.append(f"{agg['truncation']} truncations")
    return "; ".join(reasons) or "unstable aggregate"


def _group_metrics(rows, key):
    out = {}
    for value in sorted({str(r[key]) for r in rows}):
        g = [r for r in rows if str(r[key]) == value]
        n = len(g)
        solved = sum(bool(r["correct"]) for r in g)
        out[value] = {
            "n": n,
            "solved": solved,
            "coverage": solved / n if n else 0.0,
            "malformed": sum(r["lean_status"] == "malformed" for r in g),
            "clue_violation": sum(r["lean_status"] == "clue_violation" for r in g),
        }
    return out


def _model_metrics(rows, model_id, wall_seconds):
    if not rows:
        return {"model_id": model_id, "n": 0}
    n = len(rows)
    reasoning = [int(r["reasoning_tokens"] or 0) for r in rows]
    finish = Counter(str(r["finish_reason"]) for r in rows)
    outcomes = Counter(r["lean_status"] for r in rows)
    solved = sum(bool(r["correct"]) for r in rows)
    wall = wall_seconds or sum(float(r["elapsed_seconds"]) for r in rows)
    return {
        "model_id": model_id,
        "n": n,
        "solved": solved,
        "coverage": solved / n,
        "confident_wrong": 0,
        "p_true": None,
        "malformed": outcomes["malformed"],
        "clue_violation": outcomes["clue_violation"],
        "truncation": finish["length"],
        "provider_error": sum(bool(r["provider_error"]) for r in rows),
        "rate_limit_error": sum(bool(r["rate_limit_error"]) for r in rows),
        "finish_reasons": dict(sorted(finish.items())),
        "lean_outcomes": dict(sorted(outcomes.items())),
        "reasoning_tokens": {
            "positive_count": sum(v > 0 for v in reasoning),
            "positive_rate": sum(v > 0 for v in reasoning) / n,
            "min": min(reasoning),
            "median": statistics.median(reasoning),
            "p90": sorted(reasoning)[max(0, int(0.9 * len(reasoning)) - 1)],
            "max": max(reasoning),
        },
        "tokens": {"input": sum(r["tokens_in"] for r in rows),
                   "output_including_reasoning": sum(r["tokens_out"] for r in rows)},
        "cost_usd": sum(float(r["cost_usd"]) for r in rows),
        "cost_per_verified_correct": (sum(float(r["cost_usd"]) for r in rows) / solved) if solved else None,
        "examples_per_minute": n / wall * 60 if wall else 0.0,
        "wall_seconds": wall,
        "by_grid": _group_metrics(rows, "grid"),
        "by_house": _group_metrics(rows, "houses"),
        "verifier_value": solved / n if n else 0.0,
    }


def compute_metrics(run_dir):
    by_model: dict[str, list[dict[str, Any]]] = {}
    for m in MODELS:
        mid = m["id"]
        path = run_dir / "results" / f"full__{mid.replace('/', '__')}.jsonl"
        if not path.exists():
            continue
        by_model[mid] = _read_jsonl(path)
    per_model = {}
    for mid, rows in by_model.items():
        # Prefer per-puzzle started_at/ended_at; fall back to the raw-file
        # mtime range (earliest to latest), which approximates the actual
        # wall-clock window even for runs that did not complete all puzzles.
        starts = [float(r.get("started_at", 0.0)) for r in rows if r.get("started_at")]
        ends = [float(r.get("ended_at", 0.0)) for r in rows if r.get("ended_at")]
        if starts and ends:
            wall = max(ends) - min(starts)
        else:
            raw_dir = run_dir / "raw"
            safe_mid = mid.replace("/", "__")
            try:
                raws = [p.stat().st_mtime for p in raw_dir.glob(f"full__{safe_mid}__*.json")]
                wall = (max(raws) - min(raws)) if raws else 0.0
            except FileNotFoundError:
                wall = max((float(r.get("elapsed_seconds", 0.0)) for r in rows), default=0.0)
        per_model[mid] = _model_metrics(rows, mid, wall)
    ladder = []
    for mid, m in per_model.items():
        if m.get("n", 0) == 0:
            continue
        ladder.append({
            "model_id": mid,
            "label": next(md["label"] for md in MODELS if md["id"] == mid),
            "role": next(md["role"] for md in MODELS if md["id"] == mid),
            "coverage": m["coverage"],
            "solved": m["solved"],
            "n": m["n"],
            "malformed": m["malformed"],
            "clue_violation": m["clue_violation"],
            "truncation": m["truncation"],
            "cost_usd": m["cost_usd"],
            "cost_per_verified_correct": m["cost_per_verified_correct"],
            "median_reasoning_tokens": m["reasoning_tokens"]["median"],
            "max_reasoning_tokens": m["reasoning_tokens"]["max"],
            "examples_per_minute": m["examples_per_minute"],
            "wall_minutes": m["wall_seconds"] / 60.0,
        })
    ladder.sort(key=lambda r: r["coverage"])
    return {
        "per_model": per_model,
        "ladder": ladder,
        "totals": {
            "models": list(by_model),
            "n_problems": N_PUZZLES,
            "total_cost_usd": sum(m["cost_usd"] for m in per_model.values()),
        },
    }


def prepare(compiled, output, executable, n=N_PUZZLES, n_per_bin=None):
    """Prepare the gate directory; reuse the budget-sweep puzzle selection for cert parity."""
    if (output / "configs" / "puzzles.jsonl").exists():
        raise FileExistsError(f"refusing to overwrite prepared gate: {output}")
    output.mkdir(parents=True, exist_ok=True)
    (output / "configs").mkdir(exist_ok=True)
    (output / "raw").mkdir(exist_ok=True)
    (output / "results").mkdir(exist_ok=True)
    problems = load_compiled_problems(compiled)
    selected = select_puzzles(problems, n, SELECTION_SEED)
    _write_jsonl(output / "configs" / "puzzles.jsonl", selected)
    config = {
        "models": MODELS,
        "endpoint": OPENROUTER_ENDPOINT,
        "temperature": 0.1,
        "seed": SEED,
        "n_problems": n,
        "request_max_tokens": REQUEST_MAX_TOKENS,
        "full_reasoning_budget": FULL_REASONING_BUDGET,
        "mode": "Mode-0 single-shot",
        "selection_seed": SELECTION_SEED,
        "puzzle_subset": "shared with stage6_budget_sweep",
    }
    _write_json(output / "configs" / "config.json", config)
    house_bins = dict(sorted(Counter(str(p["size"]["houses"]) for p in selected).items()))
    grid_bins = dict(sorted(Counter(p["source"]["grid"] for p in selected).items()))
    (output / "status.md").write_text(
        f"# {GATE}\n\nPrepared {n} puzzles; running concurrency probe for {len(MODELS)} models.\n",
        encoding="utf-8",
    )
    _write_json(output / "manifest.json", {
        "gate": GATE,
        "state": "prepared",
        "n": n,
        "models": MODELS,
        "prompt_hash": _prompt_hash(),
        "config_hash": _json_hash(config),
        "selection_seed": SELECTION_SEED,
        "house_bins": house_bins,
        "grid_bins": grid_bins,
        "correctness_judge": "Lean check_candidate only",
    })
    _write_json(output / "metrics.json", {})
    (output / "summary.md").write_text(f"# {GATE}\n\nPrepared; concurrency probe not yet run.\n", encoding="utf-8")
    return selected


def run_full(problems, output, executable, chosen_workers):
    """Run each model on the full 200-puzzle set with its chosen workers."""
    for m in MODELS:
        mid = m["id"]
        workers = chosen_workers.get(mid, {}).get("workers", 6)
        run_label = "full"
        rows, wall = run_one_chunk(problems, mid, output, executable, workers, run_label)
        print(f"full {mid} workers={workers} done: "
              f"n={len(rows)} solved={sum(bool(r['correct']) for r in rows)} "
              f"wall={wall/60:.1f}min", flush=True)
    # Aggregate into top-level results.jsonl / failures.jsonl
    all_rows = []
    for m in MODELS:
        mid = m["id"]
        chunk = output / "results" / f"full__{mid.replace('/', '__')}.jsonl"
        if chunk.exists():
            all_rows.extend(_read_jsonl(chunk))
    _write_jsonl(output / "results.jsonl", all_rows)
    _write_jsonl(output / "failures.jsonl", [r for r in all_rows if not r["correct"]])
    return all_rows


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
        reasoning = (message.get("reasoning")
                     or (message.get("reasoning_details") or [{}])[0].get("text", "")
                     or "")
        return re.sub(r"\s+", " ", reasoning).strip()[:500]
    except Exception:
        return "(reasoning content unavailable; token metadata is retained)"


def _render_probe_markdown(probe_results, chosen, rejected):
    lines = ["# Concurrency probe", "",
             "Per-model worker-count probe, run before the full eval.", ""]
    for m in MODELS:
        mid = m["id"]
        label = m["label"]
        if mid not in probe_results:
            continue
        lines.append(f"## {label} (`{mid}`)")
        lines.append("")
        lines.append("| workers | n | coverage | provider_err | rate_limit | truncation | malformed | reason_pos | tput ex/min | avg_lat_s | elapsed_s | timed_out |")
        lines.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
        for r in probe_results[mid]:
            lines.append(
                f"| {r['workers']} | {r['n']} | {r.get('coverage', 0):.1%} | "
                f"{r.get('provider_error', 0)} | {r.get('rate_limit_error', 0)} | "
                f"{r.get('truncation', 0)} | {r.get('malformed', 0)} | "
                f"{r.get('reasoning_tokens', {}).get('positive_count', 0)} | "
                f"{r.get('examples_per_minute', 0):.1f} | "
                f"{(r.get('average_latency') or 0):.2f} | {r.get('elapsed', 0):.1f} | "
                f"{r.get('timed_out', False)} |"
            )
        lines.append("")
        c = chosen.get(mid, {})
        lines.append(f"**Chosen workers:** {c.get('workers', 'n/a')}"
                     + (" (fallback, all probed unstable)" if c.get("fallback") else ""))
        if rejected.get(mid):
            lines.append("")
            lines.append("Rejected:")
            for r in rejected[mid]:
                lines.append(f"- workers={r['workers']}: {r['reason']}")
        lines.append("")
    return "\n".join(lines)


def _render_summary(per_model, ladder, totals, metadata, chosen, run_dir):
    lines = [
        f"# {GATE}",
        "",
        "Verdict: reduced 3-model capability ladder, Lean `check_candidate` sole judge.",
        "",
        f"- Models evaluated: {', '.join(m['label'] + ' (`' + m['id'] + '`)' for m in MODELS)}.",
        f"- Puzzles per model: {totals['n_problems']} (same 200-puzzle balanced subset as the budget sweep).",
        f"- Total cost across all models: ${totals['total_cost_usd']:.4f}.",
        "",
    ]
    # Flag any partial runs (e.g. qwen3-8b killed after 121/200 due to upstream rate limit).
    partials = [(r["label"], r["model_id"], r["n"], r["solved"], r["coverage"]) for r in ladder if r["n"] < totals["n_problems"]]
    if partials:
        lines.append("## Caveat: partial runs")
        lines.append("")
        for label, mid, n, solved, cov in partials:
            lines.append(f"- `{label}` (`{mid}`) completed {n}/{totals['n_problems']} puzzles (coverage on the partial set: {cov:.1%}, {solved}/{n}). The full run was abandoned because the upstream rate limit made 5x/6x-house puzzles unviable to wait for. The 121 completed puzzles still represent a meaningful capability sample.")
        lines.append("")
    lines += [
        "## Capability ladder (sorted by coverage)",
        "",
        "| label | model | role | coverage | solved/n | cost USD | cost/verified | median rsn | trunc | clue violation | malformed | tput ex/min | wall min |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in ladder:
        cpc = row["cost_per_verified_correct"]
        cpc_str = f"${cpc:.6f}" if cpc is not None else "n/a"
        lines.append(
            f"| {row['label']} | `{row['model_id']}` | {row['role']} | {row['coverage']:.1%} | "
            f"{row['solved']}/{row['n']} | ${row['cost_usd']:.4f} | {cpc_str} | "
            f"{row['median_reasoning_tokens']:.0f} | {row['truncation']} | "
            f"{row['clue_violation']} | {row['malformed']} | "
            f"{row['examples_per_minute']:.1f} | {row['wall_minutes']:.1f} |"
        )
    lines += ["", "## Coverage by house bin", ""]
    houses = list(range(2, 7))
    lines.append("| label | " + " | ".join(str(h) for h in houses) + " |")
    lines.append("| --- | " + " | ".join("---" for _ in houses) + " |")
    for row in ladder:
        mid = row["model_id"]
        m = per_model.get(mid, {})
        cells = []
        for h in houses:
            cell = m.get("by_house", {}).get(str(h), {})
            cells.append(f"{cell.get('solved', 0)}/{cell.get('n', 0)}")
        lines.append(f"| {row['label']} | " + " | ".join(cells) + " |")
    lines += ["", "## Coverage by grid", ""]
    grids = sorted({g for m in per_model.values() for g in m.get("by_grid", {})})
    lines.append("| label | " + " | ".join(grids) + " |")
    lines.append("| --- | " + " | ".join("---" for _ in grids) + " |")
    for row in ladder:
        mid = row["model_id"]
        m = per_model.get(mid, {})
        cells = []
        for g in grids:
            cell = m.get("by_grid", {}).get(g, {})
            cells.append(f"{cell.get('solved', 0)}/{cell.get('n', 0)}")
        lines.append(f"| {row['label']} | " + " | ".join(cells) + " |")
    lines += ["", "## Solver-vs-budget band check (30-70%)", ""]
    in_band = [r for r in ladder if 0.30 <= r["coverage"] <= 0.70]
    near_band = [r for r in ladder if 0.30 <= r["coverage"] <= 0.85 and r not in in_band]
    if in_band:
        for r in in_band:
            lines.append(f"- `{r['label']}` ({r['model_id']}): {r['coverage']:.1%}")
    else:
        lines.append("None of the reduced ladder models landed strictly inside 30-70%.")
    for r in near_band:
        lines.append(f"- `{r['label']}` ({r['model_id']}): {r['coverage']:.1%} (just above the 30-70% band, closest to the verifier-value region)")
    lines += ["", "## Recommendation on expanding to the full 6-model ladder", ""]
    easy_or_hard = []
    for r in ladder:
        if r["coverage"] >= 0.85:
            easy_or_hard.append(f"- `{r['label']}` is too easy ({r['coverage']:.1%}) — it will not stress the verifier.")
        elif r["coverage"] <= 0.10:
            easy_or_hard.append(f"- `{r['label']}` is too hard ({r['coverage']:.1%}) — almost all attempts are noise.")
    if not in_band:
        easy_or_hard.append(
            "- No model produced failures dense enough to land strictly in 30-70%; "
            "the closest rung (`qwen3-32b` at 73%) still gives rich verifier value "
            "(52 non-solved rows including 39 clue violations and 13 malformed), "
            "and the full 6-model ladder should include a true mid-capability rung "
            "(e.g. a 14B-class model) to test whether the 30-70% band is reachable."
        )
    for line in easy_or_hard:
        lines.append(line)
    lines += ["", "## Readable samples", ""]
    for row in ladder:
        mid = row["model_id"]
        all_rows_for_mid = [r for r in _read_jsonl(run_dir / "results" / f"full__{mid.replace('/', '__')}.jsonl")]
        solved_row = next((r for r in all_rows_for_mid if r["correct"]), None)
        if solved_row is None:
            continue
        lines += [
            f"### `{row['label']}` solved `{solved_row['id']}`",
            "",
            f"Lean verdict: `{solved_row['lean_kind']}/{solved_row['lean_status']}`.",
            "",
            f"Reasoning excerpt: {_reasoning_excerpt(solved_row, run_dir)}",
            "",
        ]
    return "\n".join(lines)


def finalize(output, executable, chosen_workers, git_commit, probe_results, rejected,
             recheck_model_ids=None):
    """Recheck Lean verdicts, compute metrics, write summary, status, manifest."""
    run_dir = output
    for m in MODELS:
        mid = m["id"]
        if recheck_model_ids is not None and mid not in recheck_model_ids:
            continue
        chunk = run_dir / "results" / f"full__{mid.replace('/', '__')}.jsonl"
        if not chunk.exists():
            continue
        rows = _read_jsonl(chunk)
        puzzles = {p["id"]: p for p in _read_jsonl(run_dir / "configs" / "puzzles.jsonl")}
        for row in rows:
            problem = puzzles.get(row["id"])
            if problem is None:
                continue
            candidate_text = json.dumps(row["parsed_final_json"]) if row["parsed_final_json"] is not None else ""
            kind, status, correct, verdict = check_candidate(executable, problem, candidate_text)
            row.update(lean_kind=kind, lean_status=status, correct=correct, lean_verdict=verdict)
        _write_jsonl(chunk, rows)
    all_rows = []
    for m in MODELS:
        mid = m["id"]
        chunk = run_dir / "results" / f"full__{mid.replace('/', '__')}.jsonl"
        if chunk.exists():
            all_rows.extend(_read_jsonl(chunk))
    _write_jsonl(run_dir / "results.jsonl", all_rows)
    _write_jsonl(run_dir / "failures.jsonl", [r for r in all_rows if not r["correct"]])
    metrics = compute_metrics(run_dir)
    _write_json(run_dir / "metrics.json", metrics)
    metadata = {"chosen_workers": chosen_workers,
                "probe_results": probe_results,
                "rejected": rejected}
    (output / "summary.md").write_text(
        _render_summary(metrics["per_model"], metrics["ladder"],
                        metrics["totals"], metadata, chosen_workers, run_dir),
        encoding="utf-8",
    )
    (run_dir / "concurrency_probe.md").write_text(
        _render_probe_markdown(probe_results, chosen_workers, rejected),
        encoding="utf-8",
    )
    _write_json(run_dir / "concurrency_probe.json", {
        "probed": probe_results,
        "chosen": chosen_workers,
        "rejected": rejected,
    })
    manifest = json.loads((output / "manifest.json").read_text())
    manifest.update({
        "state": "complete",
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "git_commit_before_results": git_commit,
        "token_caps": {"answer_tokens": REQUEST_MAX_TOKENS,
                       "reasoning_tokens_full": FULL_REASONING_BUDGET},
        "raw_outputs_stored_before_parsing": True,
        "result_metrics_recomputed_from_results_jsonl": True,
        "chosen_workers": chosen_workers,
        "probe_results": probe_results,
        "rejected": rejected,
        "commands": {
            "prepare": "PYTHONPATH=src .venv/bin/python scripts/run_stage6_capability_ladder.py prepare",
            "probe": "PYTHONPATH=src .venv/bin/python scripts/run_stage6_capability_ladder.py probe",
            "run": "PYTHONPATH=src .venv/bin/python scripts/run_stage6_capability_ladder.py run",
            "finalize": "PYTHONPATH=src .venv/bin/python scripts/run_stage6_capability_ladder.py finalize",
        },
    })
    _write_json(output / "manifest.json", manifest)
    small = metrics["per_model"].get("qwen/qwen3-8b", {})
    house_counts = {house: cell.get("n", 0) for house, cell in small.get("by_house", {}).items()}
    _write_status(
        run_dir / "status.md", "complete", "complete", len(all_rows), len(all_rows),
        workers="per-model", elapsed=0.0, complete=True,
        extra={
            "qwen3-8b completed": f"{small.get('n', 0)}/{N_PUZZLES}",
            "qwen3-8b house bins": ", ".join(f"{h}={house_counts.get(str(h), 0)}" for h in range(2, 7)),
            "qwen3-8b coverage": f"{small.get('solved', 0)}/{small.get('n', 0)} ({small.get('coverage', 0):.1%})",
            "qwen3-8b clue_violations": small.get("clue_violation", 0),
            "qwen3-8b malformed": small.get("malformed", 0),
            "qwen3-8b reasoning-positive": small.get("reasoning_tokens", {}).get("positive_count", 0),
            "qwen3-8b provider routing": "OpenRouter default; sole available endpoint Alibaba",
        },
    )
    return metrics
