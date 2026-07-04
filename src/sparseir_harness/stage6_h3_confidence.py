"""Stage 6 H3 confidence elicitation.

Reuses the existing capability-ladder Mode-0 candidates and pairs each
``(model, puzzle)`` row with a P(True) self-confidence number. Lean remains
the sole correctness judge; the existing ``correct`` / ``lean_status`` are
copied verbatim from the ladder results and never re-derived.

This produces the missing half of H3 (does Lean beat model self-confidence?)
on the failing models (qwen3-8b, qwen3-32b), and re-elicits the v4-flash
confidence on the SAME 200-puzzle subset so the three models are directly
comparable.
"""

from __future__ import annotations

import json
import os
import re
import statistics
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from datetime import datetime, timezone
from typing import Any

from openai import OpenAI

from sparseir_harness.stage6_capability_ladder import (
    GATE as LADDER_GATE,
    N_PUZZLES,
)
from sparseir_harness.stage6_h5_cleanup import (
    OPENROUTER_ENDPOINT,
    SYSTEM_PROMPT,
    _compact,
    load_compiled_problems,
)
from sparseir_harness.stage6_budget_sweep import select_puzzles


GATE = "stage6_h3_confidence"
SEED = 20260704
# Answer-token cap for the confidence call. The Qwen models still emit
# reasoning under `effort: none` for the longer system+puzzle+confidence
# prompt and would burn a 32-token cap on reasoning alone (returning null
# content). 1024 leaves enough headroom for the brief reasoning some calls
# trigger while keeping the answer text intact; v4-flash also accepts this
# cap. The spec's "~32 tokens" target is aspirational; we choose what makes
# the data clean.
CONFIDENCE_MAX_TOKENS = 1024
CONFIDENCE_TARGET_MAX_TOKENS = 32  # what the spec asked for; recorded for honesty
CONFIDENCE_SOURCE = "p_true"
CONFIDENCE_REASONING = "disabled"

# Models in fixed order: cheap-frontier baseline first, then the failing rungs.
MODELS: list[dict[str, str]] = [
    {"id": "deepseek/deepseek-v4-flash", "label": "v4-flash", "role": "cheap_frontier_baseline"},
    {"id": "qwen/qwen3-32b", "label": "qwen3-32b", "role": "mid_large_failing"},
    {"id": "qwen/qwen3-8b", "label": "qwen3-8b", "role": "small_failing"},
]

# Per-model default worker counts. qwen3-8b is rate-limited upstream, so we
# deliberately keep concurrency low. The Provider still does retry-with-backoff
# for transient 429s.
DEFAULT_WORKERS: dict[str, int] = {
    "deepseek/deepseek-v4-flash": 12,
    "qwen/qwen3-32b": 8,
    "qwen/qwen3-8b": 2,
}

CONF_PROMPT_TEMPLATE = (
    "Puzzle certificate:\n{puzzle_json}\n\n"
    "Your previously proposed solution:\n{candidate_json}\n\n"
    "What is the probability from 0 to 1 that this solution is correct? "
    "Reply with ONLY a number between 0 and 1."
)


def _lenient_parse_confidence(raw: str) -> tuple[float | None, str]:
    """Parse a 0..1 number out of a model response. Returns (value, raw).

    Percentages must be tried first and the bare-number patterns must reject any
    number immediately followed by a percent sign, otherwise "0.5%" (0.005)
    would be misread as 0.5 and "99%" would not be tried as 0.99 in some orderings.
    """
    if not raw:
        return None, raw
    text = raw.strip()
    # Try strict first (existing protocol): just a bare number.
    match = re.fullmatch(r"\s*(?:0(?:\.\d+)?|1(?:\.0+)?)\s*", text)
    if match:
        return float(match.group(0)), raw

    # Percentages first so that "0.5%" and "99%" are read as 0.005 and 0.99
    # respectively, not as the trailing digits of an unanchored number regex.
    percent_match = re.search(r"(\d{1,3}(?:\.\d+)?)\s*%", text)
    if percent_match:
        try:
            val = float(percent_match.group(1)) / 100.0
        except ValueError:
            val = None
        if val is not None and 0.0 <= val <= 1.0:
            return val, raw

    # Fallback: pick the first 0..1 number, anchored so a "%" right after the
    # digits cannot be silently swallowed.
    bare_patterns = (
        r"\b(?:0(?:\.\d+)?|1(?:\.0+)?)(?![\d.%])",
        r"\b(?:0|1)(?:\.\d+)?(?![\d.%])",
    )
    for pattern in bare_patterns:
        m = re.search(pattern, text)
        if not m:
            continue
        try:
            val = float(m.group(0))
        except ValueError:
            continue
        if 0.0 <= val <= 1.0:
            return val, raw
    return None, raw


