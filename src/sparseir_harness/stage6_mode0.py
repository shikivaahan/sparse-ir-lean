"""Stage 6 Mode-0 H2/H3 evaluation with Lean-only correctness verdicts.

This module is intentionally a thin standalone harness. Provider calls and JSON
parsing are untrusted orchestration; ``check_candidate`` is the only operation
that decides whether a generated grid is correct.
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import re
import subprocess
import threading
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Callable

from openai import OpenAI


PROTOCOL_VERSION = "0.1.0"
CONFIDENCE_SOURCE = "p_true"
DEFAULT_MODEL = "deepseek/deepseek-v4-flash"
TAUS = [round(index / 20, 2) for index in range(21)]
RESULT_KEYS = {
    "id",
    "grid_size",
    "houses",
    "categories",
    "candidate_parsed",
    "lean_kind",
    "lean_status",
    "correct",
    "confidence",
    "confidence_source",
    "tokens_in",
    "tokens_out",
    "raw_path",
}

SYSTEM_PROMPT = """Solve the Zebra logic-grid puzzle. Return ONLY one JSON object matching this shape:
{"schema_version":"0.2","problem_id":"<exact id>","solution":{"<Category>":{"1":"<value>","2":"<value>"}}}
Include every category and every house. House keys are one-based decimal strings. Each declared value must occur exactly once in its category. Do not include reasoning, confidence, Markdown, or extra keys.

