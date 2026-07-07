"""Stage 6 capability-ladder metric aggregation provenance tests.

Regression tests for the wall-time / throughput derivation in
``compute_metrics``. The historical bug was that, when no persisted
``started_at`` / ``ended_at`` timestamps existed on a result row, the
aggregator silently fell back to the filesystem mtime range of the raw
provider output files. After a clone that mtime range is checkout
metadata, not experimental wall time, and the derived "throughput" was
absurd (e.g. >100k examples/minute for a 200-puzzle run).

The contract verified here is:

* If any row in a model's result file carries real ``started_at`` and
  ``ended_at`` epochs, wall time is ``max(ends) - min(starts)`` and
  throughput is ``n / wall_seconds * 60``.
* If no row in the file carries both, ``wall_seconds`` is ``None``,
  ``wall_minutes`` is ``None``, ``examples_per_minute`` is ``None``, and
  ``wall_time_status`` records the reason.
* Mutating filesystem mtimes of any raw output file has NO effect on
  computed experiment metrics. The only time signal is the persisted
  per-puzzle timestamps.
"""

from __future__ import annotations

import os
import time
from copy import deepcopy
from pathlib import Path

import pytest

from sparseir_harness.stage6_capability_ladder import (
    MODELS,
    _model_metrics,
    _write_jsonl,
    compute_metrics,
)


def _row(model_id, problem_id, *,
         started_at=None, ended_at=None, elapsed_seconds=10.0,
         correct=True, lean_status="solved", lean_kind="ACCEPT_SOLVED",
         finish_reason="stop", reasoning_tokens=100,
         tokens_in=100, tokens_out=100, cost_usd=0.001,
         provider_error=False, rate_limit_error=False,
         houses=2, categories=2, grid="2x2"):
    return {
        "id": problem_id,
        "model_id": model_id,
        "grid": grid,
        "houses": houses,
        "categories": categories,
        "candidate_parsed": True,
        "think_stripped": "",
        "parsed_final_json": {},
        "lean_kind": lean_kind,
        "lean_status": lean_status,
        "lean_verdict": {"kind": lean_kind, "status": lean_status},
        "correct": correct,
        "failure_category": "solved" if correct else lean_status,
        "finish_reason": finish_reason,
        "reasoning_tokens": reasoning_tokens,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "cost_usd": cost_usd,
        "provider_error": provider_error,
        "rate_limit_error": rate_limit_error,
        "provider_model_id": model_id,
        "provider_name": None,
        "rate_limit_retries": 0,
        "prompt_hash": "x",
        "config_hash": "x",
        "raw_path": "",
        "elapsed_seconds": elapsed_seconds,
        "started_at": started_at,
        "ended_at": ended_at,
    }


def test_persisted_timestamps_derive_wall_time_and_throughput() -> None:
    rows = [
        _row("qwen/qwen3-8b", f"p{i}",
             started_at=1000.0 + i * 5, ended_at=1010.0 + i * 5,
             correct=(i % 2 == 0))
        for i in range(10)
    ]
    metrics = _model_metrics(rows, "qwen/qwen3-8b",
                             wall_seconds=45.0, wall_time_status="ok")
    assert metrics["wall_seconds"] == 45.0
    assert metrics["wall_minutes"] == pytest.approx(45.0 / 60.0)
    # n=10, wall=45s => throughput = 10/45 * 60 = 13.333... examples/minute
    assert metrics["examples_per_minute"] == pytest.approx(10 / 45 * 60)
    assert metrics["wall_time_status"] == "ok"


def test_missing_persisted_timestamps_yield_null_wall_metrics() -> None:
    rows = [
        _row("qwen/qwen3-8b", f"p{i}", started_at=None, ended_at=None)
        for i in range(10)
    ]
    metrics = _model_metrics(rows, "qwen/qwen3-8b",
                             wall_seconds=None,
                             wall_time_status="unavailable_missing_persisted_timestamps")
    assert metrics["wall_seconds"] is None
    assert metrics["wall_minutes"] is None
    assert metrics["examples_per_minute"] is None
    assert metrics["wall_time_status"] == "unavailable_missing_persisted_timestamps"