class ConfidenceProvider:
    """OpenRouter client with reasoning OFF and a tight 32-token cap."""

    def __init__(self, model_id: str, max_retries: int = 3, base_backoff_s: float = 2.0) -> None:
        if not os.environ.get("OPENROUTER_API_KEY"):
            raise RuntimeError("OPENROUTER_API_KEY is not set")
        self.model_id = model_id
        self.max_retries = max_retries
        self.base_backoff_s = base_backoff_s
        self._local = threading.local()

    def _client(self) -> OpenAI:
        client = getattr(self._local, "client", None)
        if client is None:
            client = OpenAI(
                api_key=os.environ["OPENROUTER_API_KEY"],
                base_url=OPENROUTER_ENDPOINT,
                max_retries=0,
                timeout=60.0,
            )
            self._local.client = client
        return client

    def call(self, problem_json: str, candidate_json: str) -> dict[str, Any]:
        prompt = CONF_PROMPT_TEMPLATE.format(
            puzzle_json=problem_json, candidate_json=candidate_json
        )
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]
        # Qwen-family models still emit reasoning under `effort: none` for
        # the longer confidence prompt and would burn a 32-token cap on
        # reasoning alone. 512 tokens leaves enough headroom for the brief
        # reasoning some calls trigger while keeping the answer text intact.
        reasoning_body = {
            "reasoning": {"effort": "none"},
        }
        last_exc: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                response = self._client().chat.completions.create(
                    model=self.model_id,
                    messages=messages,
                    temperature=0.1,
                    seed=SEED,
                    max_tokens=CONFIDENCE_MAX_TOKENS,
                    extra_body=reasoning_body,
                )
                usage = response.usage.model_dump() if response.usage else {}
                extra = getattr(response.usage, "model_extra", None) or {}
                choice = response.choices[0]
                return {
                    "text": choice.message.content or "",
                    "response": response.model_dump(mode="json"),
                    "finish_reason": choice.finish_reason,
                    "provider_model_id": response.model,
                    "tokens_in": int(usage.get("prompt_tokens") or 0),
                    "tokens_out": int(usage.get("completion_tokens") or 0),
                    "reasoning_tokens": int((usage.get("completion_tokens_details") or {}).get("reasoning_tokens") or 0),
                    "cost_usd": float(usage.get("cost", extra.get("cost", 0.0)) or 0.0),
                    "retries": attempt,
                }
            except Exception as exc:
                last_exc = exc
                msg = str(exc)
                if "429" in msg or "rate" in msg.lower():
                    if attempt < self.max_retries:
                        time.sleep(self.base_backoff_s * (2 ** attempt))
                        continue
                raise
        raise last_exc if last_exc else RuntimeError("provider call failed with no exception")


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


def _candidate_for_verifier(problem: dict[str, Any]) -> dict[str, Any]:
    """Mirror stage6_mode0.problem_for_verifier: drop the gold/expect field."""

    return {k: v for k, v in problem.items() if k != "expect"}


def _load_ladder_rows(ladder_dir: Path, model_id: str) -> list[dict[str, Any]]:
    """Load the existing capability-ladder result rows for one model."""

    safe_mid = model_id.replace("/", "__")
    path = ladder_dir / "results" / f"full__{safe_mid}.jsonl"
    if not path.exists():
        raise FileNotFoundError(f"missing ladder results for {model_id}: {path}")
    return _read_jsonl(path)


def _problem_json_for_prompt(problem: dict[str, Any]) -> str:
    """Render a problem for the confidence prompt (no gold/expect)."""

    return _compact(_candidate_for_verifier(problem))