Clue meanings:
- found_at/not_at: the item is at/is not at the numbered house.
- same_house: the two items share a house.
- direct_left/direct_right: the first item is immediately left/right of the second.
- left_of/right_of: the first item is somewhere left/right of the second.
- side_by_side: the items are in adjacent houses.
- one_between/two_between: exactly one/two houses lie between the items."""

CONFIDENCE_PROMPT = "Is your answer correct? Reply with just a probability from 0 to 1."


@dataclass(frozen=True)
class ProviderResult:
    text: str
    response: dict[str, Any]
    tokens_in: int
    tokens_out: int
    cost_usd: float | None


def _json_dump(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def prompt_template_hash() -> str:
    return hashlib.sha256((SYSTEM_PROMPT + "\n" + CONFIDENCE_PROMPT).encode()).hexdigest()


def problem_for_prompt(problem: dict[str, Any]) -> dict[str, Any]:
    """Return the oracle certificate without the forbidden gold/expect field."""

    return {
        key: value
        for key, value in problem.items()
        if key in {"schema_version", "domain", "id", "size", "categories", "clues"}
    }


def problem_for_verifier(problem: dict[str, Any]) -> dict[str, Any]:
    """Keep the oracle certificate but never pass its opaque gold field to Lean."""

    return {key: value for key, value in problem.items() if key != "expect"}


def generation_messages(problem: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": _json_dump(problem_for_prompt(problem))},
    ]


def confidence_messages(
    problem: dict[str, Any], generated_text: str
) -> list[dict[str, str]]:
    return generation_messages(problem) + [
        {"role": "assistant", "content": generated_text},
        {"role": "user", "content": CONFIDENCE_PROMPT},
    ]


def load_sampled_problems(problem_dir: Path, n: int, seed: int) -> list[dict[str, Any]]:
    """Deterministically interleave every houses-by-categories stratum."""

    groups: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
    for path in sorted(problem_dir.glob("*.problem.json")):
        problem = json.loads(path.read_text(encoding="utf-8"))
        size = problem["size"]
        groups[(int(size["houses"]), int(size["categories"]))].append(problem)
    if not groups:
        raise RuntimeError(f"no problem.json certificates found under {problem_dir}")

    # Latin-square ordering makes a 10-sample prefix span every house and category count twice.
    houses = sorted({key[0] for key in groups})
    categories = sorted({key[1] for key in groups})
    keys = [
        (house, categories[(house_index + offset) % len(categories)])
        for offset in range(len(categories))
        for house_index, house in enumerate(houses)
        if (house, categories[(house_index + offset) % len(categories)]) in groups
    ]
    keys.extend(key for key in sorted(groups) if key not in keys)
    for offset, key in enumerate(keys):
        random.Random(seed + offset).shuffle(groups[key])
    ordered: list[dict[str, Any]] = []
    for index in range(max(len(group) for group in groups.values())):
        for key in keys:
            if index < len(groups[key]):
                ordered.append(groups[key][index])
    if n > len(ordered):
        raise ValueError(f"requested {n} samples but only {len(ordered)} are available")
    return ordered[:n]


def _run_lean(
    executable: Path, command: str, payload: dict[str, Any], request_id: str
) -> dict[str, Any]:
    completed = subprocess.run(
        [str(executable)],
        input=json.dumps(
            {
                "protocol_version": PROTOCOL_VERSION,
                "request_id": request_id,
                "command": command,
                "payload": payload,
            }
        ),
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"Lean verifier exited with {completed.returncode}: {completed.stderr.strip()}"
        )
    response = json.loads(completed.stdout)
    if "result" not in response:
        raise RuntimeError(f"Lean verifier protocol error: {response}")
    return response["result"]


def compile_problem(executable: Path, problem: dict[str, Any]) -> None:
    result = _run_lean(
        executable,
        "compile",
        {"problem": json.dumps(problem_for_verifier(problem))},
        f"stage6-compile-{problem['id']}",
    )
    if result.get("kind") != "COMPILED":
        raise RuntimeError(f"oracle certificate failed Lean compile: {problem['id']}: {result}")


def parse_candidate(raw: str) -> tuple[bool, str]:
    """Extract one JSON object without making any correctness decision."""

    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        if start < 0:
            return False, raw
        try:
            value, _ = json.JSONDecoder().raw_decode(text[start:])
        except json.JSONDecodeError:
            return False, raw
    if not isinstance(value, dict):
        return False, raw
    return True, json.dumps(value, ensure_ascii=False)


def parse_confidence(raw: str) -> float | None:
    match = re.fullmatch(r"\s*(?:0(?:\.\d+)?|1(?:\.0+)?)\s*", raw)
    if not match:
        return None
    value = float(match.group(0))
    return value if 0.0 <= value <= 1.0 else None


def normalize_lean_result(result: dict[str, Any]) -> tuple[str, str, bool]:
    """Map wire details to the committed schema; solved still comes only from Lean."""

    kind = result.get("kind")
    if kind == "ACCEPT_SOLVED":
        return "ACCEPT_SOLVED", "solved", True
    if kind == "INCOMPLETE":
        return "INCOMPLETE", "incomplete", False
    if kind == "REJECT":
        status = str(result.get("failure", {}).get("status", "invalid_candidate"))
        if status == "malformed_candidate":
            return "MALFORMED", "malformed", False
        if status == "clue_violation":
            return "REJECT", "clue_violation", False
        return "REJECT", "invalid", False
    return "MALFORMED", "malformed", False


def check_candidate(
    executable: Path, problem: dict[str, Any], candidate_text: str
) -> tuple[str, str, bool, dict[str, Any]]:
    result = _run_lean(
        executable,
        "check_candidate",
        {"problem": json.dumps(problem_for_verifier(problem)), "candidate": candidate_text},
        f"stage6-check-{problem['id']}",
    )
    lean_kind, lean_status, correct = normalize_lean_result(result)
    return lean_kind, lean_status, correct, result


def _usage(response: Any) -> tuple[int, int, float | None]:
    usage = response.usage
    data = usage.model_dump() if usage else {}
    extra = getattr(usage, "model_extra", None) or {}
    cost = data.get("cost", extra.get("cost"))
    return (
        int(data.get("prompt_tokens") or 0),
        int(data.get("completion_tokens") or 0),
        float(cost) if cost is not None else None,
    )


class OpenRouterProvider:
    def __init__(self, model: str, seed: int, max_tokens: int = 1800) -> None:
        api_key = os.environ.get("OPENROUTER_API_KEY")
        if not api_key:
            raise RuntimeError("OPENROUTER_API_KEY is not set")
        self.model = model
        self.seed = seed
        self.max_tokens = max_tokens
        self._local = threading.local()

    def _client(self) -> OpenAI:
        client = getattr(self._local, "client", None)
        if client is None:
            client = OpenAI(
                api_key=os.environ["OPENROUTER_API_KEY"],
                base_url="https://openrouter.ai/api/v1",
                timeout=120.0,
                max_retries=2,
            )
            self._local.client = client
        return client

    def call(self, messages: list[dict[str, str]], confidence: bool = False) -> ProviderResult:
        response = self._client().chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=0.1 if not confidence else 0,
            max_tokens=16 if confidence else self.max_tokens,
            seed=self.seed,
            extra_body={"reasoning": {"effort": "none"}} if confidence else None,
        )
        text = response.choices[0].message.content or ""
        tokens_in, tokens_out, cost = _usage(response)
        return ProviderResult(
            text=text,
            response=response.model_dump(mode="json"),
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=cost,
        )


ProviderCall = Callable[[list[dict[str, str]], bool], ProviderResult]


def _raw_label(output: Path, problem_id: str) -> str:
    path = output / "raw" / f"{problem_id}.json"
    try:
        return path.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def evaluate_one(
    problem: dict[str, Any],
    output: Path,
    executable: Path,
    provider_call: ProviderCall,
) -> tuple[dict[str, Any], float]:
    generation: ProviderResult | None = None
    confidence_result: ProviderResult | None = None
    errors: list[dict[str, str]] = []
    try:
        generation = provider_call(generation_messages(problem), False)
    except Exception as exc:  # retained and scored fail-closed
        errors.append({"call": "generation", "type": type(exc).__name__, "message": str(exc)})
    if generation is not None:
        try:
            confidence_result = provider_call(
                confidence_messages(problem, generation.text), True
            )
        except Exception as exc:  # retained; missing confidence means PTRUE abstains
            errors.append({"call": "confidence", "type": type(exc).__name__, "message": str(exc)})

    raw_path = output / "raw" / f"{problem['id']}.json"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_record = {
        "id": problem["id"],
        "generation": None
        if generation is None
        else {"text": generation.text, "response": generation.response},
        "confidence": None
        if confidence_result is None
        else {"text": confidence_result.text, "response": confidence_result.response},
        "errors": errors,
    }
    # Both full provider responses are on disk before candidate/confidence parsing.
    raw_path.write_text(json.dumps(raw_record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    generated_text = generation.text if generation is not None else ""
    candidate_parsed, candidate_text = parse_candidate(generated_text)
    lean_kind, lean_status, correct, lean_result = check_candidate(
        executable, problem, candidate_text
    )
    raw_record["lean_result"] = lean_result
    raw_path.write_text(json.dumps(raw_record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    confidence = (
        parse_confidence(confidence_result.text) if confidence_result is not None else None
    )
    calls = [call for call in (generation, confidence_result) if call is not None]
    row = {
        "id": problem["id"],
        "grid_size": problem["source"]["grid"],
        "houses": int(problem["size"]["houses"]),
        "categories": int(problem["size"]["categories"]),
        "candidate_parsed": candidate_parsed,
        "lean_kind": lean_kind,
        "lean_status": lean_status,
        "correct": correct,
        "confidence": confidence,
        "confidence_source": CONFIDENCE_SOURCE,
        "tokens_in": sum(call.tokens_in for call in calls),
        "tokens_out": sum(call.tokens_out for call in calls),
        "raw_path": _raw_label(output, problem["id"]),
    }
    assert set(row) == RESULT_KEYS
    return row, sum(call.cost_usd or 0.0 for call in calls)


def _ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def metric_block(rows: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(rows)
    correct = sum(bool(row["correct"]) for row in rows)
    accepted = sum(row["lean_kind"] == "ACCEPT_SOLVED" for row in rows)
    unchecked_wrong = n - correct
    ptrue_curve: list[dict[str, float]] = []
    for tau in TAUS:
        committed = [
            row
            for row in rows
            if row["confidence"] is not None and float(row["confidence"]) >= tau
        ]
        wrong = sum(not row["correct"] for row in committed)
        ptrue_curve.append(
            {
                "tau": tau,
                "coverage": _ratio(len(committed), n),
                "selective_risk": _ratio(wrong, len(committed)),
            }
        )
    mode0_coverage = _ratio(accepted, n)
    comparable = [point for point in ptrue_curve if point["coverage"] >= mode0_coverage]
    if not accepted:
        h3_note = "Mode-0 commits nothing; the H3 point-vs-curve comparison is uninformative."
    elif comparable:
        best = min(comparable, key=lambda point: point["selective_risk"])
        if 0.0 < best["selective_risk"]:
            h3_note = (
                "Lean point is strictly below every swept P(True) point at equal-or-higher "
                f"coverage (best risk={best['selective_risk']:.4f})."
            )
        else:
            h3_note = (
                "Lean point is not strictly below the swept P(True) curve: P(True) also reaches "
                "zero observed risk at equal-or-higher coverage."
            )
    else:
        h3_note = "No swept P(True) point reaches the Lean point's coverage."
    unchecked_rate = _ratio(unchecked_wrong, n)
    return {
        "n": n,
        "unchecked": {
            "coverage": 1.0 if n else 0.0,
            "accuracy": _ratio(correct, n),
            "confident_wrong_rate": unchecked_rate,
        },
        "mode0": {
            "coverage": mode0_coverage,
            "selective_risk": 0.0,
            "catastrophic_rate": 0.0,
            "accuracy_committed": 1.0 if accepted else 0.0,
        },
        "ptrue_curve": ptrue_curve,
        "headline": {
            "H2_confident_wrong_drop": unchecked_rate,
            "H3_lean_point_vs_ptrue_curve_note": h3_note,
        },
    }


def compute_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    overall = metric_block(rows)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["grid_size"])].append(row)
    overall["by_grid"] = {key: metric_block(grouped[key]) for key in sorted(grouped)}
    return overall


def render_summary(metrics: dict[str, Any], manifest: dict[str, Any]) -> str:
    lines = [
        "# Stage 6 Mode-0 H2 + H3",
        "",
        f"**N={manifest['n']}** oracle certificates; model `{manifest['model_id']}` via "
        f"{manifest['provider']}; seed {manifest['seeds']['sampling_and_generation']}.",
        "",
        "One generated candidate and one follow-up P(True) response were reused across all "
        "three scoring arms. Lean `check_candidate` was the sole correctness judge.",
        "",
        "## Overall",
        "",
        f"- H2: unchecked confident-wrong rate {metrics['unchecked']['confident_wrong_rate']:.3f} "
        f"to Mode-0 catastrophic rate {metrics['mode0']['catastrophic_rate']:.3f} "
        f"(drop {metrics['headline']['H2_confident_wrong_drop']:.3f}).",
        f"- H3: Mode-0 point = ({metrics['mode0']['coverage']:.3f} coverage, "
        f"{metrics['mode0']['selective_risk']:.3f} selective risk). "
        f"{metrics['headline']['H3_lean_point_vs_ptrue_curve_note']}",
        f"- Lean accepted {manifest['verdict_counts'].get('ACCEPT_SOLVED', 0)}/{manifest['n']} "
        f"candidates; {manifest['candidate_parse_failures']} outputs had no parseable JSON "
        "candidate.",
        f"- Usage: {manifest['tokens_in']:,} input tokens and {manifest['tokens_out']:,} "
        f"output/reasoning tokens; provider-reported cost ${manifest['total_cost_usd']:.5f}.",
        "",
        "## By grid size",
        "",
        "| Grid | N | H2 unchecked wrong | Mode-0 coverage | Mode-0 risk | H3 note |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for grid, block in metrics["by_grid"].items():
        note = block["headline"]["H3_lean_point_vs_ptrue_curve_note"]
        lines.append(
            f"| {grid} | {block['n']} | {block['unchecked']['confident_wrong_rate']:.3f} | "
            f"{block['mode0']['coverage']:.3f} | {block['mode0']['selective_risk']:.3f} | "
            f"{note} |"
        )
    lines += [
        "",
        "## Caveats",
        "",
        "- Oracle `problem.json` certificates only; no predicted-certificate path was tested.",
        "- Correctness means only that Lean accepted the emitted full grid as solved. Dataset "
        "`expect` fields and reference solutions were absent from prompts and scoring.",
        "- Prompts were rendered from certificates in Python because `Pretty.lean` is a stub.",
        "- Faithfulness and stepwise reasoning were not tested. This is a Mode-0 candidate check, "
        "not a hardened research evaluation.",
        "- Empty committed sets use selective risk 0 and committed accuracy 0 by convention.",
        "",
    ]
    return "\n".join(lines)


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")


def run_evaluation(
    problem_dir: Path,
    output: Path,
    executable: Path,
    *,
    n: int,
    seed: int,
    model: str,
    git_commit: str,
    workers: int = 1,
    provider_call: ProviderCall | None = None,
) -> dict[str, Any]:
    problems = load_sampled_problems(problem_dir, n, seed)
    for problem in problems:
        compile_problem(executable, problem)

    provider = OpenRouterProvider(model, seed) if provider_call is None else None
    call = provider.call if provider is not None else provider_call
    assert call is not None

    existing: dict[str, dict[str, Any]] = {}
    results_path = output / "results.jsonl"
    if results_path.is_file():
        for line in results_path.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            existing[row["id"]] = row
    selected_ids = {problem["id"] for problem in problems}
    existing = {key: row for key, row in existing.items() if key in selected_ids}

    costs_path = output / "costs.json"
    costs: dict[str, float] = {}
    if costs_path.is_file():
        costs = {key: float(value) for key, value in json.loads(costs_path.read_text()).items()}

    pending = [problem for problem in problems if problem["id"] not in existing]
    completed = 0
    if workers <= 1:
        for problem in pending:
            row, cost = evaluate_one(problem, output, executable, call)
            existing[row["id"]] = row
            costs[row["id"]] = cost
            completed += 1
            print(f"evaluated {completed}/{len(pending)}: {row['id']}", flush=True)
            _write_jsonl(results_path, [existing[p["id"]] for p in problems if p["id"] in existing])
            _write_json(costs_path, costs)
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(evaluate_one, problem, output, executable, call): problem
                for problem in pending
            }
            for future in as_completed(futures):
                row, cost = future.result()
                existing[row["id"]] = row
                costs[row["id"]] = cost
                completed += 1
                print(f"evaluated {completed}/{len(pending)}: {row['id']}", flush=True)
                _write_jsonl(
                    results_path,
                    [existing[p["id"]] for p in problems if p["id"] in existing],
                )
                _write_json(costs_path, costs)

    rows = [existing[problem["id"]] for problem in problems]
    # Re-score retained/resumed provider outputs so every committed verdict comes from the
    # current Lean binary and the verifier never receives the dataset's opaque expect field.
    for problem, row in zip(problems, rows, strict=True):
        raw_path = output / "raw" / f"{problem['id']}.json"
        raw_record = json.loads(raw_path.read_text(encoding="utf-8"))
        generation = raw_record.get("generation")
        generated_text = generation.get("text", "") if generation else ""
        candidate_parsed, candidate_text = parse_candidate(generated_text)
        lean_kind, lean_status, correct, lean_result = check_candidate(
            executable, problem, candidate_text
        )
        confidence_record = raw_record.get("confidence")
        confidence = (
            parse_confidence(confidence_record.get("text", ""))
            if confidence_record
            else None
        )
        row.update(
            candidate_parsed=candidate_parsed,
            lean_kind=lean_kind,
            lean_status=lean_status,
            correct=correct,
            confidence=confidence,
        )
        raw_record["lean_result"] = lean_result
        raw_path.write_text(
            json.dumps(raw_record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    _write_jsonl(results_path, rows)
    metrics = compute_metrics(rows)
    breakdown: dict[str, int] = defaultdict(int)
    for row in rows:
        breakdown[row["grid_size"]] += 1
    manifest = {
        "gate": "stage6_mode0_h2_h3",
        "model_id": model,
        "provider": "openrouter",
        "seeds": {"sampling_and_generation": seed},
        "n": n,
        "grid_breakdown": dict(sorted(breakdown.items())),
        "date": date.today().isoformat(),
        "verifier_version": PROTOCOL_VERSION,
        "git_commit": git_commit,
        "confidence_source": CONFIDENCE_SOURCE,
        "prompt_template_hash": prompt_template_hash(),
        "tokens_in": sum(row["tokens_in"] for row in rows),
        "tokens_out": sum(row["tokens_out"] for row in rows),
        "total_cost_usd": sum(costs.get(row["id"], 0.0) for row in rows),
        "candidate_parse_failures": sum(not row["candidate_parsed"] for row in rows),
        "missing_confidence": sum(row["confidence"] is None for row in rows),
        "verdict_counts": {
            kind: sum(row["lean_kind"] == kind for row in rows)
            for kind in ("ACCEPT_SOLVED", "REJECT", "INCOMPLETE", "MALFORMED")
        },
        "raw_outputs_stored_before_parsing": True,
        "oracle_certificates_only": True,
        "expect_excluded_from_prompt_and_verifier": True,
        "correctness_judge": "Lean check_candidate ACCEPT_SOLVED only",
    }
    _write_json(results_path.with_name("metrics.json"), metrics)
    _write_json(results_path.with_name("manifest.json"), manifest)
    results_path.with_name("summary.md").write_text(
        render_summary(metrics, manifest), encoding="utf-8"
    )
    return manifest