def test_compute_metrics_uses_persisted_timestamps_when_available(tmp_path: Path) -> None:
    model = MODELS[0]
    mid = model["id"]
    safe_mid = mid.replace("/", "__")
    # 20 rows with timestamps; min start 1000.0, max end = 1010.0 + 19*10 = 1200.0
    rows = [
        _row(mid, f"p{i}", started_at=1000.0 + i * 10, ended_at=1010.0 + i * 10)
        for i in range(20)
    ]
    result_path = tmp_path / "results" / f"full__{safe_mid}.jsonl"
    result_path.parent.mkdir(parents=True, exist_ok=True)
    _write_jsonl(result_path, rows)
    metrics = compute_metrics(tmp_path)
    m = metrics["per_model"][mid]
    assert m["wall_seconds"] == pytest.approx(200.0)
    assert m["wall_minutes"] == pytest.approx(200.0 / 60.0)
    # 20 / 200 * 60 = 6.0 examples/minute
    assert m["examples_per_minute"] == pytest.approx(6.0)
    assert m["wall_time_status"] == "ok"


def test_compute_metrics_returns_null_wall_when_no_timestamps(tmp_path: Path) -> None:
    model = MODELS[0]
    mid = model["id"]
    safe_mid = mid.replace("/", "__")
    rows = [_row(mid, f"p{i}", started_at=None, ended_at=None) for i in range(20)]
    result_path = tmp_path / "results" / f"full__{safe_mid}.jsonl"
    result_path.parent.mkdir(parents=True, exist_ok=True)
    _write_jsonl(result_path, rows)
    metrics = compute_metrics(tmp_path)
    m = metrics["per_model"][mid]
    assert m["wall_seconds"] is None
    assert m["wall_minutes"] is None
    assert m["examples_per_minute"] is None
    assert m["wall_time_status"] == "unavailable_missing_persisted_timestamps"


def test_filesystem_mtimes_do_not_affect_computed_metrics(tmp_path: Path) -> None:
    """Mutating raw output file mtimes cannot move wall time or throughput.

    This is the regression test for the historical bug where the aggregator
    silently fell back to raw-file mtime range and reported absurd
    throughputs (e.g. >100k examples/minute for a 200-puzzle run).
    """
    model = MODELS[0]
    mid = model["id"]
    safe_mid = mid.replace("/", "__")
    rows = [_row(mid, f"p{i}", started_at=None, ended_at=None) for i in range(20)]
    result_path = tmp_path / "results" / f"full__{safe_mid}.jsonl"
    result_path.parent.mkdir(parents=True, exist_ok=True)
    _write_jsonl(result_path, rows)
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    (raw_dir / f"full__{safe_mid}__p0.json").write_text("{}")
    (raw_dir / f"full__{safe_mid}__p1.json").write_text("{}")

    before = compute_metrics(tmp_path)
    # Mutate raw-file mtimes to year 2000 (extreme) and again to year 2100.
    target_2000 = time.mktime(time.strptime("2000-01-01", "%Y-%m-%d"))
    target_2100 = time.mktime(time.strptime("2100-01-01", "%Y-%m-%d"))
    for p in raw_dir.iterdir():
        os.utime(p, (target_2000, target_2000))
    after_2000 = compute_metrics(tmp_path)
    for p in raw_dir.iterdir():
        os.utime(p, (target_2100, target_2100))
    after_2100 = compute_metrics(tmp_path)

    m = before["per_model"][mid]
    for snapshot in (after_2000["per_model"][mid], after_2100["per_model"][mid]):
        assert snapshot["wall_seconds"] == m["wall_seconds"]
        assert snapshot["wall_minutes"] == m["wall_minutes"]
        assert snapshot["examples_per_minute"] == m["examples_per_minute"]
        assert snapshot["wall_time_status"] == m["wall_time_status"]
        assert snapshot["n"] == m["n"]
        assert snapshot["solved"] == m["solved"]
        assert snapshot["coverage"] == m["coverage"]
        assert snapshot["cost_usd"] == m["cost_usd"]


