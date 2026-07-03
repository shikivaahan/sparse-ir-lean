"""Stage 6 contamination perturbation gate."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import random
import re
import statistics
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from openai import OpenAI

from sparseir_harness.reference_solutions import solve_problem
from sparseir_harness.stage6_h5_cleanup import (
    CHEAP_MODEL,
    CHEAP_TOKEN_CAPS,
    OPENROUTER_ENDPOINT,
    SYSTEM_PROMPT,
    USER_TEMPLATE,
    _compact,
    cheap_working_set,
    extract_candidate,
    load_compiled_problems,
)
from sparseir_harness.stage6_mode0 import check_candidate, compile_problem


GATE = "stage6_contamination"
SEED = 20260701
NATURAL_WORDS = (
    "amber birch cedar dahlia ember fern garnet hazel indigo jasmine kelp lilac maple "
    "nectar olive pebble quartz raven saffron thistle umber violet willow xenia yarrow "
    "zephyr acorn brook coral dune elm frost grove harbor iris juniper lagoon meadow "
    "north orchid pine river stone tulip valley wheat yucca zinc apricot breeze clover "
    "drift echo flint glade honey island jade kite lemon moss nova ocean pearl reed "
    "spruce tide opal plum rose sage thyme wren azure berry copper dawn ivory mint"
).split()
SWAP_DIRECTION = {
    "direct_left": "direct_right",
    "direct_right": "direct_left",
    "left_of": "right_of",
    "right_of": "left_of",
}
PROMPT_TEXT = "[system]\n" + SYSTEM_PROMPT + "\n\n[user]\n" + USER_TEMPLATE + "\n"
CONFIG = {
    "model": CHEAP_MODEL,
    "endpoint": OPENROUTER_ENDPOINT,
    "temperature": 0.1,
    "seed": SEED,
    "workers": 8,
    "reasoning": {"max_tokens": CHEAP_TOKEN_CAPS["reasoning_tokens"], "exclude": False},
    "max_tokens": CHEAP_TOKEN_CAPS["request_max_tokens"],
    "mode": "Mode-0 single-shot",
}


def _json_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def perturb_problem(problem: dict[str, Any], seed: int = SEED) -> tuple[dict[str, Any], dict[str, Any]]:
    """Rename values, reverse houses, and shuffle safe presentation order."""

    rng = random.Random(f"{seed}:{problem['id']}")
    words = NATURAL_WORDS.copy()
    rng.shuffle(words)
    pairs = [(category, value) for category, values in problem["categories"].items() for value in values]
    if len(pairs) > len(words):
        raise ValueError("natural-word pool is too small")
    renamed = {pair: words[index] for index, pair in enumerate(pairs)}

    categories = list(problem["categories"])
    rng.shuffle(categories)
    perturbed_categories: dict[str, list[str]] = {}
    for category in categories:
        values = [renamed[(category, value)] for value in problem["categories"][category]]
        rng.shuffle(values)
        perturbed_categories[category] = values

    houses = int(problem["size"]["houses"])
    clues = copy.deepcopy(problem["clues"])
    for clue in clues:
        clue["type"] = SWAP_DIRECTION.get(clue["type"], clue["type"])
        if "house" in clue:
            clue["house"] = houses + 1 - int(clue["house"])
        for item in (clue, clue.get("a"), clue.get("b")):
            if item and "cat" in item and "val" in item:
                item["val"] = renamed[(item["cat"], item["val"])]
    rng.shuffle(clues)

    perturbed = copy.deepcopy(problem)
    perturbed["id"] = f"{problem['id']}__perturbed_{seed}"
    perturbed["source"]["external_id"] = f"{problem['source']['external_id']}__perturbed_{seed}"
    perturbed["categories"] = perturbed_categories
    perturbed["clues"] = clues
    mapping = {
        "original_id": problem["id"],
        "perturbed_id": perturbed["id"],
        "house_permutation": {str(house): str(houses + 1 - house) for house in range(1, houses + 1)},
        "value_mapping": [
            {"category": category, "original": value, "perturbed": renamed[(category, value)]}
            for category, value in pairs
        ],
    }
    return perturbed, mapping


def remap_candidate_to_original(candidate: Any, mapping: dict[str, Any]) -> dict[str, Any] | None:
    """Undo value renaming but deliberately retain houses to detect original-layout recall."""

    if not isinstance(candidate, dict) or not isinstance(candidate.get("solution"), dict):
        return None
    inverse = {
        (row["category"], row["perturbed"]): row["original"]
        for row in mapping["value_mapping"]
    }
    remapped = copy.deepcopy(candidate)
    remapped["problem_id"] = mapping["original_id"]
    for category, assignments in remapped["solution"].items():
        if isinstance(assignments, dict):
            for house, value in assignments.items():
                assignments[house] = inverse.get((category, value), value)
    return remapped


def extract_final_json(text: str) -> tuple[bool, dict[str, Any] | None, str, bool]:
    closing = list(re.finditer(r"</think>", text, flags=re.IGNORECASE))
    if closing:
        suffix = text[closing[-1].end():]
        parsed, candidate_text = extract_candidate(suffix)
        if parsed:
            candidate = json.loads(candidate_text)
            if isinstance(candidate, dict):
                return True, candidate, candidate_text, False
    parsed, candidate_text = extract_candidate(text)
    stripped = False
    if closing:
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE)
        parsed, candidate_text = extract_candidate(text)
        stripped = True
    if not parsed:
        return False, None, candidate_text, stripped
    try:
        candidate = json.loads(candidate_text)
    except json.JSONDecodeError:
        return False, None, candidate_text, stripped
    return isinstance(candidate, dict), candidate if isinstance(candidate, dict) else None, candidate_text, stripped


class Provider:
    def __init__(self, config: dict[str, Any]) -> None:
        if not os.environ.get("OPENROUTER_API_KEY"):
            raise RuntimeError("OPENROUTER_API_KEY is not set")
        self.config = config
        self._local = threading.local()

    def _client(self) -> OpenAI:
        if not getattr(self._local, "client", None):
            self._local.client = OpenAI(
                api_key=os.environ["OPENROUTER_API_KEY"],
                base_url=self.config["endpoint"],
                max_retries=0,
                timeout=300.0,
            )
        return self._local.client

    def call(self, problem: dict[str, Any]) -> dict[str, Any]:
        response = self._client().chat.completions.create(
            model=self.config["model"],
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": USER_TEMPLATE.format(problem_json=_compact(problem))},
            ],
            temperature=self.config["temperature"],
            seed=self.config["seed"],
            max_tokens=self.config["max_tokens"],
            extra_body={"reasoning": self.config["reasoning"]},
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


def prepare(compiled: Path, output: Path, executable: Path, n: int = 40) -> list[dict[str, Any]]:
    if (output / "configs" / "pairs.jsonl").exists():
        raise FileExistsError(f"refusing to overwrite prepared gate: {output}")
    output.mkdir(parents=True, exist_ok=True)
    (output / "configs").mkdir(exist_ok=True)
    (output / "raw").mkdir(exist_ok=True)
    problems = load_compiled_problems(compiled)
    selected = cheap_working_set(problems, n, SEED)
    baseline = {
        row["id"]: row
        for row in _read_jsonl(output.parent / "stage6_mode0_h5_cleanup" / "results.jsonl")
        if row["arm"] == "cheap_mode0"
    }
    pairs: list[dict[str, Any]] = []
    for problem in selected:
        perturbed, mapping = perturb_problem(problem)
        compile_problem(executable, perturbed)
        outcome = solve_problem(perturbed, timeout_seconds=10.0)
        if outcome.status != "unique" or len(outcome.models) != 1:
            raise RuntimeError(f"perturbation is not clingo-unique: {perturbed['id']}: {outcome.status}")
        pairs.append(
            {
                "original": problem,
                "perturbed": perturbed,
                "mapping": mapping,
                "clingo": {"status": outcome.status, "models": len(outcome.models), "seconds": outcome.elapsed_seconds},
                "baseline": baseline.get(problem["id"]),
            }
        )
    _write_jsonl(output / "configs" / "pairs.jsonl", pairs)
    _write_json(output / "configs" / "config.json", CONFIG)
    (output / "configs" / "prompt_template.txt").write_text(PROMPT_TEXT, encoding="utf-8")
    for name in ("results.jsonl", "failures.jsonl"):
        (output / name).write_text("", encoding="utf-8")
    (output / "status.md").write_text(f"# {GATE}\n\nPrepared {n} clingo-unique perturbations.\n", encoding="utf-8")
    _write_json(output / "manifest.json", {
        "gate": GATE,
        "state": "prepared",
        "n": n,
        "model": CHEAP_MODEL,
        "prompt_hash": hashlib.sha256(PROMPT_TEXT.encode()).hexdigest(),
        "config_hash": _json_hash(CONFIG),
        "selection_seed": SEED,
        "house_bins": dict(sorted(Counter(str(p["perturbed"]["size"]["houses"]) for p in pairs).items())),
        "grid_bins": dict(sorted(Counter(p["perturbed"]["source"]["grid"] for p in pairs).items())),
        "clingo_unique": len(pairs),
        "correctness_judge": "Lean check_candidate only",
    })
    _write_json(output / "metrics.json", {})
    (output / "summary.md").write_text(f"# {GATE}\n\nPrepared; evaluation not yet run.\n", encoding="utf-8")
    return pairs


def evaluate_pair(pair: dict[str, Any], run_dir: Path, executable: Path, provider: Provider) -> dict[str, Any]:
    started = time.monotonic()
    problem = pair["perturbed"]
    raw_path = run_dir / "raw" / f"{problem['id']}.json"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    call: dict[str, Any] | None = None
    errors: list[dict[str, str]] = []
    try:
        call = provider.call(problem)
    except Exception as exc:
        errors.append({"type": type(exc).__name__, "message": str(exc)})
    raw = {"original_id": pair["original"]["id"], "perturbed_id": problem["id"], "provider": call, "errors": errors}
    raw_path.write_text(json.dumps(raw, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    text = call["text"] if call else ""
    parsed, final_json, candidate_text, think_stripped = extract_final_json(text)
    lean_kind, lean_status, correct, lean_result = check_candidate(executable, problem, candidate_text)
    original_candidate = remap_candidate_to_original(final_json, pair["mapping"])
    original_text = json.dumps(original_candidate) if original_candidate is not None else candidate_text
    original_kind, original_status, original_correct, original_result = check_candidate(
        executable, pair["original"], original_text
    )
    finish_reason = call["finish_reason"] if call else None
    provider_error = bool(errors)
    rate_limit_error = any("429" in e["message"] or "rate" in e["type"].lower() for e in errors)
    regurgitation = bool(original_correct and not correct)
    if correct:
        category = "solved"
    elif provider_error:
        category = "rate_limit_error" if rate_limit_error else "provider_error"
    elif finish_reason == "length":
        category = "truncation"
    elif regurgitation:
        category = "regurgitation"
    else:
        category = lean_status
    raw.update({"parsed_final_json": final_json, "lean_verdict": lean_result, "original_remap_lean_verdict": original_result})
    raw_path.write_text(json.dumps(raw, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {
        "id": problem["id"],
        "original_id": pair["original"]["id"],
        "grid": problem["source"]["grid"],
        "houses": problem["size"]["houses"],
        "categories": problem["size"]["categories"],
        "model": CONFIG["model"],
        "provider_model_id": call["provider_model_id"] if call else None,
        "prompt_hash": hashlib.sha256(PROMPT_TEXT.encode()).hexdigest(),
        "config_hash": _json_hash(CONFIG),
        "raw_path": str(raw_path.relative_to(run_dir.parent.parent.parent if run_dir.name == GATE else run_dir.parent.parent.parent.parent)),
        "candidate_parsed": parsed,
        "think_stripped": think_stripped,
        "parsed_final_json": final_json,
        "lean_kind": lean_kind,
        "lean_status": lean_status,
        "lean_verdict": lean_result,
        "correct": correct,
        "original_remap_lean_kind": original_kind,
        "original_remap_lean_status": original_status,
        "original_remap_lean_verdict": original_result,
        "regurgitation": regurgitation,
        "failure_category": category,
        "finish_reason": finish_reason,
        "reasoning_tokens": call["reasoning_tokens"] if call else 0,
        "tokens_in": call["tokens_in"] if call else 0,
        "tokens_out": call["tokens_out"] if call else 0,
        "cost_usd": call["cost_usd"] if call else 0.0,
        "provider_error": provider_error,
        "rate_limit_error": rate_limit_error,
        "baseline_original_correct": bool(pair.get("baseline", {}).get("correct")) if pair.get("baseline") else None,
        "elapsed_seconds": time.monotonic() - started,
    }


def run(output: Path, run_dir: Path, executable: Path, workers: int, limit: int | None = None) -> list[dict[str, Any]]:
    if (run_dir / "results.jsonl").exists() and (run_dir / "results.jsonl").stat().st_size:
        raise FileExistsError(f"refusing to overwrite prior run: {run_dir}")
    run_dir.mkdir(parents=True, exist_ok=True)
    pairs = _read_jsonl(output / "configs" / "pairs.jsonl")[:limit]
    provider = Provider(CONFIG)
    rows: list[dict[str, Any]] = []
    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(evaluate_pair, pair, run_dir, executable, provider): pair for pair in pairs}
        for future in as_completed(futures):
            rows.append(future.result())
            rows.sort(key=lambda row: (row["houses"], row["categories"], row["id"]))
            _write_jsonl(run_dir / "results.jsonl", rows)
            _write_jsonl(run_dir / "failures.jsonl", [row for row in rows if not row["correct"]])
            _write_status(run_dir / "status.md", rows, len(pairs), workers, time.monotonic() - started)
            print(f"{GATE}: {len(rows)}/{len(pairs)} {future.result()['id']}", flush=True)
    _write_json(run_dir / "run_metadata.json", {
        "workers": workers,
        "wall_seconds": time.monotonic() - started,
        "completed": len(rows),
    })
    return rows


def compute_metrics(rows: list[dict[str, Any]], wall_seconds: float | None = None) -> dict[str, Any]:
    n = len(rows)
    reasoning = [int(row["reasoning_tokens"] or 0) for row in rows]
    finish = Counter(str(row["finish_reason"]) for row in rows)
    outcomes = Counter(row["lean_status"] for row in rows)
    failures = Counter(row["failure_category"] for row in rows if not row["correct"])
    solved = sum(bool(row["correct"]) for row in rows)
    baseline_rows = [row for row in rows if row["baseline_original_correct"] is not None]
    baseline_solved = sum(bool(row["baseline_original_correct"]) for row in baseline_rows)
    elapsed = wall_seconds if wall_seconds is not None else sum(float(row["elapsed_seconds"]) for row in rows)
    return {
        "n": n,
        "perturbed_solved": solved,
        "perturbed_solve_rate": solved / n if n else 0.0,
        "original_baseline_n": len(baseline_rows),
        "original_baseline_solved": baseline_solved,
        "original_baseline_solve_rate": baseline_solved / len(baseline_rows) if baseline_rows else None,
        "solve_rate_delta": (solved / n - baseline_solved / len(baseline_rows)) if n and baseline_rows else None,
        "regurgitation_count": sum(bool(row["regurgitation"]) for row in rows),
        "malformed_count": outcomes["malformed"],
        "clue_violation_count": outcomes["clue_violation"],
        "truncation_count": finish["length"],
        "provider_error_count": sum(bool(row["provider_error"]) for row in rows),
        "rate_limit_error_count": sum(bool(row["rate_limit_error"]) for row in rows),
        "failure_categories": dict(sorted(failures.items())),
        "finish_reasons": dict(sorted(finish.items())),
        "lean_outcomes": dict(sorted(outcomes.items())),
        "reasoning_tokens": {
            "positive_count": sum(value > 0 for value in reasoning),
            "positive_rate": sum(value > 0 for value in reasoning) / n if n else 0.0,
            "min": min(reasoning, default=0),
            "median": statistics.median(reasoning) if reasoning else 0,
            "p90": sorted(reasoning)[max(0, int(0.9 * len(reasoning)) - 1)] if reasoning else 0,
            "max": max(reasoning, default=0),
        },
        "tokens": {"input": sum(row["tokens_in"] for row in rows), "output_including_reasoning": sum(row["tokens_out"] for row in rows)},
        "cost_usd": sum(float(row["cost_usd"]) for row in rows),
        "wall_seconds": elapsed,
        "examples_per_minute": n / elapsed * 60 if elapsed else 0.0,
        "by_grid": _group_metrics(rows, "grid"),
        "by_house": _group_metrics(rows, "houses"),
    }


def finalize(output: Path, executable: Path, git_commit: str) -> dict[str, Any]:
    rows = _read_jsonl(output / "results.jsonl")
    if len(rows) != 40:
        raise RuntimeError(f"expected 40 full-run rows, found {len(rows)}")
    # Recheck every stored parsed candidate with Lean before deriving metrics.
    pairs = {pair["perturbed"]["id"]: pair for pair in _read_jsonl(output / "configs" / "pairs.jsonl")}
    for row in rows:
        candidate_text = json.dumps(row["parsed_final_json"]) if row["parsed_final_json"] is not None else ""
        kind, status, correct, verdict = check_candidate(executable, pairs[row["id"]]["perturbed"], candidate_text)
        row.update(lean_kind=kind, lean_status=status, correct=correct, lean_verdict=verdict)
    _write_jsonl(output / "results.jsonl", rows)
    _write_jsonl(output / "failures.jsonl", [row for row in rows if not row["correct"]])
    run_metadata = json.loads((output / "run_metadata.json").read_text())
    metrics = compute_metrics(rows, float(run_metadata["wall_seconds"]))
    baseline = metrics["original_baseline_solve_rate"]
    close = baseline is not None and metrics["perturbed_solve_rate"] >= baseline - 0.10
    passed = close and metrics["regurgitation_count"] == 0
    metrics["verdict"] = "passed" if passed else "failed_or_unclear"
    metrics["verdict_rule"] = "pass iff perturbed solve rate is within 0.10 of paired original baseline and regurgitation count is zero"
    _write_json(output / "metrics.json", metrics)
    manifest = json.loads((output / "manifest.json").read_text())
    manifest.update({
        "state": "complete",
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "git_commit_before_results": git_commit,
        "workers": CONFIG["workers"],
        "reasoning_config": CONFIG["reasoning"],
        "token_caps": {"answer_tokens": CHEAP_TOKEN_CAPS["answer_tokens"], "reasoning_tokens": CHEAP_TOKEN_CAPS["reasoning_tokens"], "request_max_tokens": CHEAP_TOKEN_CAPS["request_max_tokens"]},
        "raw_outputs_stored_before_parsing": True,
        "result_metrics_recomputed_from_results_jsonl": True,
        "verdict": metrics["verdict"],
        "commands": {
            "prepare": "PYTHONPATH=src .venv/bin/python scripts/run_stage6_contamination.py prepare --n 40",
            "smoke": "PYTHONPATH=src .venv/bin/python scripts/run_stage6_contamination.py smoke --n 10 --workers 8",
            "full": "PYTHONPATH=src .venv/bin/python scripts/run_stage6_contamination.py run --workers 8",
            "finalize": "PYTHONPATH=src .venv/bin/python scripts/run_stage6_contamination.py finalize",
        },
    })
    _write_json(output / "manifest.json", manifest)
    (output / "summary.md").write_text(_render_summary(rows, metrics), encoding="utf-8")
    _write_status(output / "status.md", rows, len(rows), CONFIG["workers"], metrics["wall_seconds"], complete=True)
    return metrics


def smoke_health(run_dir: Path) -> tuple[bool, dict[str, Any]]:
    rows = _read_jsonl(run_dir / "results.jsonl")
    metrics = compute_metrics(rows)
    healthy = (
        len(rows) >= 5
        and metrics["reasoning_tokens"]["positive_rate"] >= 0.9
        and metrics["truncation_count"] <= max(1, len(rows) // 5)
        and sum(row["candidate_parsed"] for row in rows) >= int(0.8 * len(rows))
        and all(row["lean_kind"] for row in rows)
    )
    metrics["smoke_passed"] = healthy
    _write_json(run_dir / "metrics.json", metrics)
    return healthy, metrics


def _group_metrics(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
    result = {}
    for value in sorted({str(row[key]) for row in rows}):
        group = [row for row in rows if str(row[key]) == value]
        result[value] = {"n": len(group), "solved": sum(bool(row["correct"]) for row in group), "malformed": sum(row["lean_status"] == "malformed" for row in group), "clue_violation": sum(row["lean_status"] == "clue_violation" for row in group)}
    return result


def _reasoning_excerpt(row: dict[str, Any]) -> str:
    path = Path(row["raw_path"])
    if not path.is_absolute():
        path = Path.cwd() / path
    try:
        raw = json.loads(path.read_text())
        message = raw["provider"]["response"]["choices"][0]["message"]
        reasoning = message.get("reasoning") or message.get("reasoning_content") or ""
        return re.sub(r"\s+", " ", reasoning).strip()[:500]
    except Exception:
        return "(reasoning content unavailable; token metadata is retained)"


def _render_summary(rows: list[dict[str, Any]], metrics: dict[str, Any]) -> str:
    solved = next((row for row in rows if row["correct"]), None)
    failed = next((row for row in rows if not row["correct"] and not row["regurgitation"]), None)
    regurgitated = next((row for row in rows if row["regurgitation"]), None)
    lines = [
        "# Stage 6 contamination perturbation smoke",
        "",
        f"Verdict: **{metrics['verdict']}**. This perturbation smoke " + ("did not find evidence of contamination; it does not establish absence of contamination." if metrics["verdict"] == "passed" else "found a collapse or regurgitation signal, so later experiments should not proceed yet."),
        "",
        f"- Perturbed solve rate: {metrics['perturbed_solved']}/{metrics['n']} ({metrics['perturbed_solve_rate']:.1%}).",
        f"- Paired original baseline: {metrics['original_baseline_solved']}/{metrics['original_baseline_n']} ({metrics['original_baseline_solve_rate']:.1%}).",
        f"- Regurgitations: {metrics['regurgitation_count']}; malformed: {metrics['malformed_count']}; clue violations: {metrics['clue_violation_count']}; truncations: {metrics['truncation_count']}.",
        f"- Reasoning present: {metrics['reasoning_tokens']['positive_count']}/{metrics['n']}; median {metrics['reasoning_tokens']['median']:.0f} tokens; finish reasons {metrics['finish_reasons']}.",
        f"- Provider/rate-limit errors: {metrics['provider_error_count']}/{metrics['rate_limit_error_count']}; cost ${metrics['cost_usd']:.6f}; {metrics['examples_per_minute']:.2f} examples/min.",
        "",
        "Lean `check_candidate` is the sole correctness judge. Malformed outputs are not counted as clue violations.",
        "",
        "## Readable samples",
        "",
    ]
    for label, row in (("Solved perturbed", solved), ("Failed/clue-violating", failed), ("Regurgitation", regurgitated)):
        if row is None:
            lines += [f"### {label}", "", "None observed.", ""]
        else:
            lines += [f"### {label}: `{row['id']}`", "", f"Outcome: `{row['failure_category']}`; Lean `{row['lean_kind']}/{row['lean_status']}`.", "", f"Reasoning excerpt: {_reasoning_excerpt(row)}", ""]
    return "\n".join(lines)


def _write_status(path: Path, rows: list[dict[str, Any]], total: int, workers: int, elapsed: float, complete: bool = False) -> None:
    n = len(rows)
    rate = n / elapsed * 60 if elapsed else 0.0
    eta = (total - n) / rate if rate else None
    malformed = sum(row["lean_status"] == "malformed" for row in rows)
    clue = sum(row["lean_status"] == "clue_violation" for row in rows)
    provider = sum(bool(row["provider_error"]) for row in rows)
    trunc = sum(row["finish_reason"] == "length" for row in rows)
    reasoning = [row["reasoning_tokens"] for row in rows]
    text = f"""# {GATE} status

- state: {'complete' if complete else 'running'}
- model/budget: `{CHEAP_MODEL}`, reasoning {CHEAP_TOKEN_CAPS['reasoning_tokens']}, request max {CHEAP_TOKEN_CAPS['request_max_tokens']}
- completed: {n}/{total}
- examples/min: {rate:.2f}
- elapsed: {elapsed / 60:.1f} min
- ETA: {eta:.1f} min
- workers: {workers}
- malformed: {malformed}
- clue violations: {clue}
- provider/rate-limit errors: {provider}/{sum(bool(row['rate_limit_error']) for row in rows)}
- truncation/finish_reason issues: {trunc}; {dict(Counter(str(row['finish_reason']) for row in rows))}
- reasoning_tokens health: {sum(value > 0 for value in reasoning)}/{n} positive; median {statistics.median(reasoning) if reasoning else 0:.0f}
- cost estimate: ${sum(float(row['cost_usd']) for row in rows):.6f}
"""
    path.write_text(text, encoding="utf-8")


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