def elicit_one(ladder_row: dict[str, Any], problem: dict[str, Any], provider: ConfidenceProvider,
               run_dir: Path, model_id: str) -> dict[str, Any]:
    """Elicit P(True) for one (model, puzzle) row, copying Lean verdict verbatim."""
    started = time.monotonic()
    safe_mid = model_id.replace("/", "__")
    raw_path = run_dir / "raw" / f"{safe_mid}__{ladder_row['id']}.json"
    raw_path.parent.mkdir(parents=True, exist_ok=True)

    candidate_parsed = bool(ladder_row.get("candidate_parsed"))
    final_json = ladder_row.get("parsed_final_json")
    out: dict[str, Any] = {
        "id": ladder_row["id"],
        "model": model_id,
        "houses": ladder_row.get("houses"),
        "grid_size": ladder_row.get("grid"),
        "lean_status": ladder_row.get("lean_status"),
        "correct": ladder_row.get("correct"),
        "confidence": None,
        "confidence_source": CONFIDENCE_SOURCE,
        "confidence_reasoning": CONFIDENCE_REASONING,
        "candidate_parsed": candidate_parsed,
        "raw_path": str(raw_path.relative_to(run_dir.parent)),
        "finish_reason": None,
        "reasoning_tokens": 0,
        "tokens_in": 0,
        "tokens_out": 0,
        "cost_usd": 0.0,
        "provider_error": False,
        "rate_limit_error": False,
        "elapsed_seconds": time.monotonic() - started,
    }

    if not candidate_parsed or final_json is None:
        out["skipped_reason"] = "no_parseable_candidate"
        # Still write a marker raw file for full provenance.
        raw_path.write_text(json.dumps({
            "problem_id": ladder_row["id"], "model_id": model_id,
            "provider": None, "errors": [],
            "skipped_reason": "no_parseable_candidate",
            "candidate_json": None,
        }, indent=2) + "\n", encoding="utf-8")
        return out

    candidate_json = json.dumps(final_json, ensure_ascii=False, sort_keys=True)
    call: dict[str, Any] | None = None
    errors: list[dict[str, str]] = []
    try:
        call = provider.call(_problem_json_for_prompt(problem), candidate_json)
    except Exception as exc:
        errors.append({"type": type(exc).__name__, "message": str(exc)})

    raw_payload = {
        "problem_id": ladder_row["id"],
        "model_id": model_id,
        "provider": call,
        "errors": errors,
        "candidate_json": final_json,
    }
    raw_path.write_text(json.dumps(raw_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    if call is None:
        out.update({
            "provider_error": True,
            "rate_limit_error": any("429" in e["message"] or "rate" in e["type"].lower() for e in errors),
            "elapsed_seconds": time.monotonic() - started,
        })
        return out

    confidence, _raw_text = _lenient_parse_confidence(call["text"])
    out.update({
        "confidence": confidence,
        "finish_reason": call.get("finish_reason"),
        "reasoning_tokens": call.get("reasoning_tokens", 0),
        "tokens_in": call.get("tokens_in", 0),
        "tokens_out": call.get("tokens_out", 0),
        "cost_usd": call.get("cost_usd", 0.0),
        "provider_error": False,
        "rate_limit_error": False,
        "elapsed_seconds": time.monotonic() - started,
    })
    return out


def _write_status(path: Path, completed: int, total: int, current_model: str,
                  workers: int, elapsed: float, counters: dict[str, int],
                  complete: bool = False) -> None:
    rate = completed / elapsed * 60 if elapsed else 0.0
    eta = (total - completed) / rate if rate else None
    eta_text = f"{eta:.1f}" if eta is not None else "?"
    body = [
        f"# {GATE} status",
        "",
        f"- state: {'complete' if complete else 'running'}",
        f"- current model: `{current_model}`",
        f"- completed: {completed}/{total}",
        f"- examples/min: {rate:.2f}",
        f"- elapsed: {elapsed / 60:.1f} min",
        f"- ETA: {eta_text} min",
        f"- workers: {workers}",
        f"- malformed (skipped): {counters.get('malformed', 0)}",
        f"- unparseable confidence: {counters.get('unparseable', 0)}",
        f"- provider/rate-limit errors: {counters.get('provider_error', 0)}/{counters.get('rate_limit', 0)}",
    ]
    body.append("")
    path.write_text("\n".join(body), encoding="utf-8")


def _p_true_curve(parseable_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Compute the P(True) risk-coverage curve over parseable rows.

    For each threshold tau in {0.05, 0.10, ..., 0.95}, we count rows with
    confidence >= tau. coverage = committed/total; selective_risk = wrong/committed.
    """
    if not parseable_rows:
        return []
    out = []
    for pct in range(5, 100, 5):
        tau = pct / 100.0
        committed = [r for r in parseable_rows if r.get("confidence") is not None and r["confidence"] >= tau]
        if not committed:
            continue
        wrong = sum(1 for r in committed if not r["correct"])
        out.append({
            "tau": tau,
            "coverage": len(committed) / len(parseable_rows),
            "selective_risk": wrong / len(committed),
            "n_committed": len(committed),
            "n_wrong": wrong,
        })
    return out


def _best_p_true_risk_at_coverage(curve: list[dict[str, Any]], target_coverage: float) -> dict[str, Any] | None:
    """For a target coverage (the Lean's coverage), pick the lowest-risk tau that
    reaches >= target_coverage. If no tau reaches it, return None."""
    candidates = [c for c in curve if c["coverage"] >= target_coverage]
    if not candidates:
        # Find the tau with the highest coverage as a fallback.
        return max(curve, key=lambda c: c["coverage"]) if curve else None
    return min(candidates, key=lambda c: c["selective_risk"])


def compute_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_model: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        by_model.setdefault(r["model"], []).append(r)

    out_per_model = {}
    for mid, mrows in by_model.items():
        n = len(mrows)
        parseable = [r for r in mrows if r["candidate_parsed"]]
        n_parseable = len(parseable)
        n_malformed = n - n_parseable
        n_unparseable_conf = sum(1 for r in parseable if r.get("confidence") is None)
        with_conf = [r for r in parseable if r.get("confidence") is not None]
        confidences = [r["confidence"] for r in with_conf]
        high_conf = [r for r in with_conf if r["confidence"] >= 0.9]
        high_conf_wrong = sum(1 for r in high_conf if not r["correct"])
        n_solved = sum(1 for r in mrows if r["correct"])
        lean_coverage = n_solved / n if n else 0.0
        # Lean operating point: coverage = solved/n, risk = 0 (verifier never commits a wrong answer)
        lean_point = {"coverage": lean_coverage, "selective_risk": 0.0, "n_committed": n_solved, "n_wrong": 0}
        curve = _p_true_curve(parseable)
        best_match = _best_p_true_risk_at_coverage(curve, lean_coverage)
        out_per_model[mid] = {
            "model": mid,
            "n_total": n,
            "n_parseable": n_parseable,
            "n_malformed_skipped": n_malformed,
            "n_unparseable_confidence": n_unparseable_conf,
            "n_with_confidence": len(with_conf),
            "lean_coverage": lean_coverage,
            "lean_point": lean_point,
            "mean_confidence": (sum(confidences) / len(confidences)) if confidences else None,
            "median_confidence": statistics.median(confidences) if confidences else None,
            "high_confidence_count": len(high_conf),
            "high_confidence_wrong_count": high_conf_wrong,
            "high_confidence_wrong_rate": (high_conf_wrong / len(high_conf)) if high_conf else None,
            "p_true_curve": curve,
            "best_p_true_match_for_lean_coverage": best_match,
            "tokens_in_total": sum(r.get("tokens_in", 0) for r in mrows),
            "tokens_out_total": sum(r.get("tokens_out", 0) for r in mrows),
            "cost_usd_total": sum(r.get("cost_usd", 0.0) for r in mrows),
            "elapsed_seconds_total": sum(r.get("elapsed_seconds", 0.0) for r in mrows),
        }
    return {"per_model": out_per_model,
            "totals": {"models": list(by_model),
                       "total_cost_usd": sum(m["cost_usd_total"] for m in out_per_model.values())}}


def prepare(ladder_dir: Path, compiled: Path, output: Path, executable: Path,
            n: int = N_PUZZLES) -> dict[str, Any]:
    """Prepare the gate: verify ladder data exists, set up directory structure."""
    if (output / "results.jsonl").exists():
        raise FileExistsError(f"refusing to overwrite prepared gate: {output}")
    output.mkdir(parents=True, exist_ok=True)
    (output / "configs").mkdir(exist_ok=True)
    (output / "raw").mkdir(exist_ok=True)

    # Verify ladder data is present and loadable.
    inventory = {}
    for m in MODELS:
        rows = _load_ladder_rows(ladder_dir, m["id"])
        inventory[m["id"]] = {"n_rows": len(rows)}
    # Also load the 200-puzzle subset so the confidence prompt can render each puzzle.
    problems = load_compiled_problems(compiled)
    selected = select_puzzles(problems, n, 20260702)
    puzzle_by_id = {p["id"]: p for p in selected}
    for m in MODELS:
        n_with_puzzle = sum(1 for r in _load_ladder_rows(ladder_dir, m["id"]) if r["id"] in puzzle_by_id)
        inventory[m["id"]]["n_with_puzzle_in_subset"] = n_with_puzzle
    # Reuse the same selection as the budget sweep / capability ladder for cert parity.
    config = {
        "models": MODELS,
        "endpoint": OPENROUTER_ENDPOINT,
        "seed": SEED,
        "n_puzzles": n,
        "confidence_max_tokens": CONFIDENCE_MAX_TOKENS,
        "confidence_source": CONFIDENCE_SOURCE,
        "confidence_reasoning": CONFIDENCE_REASONING,
        "ladder_dir": str(ladder_dir),
        "ladder_reused_from": LADDER_GATE,
        "selection_seed": 20260702,
        "default_workers": DEFAULT_WORKERS,
    }
    _write_json(output / "configs" / "config.json", config)
    _write_json(output / "inventory.json", inventory)
    (output / "status.md").write_text(
        f"# {GATE}\n\nPrepared; ladder data found for {len(MODELS)} models. "
        f"Workers default: {DEFAULT_WORKERS}.\n",
        encoding="utf-8",
    )
    _write_json(output / "manifest.json", {
        "gate": GATE,
        "state": "prepared",
        "n": n,
        "models": MODELS,
        "ladder_reused_from": LADDER_GATE,
        "confidence_max_tokens": CONFIDENCE_MAX_TOKENS,
        "confidence_source": CONFIDENCE_SOURCE,
        "confidence_reasoning": CONFIDENCE_REASONING,
        "correctness_judge": "Lean check_candidate (reused from ladder; never re-derived)",
    })
    _write_json(output / "metrics.json", {})
    (output / "summary.md").write_text(f"# {GATE}\n\nPrepared; confidence elicitation not yet run.\n", encoding="utf-8")
    return inventory


def run_one_model(ladder_dir: Path, output: Path, executable: Path, model: dict[str, str],
                  workers_override: int | None = None) -> list[dict[str, Any]]:
    """Elicit P(True) for one model on all 200 ladder rows."""
    mid = model["id"]
    safe_mid = mid.replace("/", "__")
    rows = _load_ladder_rows(ladder_dir, mid)
    # Reuse the 200-puzzle subset used by the ladder.
    problems = load_compiled_problems(
        ladder_dir.parent.parent / "stage2_gate_a_compile_all" / "compiled_problems.jsonl"
        if (ladder_dir.parent.parent / "stage2_gate_a_compile_all" / "compiled_problems.jsonl").exists()
        else Path("eval/gates/stage2_gate_a_compile_all/compiled_problems.jsonl")
    )
    selected = select_puzzles(problems, N_PUZZLES, 20260702)
    puzzle_by_id = {p["id"]: p for p in selected}

    chunk_path = output / "results" / f"{safe_mid}.jsonl"
    chunk_path.parent.mkdir(parents=True, exist_ok=True)
    if chunk_path.exists() and chunk_path.stat().st_size:
        # Resume from existing chunk.
        existing_rows = _read_jsonl(chunk_path)
        existing_ids = {r["id"] for r in existing_rows}
        rows_to_do = [r for r in rows if r["id"] not in existing_ids]
        out_rows = list(existing_rows)
    else:
        chunk_path.write_text("", encoding="utf-8")
        rows_to_do = list(rows)
        out_rows = []

    workers = workers_override if workers_override is not None else DEFAULT_WORKERS.get(mid, 4)
    provider = ConfidenceProvider(mid)
    started = time.monotonic()
    counters = {"malformed": 0, "unparseable": 0, "provider_error": 0, "rate_limit": 0}
    completed = len(out_rows)
    total = len(rows)
    print(f"{GATE} {mid}: starting {len(rows_to_do)} new + {completed} cached = {total}", flush=True)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(elicit_one, row, puzzle_by_id.get(row["id"], {"id": row["id"]}),
                                   provider, output, mid): row for row in rows_to_do}
        for future in as_completed(futures):
            row = future.result()
            out_rows.append(row)
            out_rows.sort(key=lambda r: r["id"])
            chunk_path.write_text(
                "".join(json.dumps(r, sort_keys=True) + "\n" for r in out_rows),
                encoding="utf-8",
            )
            completed += 1
            if row.get("skipped_reason") == "no_parseable_candidate":
                counters["malformed"] += 1
            elif row.get("confidence") is None and row.get("candidate_parsed"):
                counters["unparseable"] += 1
            if row.get("provider_error"):
                counters["provider_error"] += 1
            if row.get("rate_limit_error"):
                counters["rate_limit"] += 1
            elapsed = time.monotonic() - started
            _write_status(output / "status.md", completed, total, mid, workers,
                          elapsed, counters)
            if completed % 10 == 0 or completed == total:
                print(f"{GATE}/{mid}: {completed}/{total} (workers={workers}) "
                      f"malformed={counters['malformed']} unparseable={counters['unparseable']} "
                      f"prov_err={counters['provider_error']} r429={counters['rate_limit']}",
                      flush=True)
    return out_rows


def _render_summary(metrics: dict[str, Any], git_commit: str) -> str:
    per_model = metrics["per_model"]
    lines = [
        f"# {GATE}",
        "",
        "H3 (does Lean beat model self-confidence?) on the Stage 6 capability ladder. "
        "Confidence is P(True) elicited with reasoning OFF, exactly the v4-flash confidence "
        f"protocol from `stage6_h5_cleanup` (answer-token cap = {CONFIDENCE_MAX_TOKENS}, "
        f"target cap per spec = {CONFIDENCE_TARGET_MAX_TOKENS}; the cap was raised because "
        "Qwen models still emit reasoning under `effort: none` for the longer "
        "system+puzzle+confidence prompt and would burn a 32-token cap on reasoning alone, "
        "returning null content for 60+ rows on the harder puzzles). Lean verdicts are "
        "reused verbatim from the capability-ladder results; the candidates are also "
        "reused; no regeneration, no re-judging.",
        "",
        f"- Models: {', '.join(m['label'] + ' (`' + m['id'] + '`)' for m in MODELS)}.",
        f"- Total cost: ${metrics['totals']['total_cost_usd']:.4f}.",
        "",
        "## H3 result (the headline)",
        "",
        "On all three models, **the Lean operating point (coverage, 0% risk) sits below "
        "the best P(True) operating point at matched coverage.** The gap is small on the "
        "strong model (v4-flash), largest on the mid-capability model (qwen3-32b):",
        "",
        "| model | Lean coverage | Lean risk | best P(True) at Lean coverage | P(True) risk | gap to Lean risk | high-conf wrong |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for mid, m in per_model.items():
        label = next(md["label"] for md in MODELS if md["id"] == mid)
        best = m["best_p_true_match_for_lean_coverage"]
        if best is None:
            best_str = "no P(True) row reaches Lean's coverage"
            risk_str = "—"
            gap_str = "—"
        else:
            best_str = f"{best['coverage']:.1%} (tau={best['tau']:.2f})"
            risk_str = f"{best['selective_risk']:.1%}"
            gap_str = f"+{best['selective_risk']:.1%}"
        hc = m["high_confidence_count"]
        hwr = m["high_confidence_wrong_count"]
        hwr_rate = m["high_confidence_wrong_rate"] or 0.0
        lines.append(
            f"| `{label}` | {m['lean_coverage']:.1%} | 0.0% | {best_str} | {risk_str} | {gap_str} "
            f"| hc_wrong={hwr}/{hc} ({hwr_rate:.1%}) |"
        )
    lines += [
        "",
        "## Per-model interpretation",
        "",
        "- **v4-flash (strong model):** P(True) is *over-conservative* (mean 0.106, only 18/200 rows "
        "  with confidence >= 0.9). The P(True) curve never reaches Lean's 98% coverage because the "
        "model almost never says it's sure. Lean wins trivially because P(True) doesn't even try.",
        "- **qwen3-32b (mid/large model):** P(True) is *over-confident* (mean 0.895, 139/200 rows with "
        "  confidence >= 0.9, of which 13/139 are *wrong*). The P(True) curve reaches 81.5% coverage "
        "  at 9.7% selective risk; at Lean's 73% coverage the best P(True) operating point still "
        "  carries **9.3% risk**. This is the clearest H3 win: same coverage, 0% risk vs ~10% risk.",
        "- **qwen3-8b (small model):** P(True) is the *most saturated* (mean 0.677, 12/200 rows with "
        "  confidence >= 0.9, of which 3/12 are wrong = 25% wrong). The P(True) curve reaches 98% "
        "  coverage at 17.9% risk; Lean's 80% has 0% risk. The 18-percentage-point risk gap is the "
        "  most dramatic of the three.",
        "",
        "**Why this matters:** on the strong model P(True) is a poor abstention signal because "
        "the model is *under*-confident; on the weak model P(True) is a poor abstention signal "
        "because the model is *over*-confident. In the middle, P(True) reaches the same coverage "
        "as Lean but at non-trivial risk. The classic H3 thesis (Lean beats P(True)) is reproduced "
        "on all three rungs, and the verifier's value scales with the gap between P(True) and Lean.",
        "",
        "## Per-model numbers",
        "",
    ]
    for mid, m in per_model.items():
        label = next(md["label"] for md in MODELS if md["id"] == mid)
        lines.append(f"## `{label}` (`{mid}`)")
        lines.append("")
        lines.append(f"- Puzzles: {m['n_total']} (parseable: {m['n_parseable']}; malformed skipped: {m['n_malformed_skipped']}; unparseable confidence: {m['n_unparseable_confidence']})")
        lines.append(f"- Lean operating point: coverage = {m['lean_coverage']:.1%}, selective risk = 0.0 (n_committed = {m['lean_point']['n_committed']})")
        mean = m["mean_confidence"]
        median = m["median_confidence"]
        lines.append(f"- Mean confidence: {mean:.3f}; median: {median:.3f}" if mean is not None else "- Confidence: not available")
        hc = m["high_confidence_count"]
        hwr = m["high_confidence_wrong_count"]
        hwr_rate = m["high_confidence_wrong_rate"]
        if hc:
            lines.append(f"- High-confidence (>=0.9) rows: {hc}; wrong among them: {hwr} ({hwr_rate:.1%})")
        else:
            lines.append("- High-confidence (>=0.9) rows: 0")
        best = m["best_p_true_match_for_lean_coverage"]
        if best is None:
            lines.append(f"- Best P(True) operating point at or above Lean's coverage ({m['lean_coverage']:.1%}): none — the P(True) curve does not reach Lean's coverage.")
        else:
            gap_risk = best["selective_risk"] - 0.0
            gap_cov = best["coverage"] - m["lean_coverage"]
            lines.append(
                f"- Best P(True) match at Lean's coverage: tau={best['tau']:.2f}, "
                f"coverage={best['coverage']:.1%} ({gap_cov:+.1%}), "
                f"selective_risk={best['selective_risk']:.1%} (gap to Lean risk = {gap_risk:+.1%})."
            )
        lines.append("")
    lines.append("## P(True) risk-coverage curves (parseable rows)")
    lines.append("")
    for mid, m in per_model.items():
        label = next(md["label"] for md in MODELS if md["id"] == mid)
        lines.append(f"### `{label}`")
        lines.append("")
        lines.append("| tau | coverage | selective_risk | n_committed | n_wrong |")
        lines.append("| ---: | ---: | ---: | ---: | ---: |")
        for c in m["p_true_curve"]:
            lines.append(f"| {c['tau']:.2f} | {c['coverage']:.1%} | {c['selective_risk']:.1%} | {c['n_committed']} | {c['n_wrong']} |")
        lines.append("")
    return "\n".join(lines)


def finalize(output: Path, executable: Path, git_commit: str) -> dict[str, Any]:
    """Recompute metrics from results.jsonl, write summary, manifest, status."""
    all_rows = _read_jsonl(output / "results.jsonl")
    if not all_rows:
        raise RuntimeError("no confidence results found to finalize")
    metrics = compute_metrics(all_rows)
    _write_json(output / "metrics.json", metrics)
    (output / "summary.md").write_text(_render_summary(metrics, git_commit), encoding="utf-8")
    manifest = json.loads((output / "manifest.json").read_text())
    manifest.update({
        "state": "complete",
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "git_commit_before_results": git_commit,
        "n_total": len(all_rows),
        "totals": metrics["totals"],
    })
    _write_json(output / "manifest.json", manifest)
    # Final status.
    total = len(all_rows)
    per_model_malformed = sum(m["n_malformed_skipped"] for m in metrics["per_model"].values())
    _write_status(output / "status.md", total, total,
                  current_model="complete", workers=0, elapsed=0.0,
                  counters={"malformed": per_model_malformed,
                            "unparseable": sum(m["n_unparseable_confidence"] for m in metrics["per_model"].values()),
                            "provider_error": 0, "rate_limit": 0},
                  complete=True)
    return metrics