def test_summary_renders_unavailable_timing_as_na() -> None:
    """The summary renderer must show 'n/a' (not 0.0) when timing is null."""
    from sparseir_harness.stage6_capability_ladder import _render_summary

    per_model = {
        "qwen/qwen3-32b": {
            "model_id": "qwen/qwen3-32b",
            "n": 200, "solved": 146, "coverage": 0.73,
            "confident_wrong": 0, "p_true": None,
            "malformed": 13, "clue_violation": 39,
            "truncation": 0, "provider_error": 0, "rate_limit_error": 0,
            "finish_reasons": {"stop": 200},
            "lean_outcomes": {"solved": 146, "clue_violation": 39, "malformed": 13},
            "reasoning_tokens": {
                "positive_count": 100, "positive_rate": 0.5,
                "min": 0, "median": 3265.0, "p90": 10000, "max": 24000,
            },
            "tokens": {"input": 0, "output_including_reasoning": 0},
            "cost_usd": 0.58830945,
            "cost_per_verified_correct": 0.004030,
            "examples_per_minute": None,
            "wall_seconds": None, "wall_minutes": None,
            "wall_time_status": "unavailable_missing_persisted_timestamps",
            "by_grid": {}, "by_house": {}, "verifier_value": 0.73,
        },
    }
    ladder = [{
        "model_id": "qwen/qwen3-32b",
        "label": "qwen3-32b", "role": "mid_large",
        "coverage": 0.73, "solved": 146, "n": 200,
        "malformed": 13, "clue_violation": 39, "truncation": 0,
        "cost_usd": 0.58830945,
        "cost_per_verified_correct": 0.004030,
        "median_reasoning_tokens": 3265.0,
        "max_reasoning_tokens": 24000,
        "examples_per_minute": None,
        "wall_minutes": None, "wall_seconds": None,
        "wall_time_status": "unavailable_missing_persisted_timestamps",
    }]
    totals = {"models": ["qwen/qwen3-32b"], "n_problems": 200,
              "total_cost_usd": 0.58830945}
    metadata = {"chosen_workers": {}, "probe_results": {}, "rejected": {}}
    md = _render_summary(per_model, ladder, totals, metadata, {}, __import__("pathlib").Path("/tmp"))
    # Per-row table cell for tput ex/min and wall min must read "n/a", not "0.0".
    table_row = next(line for line in md.splitlines()
                     if line.startswith("| qwen3-32b |"))
    assert "n/a | n/a |" in table_row
    assert "0.0 | 0.0 |" not in table_row
    # Provenance note must be present.
    assert "## Provenance: historical wall time" in md
    assert "unavailable_missing_persisted_timestamps" in md


def test_metrics_are_substantively_unchanged_except_timing() -> None:
    """Sanity: every metric except wall/throughput is identical with vs without timestamps."""
    base_kwargs = dict(lean_status="solved", lean_kind="ACCEPT_SOLVED",
                       finish_reason="stop", reasoning_tokens=100,
                       tokens_in=100, tokens_out=100, cost_usd=0.001,
                       provider_error=False, rate_limit_error=False,
                       houses=2, categories=2, grid="2x2")
    rows_with = [
        _row("qwen/qwen3-8b", f"p{i}", started_at=1000.0 + i, ended_at=1002.0 + i,
             correct=(i < 5), **base_kwargs)
        for i in range(10)
    ]
    rows_without = [deepcopy(r) for r in rows_with]
    for r in rows_without:
        r["started_at"] = None
        r["ended_at"] = None
    m_with = _model_metrics(rows_with, "qwen/qwen3-8b",
                            wall_seconds=2.0, wall_time_status="ok")
    m_without = _model_metrics(rows_without, "qwen/qwen3-8b",
                               wall_seconds=None,
                               wall_time_status="unavailable_missing_persisted_timestamps")
    for key in ("n", "solved", "coverage", "malformed", "clue_violation",
                "truncation", "provider_error", "rate_limit_error",
                "cost_usd", "cost_per_verified_correct",
                "finish_reasons", "lean_outcomes", "reasoning_tokens",
                "tokens", "verifier_value"):
        assert m_with[key] == m_without[key], key
    # Only the timing fields differ.
    assert m_with["wall_seconds"] == 2.0
    assert m_without["wall_seconds"] is None
    assert m_with["wall_time_status"] == "ok"
    assert m_without["wall_time_status"] == "unavailable_missing_persisted_timestamps"