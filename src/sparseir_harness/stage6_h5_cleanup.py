"""Stage 6 Mode-0 cleanup and single-shot frontier evaluation.

Python orchestrates provider calls and artifact writing. Lean ``check_candidate``
is the sole correctness judge. No expected solution is loaded or transmitted.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import random
import re
import subprocess
import threading
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from openai import OpenAI

from sparseir_harness.reference_solutions import solve_problem
from sparseir_harness.stage6_mode0 import check_candidate, compile_problem


PROTOCOL_VERSION = "0.1.0"
OPENROUTER_ENDPOINT = "https://openrouter.ai/api/v1"
CHEAP_MODEL = "deepseek/deepseek-v4-flash"
FRONTIER_MODEL = "anthropic/claude-opus-4.8"
CHEAP_ARM = "cheap_mode0"
FRONTIER_ARM = "frontier_mode0"
SEED = 20260630
OPUS_BUDGET_USD = 5.0
OPUS_PROMPT_PRICE = 0.000005
OPUS_COMPLETION_PRICE = 0.000025
PRIOR_MALFORMED_RATE = 0.24
TAUS = [round(index / 20, 2) for index in range(21)]

CHEAP_TOKEN_CAPS = {
    "answer_tokens": 8192,
    "reasoning_tokens": 24000,
    "request_max_tokens": 32768,
    "confidence_max_tokens": 32,
}
FRONTIER_TOKEN_CAPS = {
    "answer_tokens": 4096,
    "reasoning_tokens": 2048,
    "request_max_tokens": 6144,
}

SYSTEM_PROMPT = """Solve the Zebra logic-grid puzzle. Reason as needed, then output your final answer as a single JSON candidate object.

Your final response must contain a single JSON object with exactly this shape:
{"schema_version":"0.2","problem_id":"<exact id>","solution":{"<Category>":{"1":"<value>","2":"<value>"}}}

Include every declared category and every house. House keys must be one-based canonical decimal strings. Every declared value must appear exactly once in its category. The final JSON object may be the only thing in your final channel, or it may be the last fenced ```json block, or the last top-level {...} object. Reasoning is welcome; do not suppress it.

Clue meanings:
- found_at/not_at: the item is at/is not at the numbered house.
- same_house: the two items share a house.
- direct_left/direct_right: the first item is immediately left/right of the second.
- left_of/right_of: the first item is somewhere left/right of the second.
- side_by_side: the items are in adjacent houses.
- one_between/two_between: exactly one/two houses lie between the items."""

USER_TEMPLATE = "Puzzle certificate:\n{problem_json}"
CONFIDENCE_PROMPT = "Is your answer correct? Reply with just a probability 0-1."
PROMPT_TEMPLATE_TEXT = (
    "[generation system]\n"
    + SYSTEM_PROMPT
    + "\n\n[generation user]\n"
    + USER_TEMPLATE
    + "\n\n[cheap-arm confidence follow-up]\n"
    + CONFIDENCE_PROMPT
    + "\n"
)

RESULT_KEYS = {
    "id",
    "grid_size",
    "houses",
    "categories",
    "model",
    "arm",
    "seed",
    "candidate_parsed",
    "lean_kind",
    "lean_status",
    "correct",
    "confidence",
    "confidence_source",
    "tokens_in",
    "tokens_out",
    "reasoning_tokens",
    "cost_usd",
    "raw_path",
}


@dataclass(frozen=True)
class ProviderResult:
    text: str
    response: dict[str, Any]
    tokens_in: int
    tokens_out: int
    reasoning_tokens: int | None
    cost_usd: float


def _compact(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def prompt_template_hash() -> str:
    return hashlib.sha256(PROMPT_TEMPLATE_TEXT.encode("utf-8")).hexdigest()


def reconstruct_problem(row: dict[str, Any]) -> dict[str, Any]:
    """Reshape one committed Stage-2 compiled record without any gold field."""

    return {
        "schema_version": "0.2",
        "domain": "zebra",
        "id": row["problem_id"],
        "source": {
            "dataset": "zebralogic",
            "split": "test",
            "external_id": row["external_id"],
            "grid": row["grid"],
        },
        "size": {"houses": int(row["houses"]), "categories": int(row["categories"])},
        "categories": {
            category["name"]: list(category["values"])
            for category in row["compiled_categories"]
        },
        "clues": row["compiled_clues"],
    }


def load_compiled_problems(compiled_path: Path) -> list[dict[str, Any]]:
    problems = [
        reconstruct_problem(json.loads(line))
        for line in compiled_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return sorted(problems, key=lambda problem: problem["source"]["external_id"])


def _group_order(problems: list[dict[str, Any]], seed: int) -> list[dict[str, Any]]:
    groups: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
    for problem in problems:
        size = problem["size"]
        groups[(int(size["houses"]), int(size["categories"]))].append(problem)
    houses = sorted({key[0] for key in groups})
    categories = sorted({key[1] for key in groups})
    keys = [
        (house, categories[(house_index + offset) % len(categories)])
        for offset in range(len(categories))
        for house_index, house in enumerate(houses)
        if (house, categories[(house_index + offset) % len(categories)]) in groups
    ]
    for offset, key in enumerate(keys):
        random.Random(seed + offset).shuffle(groups[key])
    ordered: list[dict[str, Any]] = []
    for index in range(max(len(group) for group in groups.values())):
        for key in keys:
            if index < len(groups[key]):
                ordered.append(groups[key][index])
    return ordered


def cheap_working_set(problems: list[dict[str, Any]], n: int, seed: int) -> list[dict[str, Any]]:
    ordered = _group_order(problems, seed)
    if n > len(ordered):
        raise ValueError(f"requested {n} cheap puzzles but only {len(ordered)} are available")
    return ordered[:n]


def _house_candidates(
    problems: list[dict[str, Any]], house: int, seed: int
) -> list[dict[str, Any]]:
    groups: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for problem in problems:
        if int(problem["size"]["houses"]) == house:
            groups[int(problem["size"]["categories"])].append(problem)
    for category, group in groups.items():
        random.Random(seed + house * 100 + category).shuffle(group)
    ordered: list[dict[str, Any]] = []
    categories = sorted(groups)
    for index in range(max(len(group) for group in groups.values())):
        for category in categories:
            if index < len(groups[category]):
                ordered.append(groups[category][index])
    return ordered


def opus_probe_set(problems: list[dict[str, Any]], seed: int) -> list[dict[str, Any]]:
    return [_house_candidates(problems, house, seed)[0] for house in (2, 4, 6)]


def frontier_subset(
    problems: list[dict[str, Any]], n: int, seed: int, probe_ids: set[str]
) -> list[dict[str, Any]]:
    if n % 5:
        raise ValueError("frontier N must be divisible by five for house-bin balance")
    per_house = n // 5
    selected: list[dict[str, Any]] = []
    for house in range(2, 7):
        candidates = _house_candidates(problems, house, seed)
        probes = [problem for problem in candidates if problem["id"] in probe_ids]
        remainder = [problem for problem in candidates if problem["id"] not in probe_ids]
        chosen = (probes + remainder)[:per_house]
        if len(chosen) != per_house:
            raise ValueError(f"not enough puzzles for house bin {house}")
        selected.extend(chosen)
    return selected


def prompt_problem(problem: dict[str, Any]) -> dict[str, Any]:
    if "expect" in problem:
        raise ValueError("expect/gold data must not enter the prompt")
    return problem


def generation_messages(problem: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": USER_TEMPLATE.format(problem_json=_compact(prompt_problem(problem))),
        },
    ]


def confidence_messages(
    problem: dict[str, Any], generated_text: str
) -> list[dict[str, str]]:
    return generation_messages(problem) + [
        {"role": "assistant", "content": generated_text},
        {"role": "user", "content": CONFIDENCE_PROMPT},
    ]


def extract_candidate(raw: str) -> tuple[bool, str]:
    """Take the last valid fenced JSON block or last valid top-level object."""

    fenced = re.findall(r"```(?:json)?\s*(.*?)```", raw, flags=re.IGNORECASE | re.DOTALL)
    for block in reversed(fenced):
        try:
            value = json.loads(block.strip())
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return True, json.dumps(value, ensure_ascii=False)

    decoder = json.JSONDecoder()
    starts: list[int] = []
    depth = 0
    in_string = False
    escaped = False
    for index, character in enumerate(raw):
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue
        if character == '"':
            in_string = True
        elif character == "{":
            if depth == 0:
                starts.append(index)
            depth += 1
        elif character == "}" and depth:
            depth -= 1
    parsed: list[tuple[int, dict[str, Any]]] = []
    for start in starts:
        try:
            value, _ = decoder.raw_decode(raw[start:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            parsed.append((start, value))
    if parsed:
        return True, json.dumps(parsed[-1][1], ensure_ascii=False)
    return False, raw


def parse_confidence(raw: str) -> float | None:
    match = re.fullmatch(r"\s*(?:0(?:\.\d+)?|1(?:\.0+)?)\s*", raw)
    if match is None:
        return None
    value = float(match.group(0))
    return value if 0.0 <= value <= 1.0 else None


def _usage(response: Any) -> tuple[int, int, int | None, float]:
    usage = response.usage
    data = usage.model_dump() if usage else {}
    extra = getattr(usage, "model_extra", None) or {}
    details = data.get("completion_tokens_details") or {}
    reasoning = details.get("reasoning_tokens")
    cost = data.get("cost", extra.get("cost", 0.0))
    return (
        int(data.get("prompt_tokens") or 0),
        int(data.get("completion_tokens") or 0),
        int(reasoning) if reasoning is not None else None,
        float(cost or 0.0),
    )


class OpenRouterProvider:
    def __init__(self, model: str, seed: int) -> None:
        if not os.environ.get("OPENROUTER_API_KEY"):
            raise RuntimeError("OPENROUTER_API_KEY is not set")
        if model not in {CHEAP_MODEL, FRONTIER_MODEL}:
            raise ValueError(f"unsupported Stage 6 model: {model}")
        self.model = model
        self.seed = seed
        self._local = threading.local()

    def _client(self) -> OpenAI:
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

    def generation(self, messages: list[dict[str, str]]) -> ProviderResult:
        cheap = self.model == CHEAP_MODEL
        caps = CHEAP_TOKEN_CAPS if cheap else FRONTIER_TOKEN_CAPS
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "max_tokens": caps["request_max_tokens"],
        }
        if cheap:
            kwargs.update(
                temperature=0.1,
                seed=self.seed,
                extra_body={
                    "reasoning": {
                        "max_tokens": caps["reasoning_tokens"],
                        "exclude": True,
                    }
                },
            )
        else:
            kwargs["extra_body"] = {
                "reasoning": {
                    "max_tokens": caps["reasoning_tokens"],
                    "exclude": True,
                }
            }
        response = self._client().chat.completions.create(**kwargs)
        tokens_in, tokens_out, reasoning, cost = _usage(response)
        return ProviderResult(
            text=response.choices[0].message.content or "",
            response=response.model_dump(mode="json"),
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            reasoning_tokens=reasoning,
            cost_usd=cost,
        )

    def confidence(self, messages: list[dict[str, str]]) -> ProviderResult:
        if self.model != CHEAP_MODEL:
            raise RuntimeError("frontier confidence elicitation is out of scope")
        response = self._client().chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=0,
            max_tokens=CHEAP_TOKEN_CAPS["confidence_max_tokens"],
            seed=self.seed,
            extra_body={"reasoning": {"effort": "none"}},
        )
        tokens_in, tokens_out, reasoning, cost = _usage(response)
        return ProviderResult(
            text=response.choices[0].message.content or "",
            response=response.model_dump(mode="json"),
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            reasoning_tokens=reasoning,
            cost_usd=cost,
        )


def _raw_label(output: Path, arm: str, problem_id: str) -> str:
    path = output / "raw" / f"{arm}__{problem_id}.json"
    try:
        return path.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def _sum_reasoning(calls: list[ProviderResult]) -> int | None:
    values = [call.reasoning_tokens for call in calls if call.reasoning_tokens is not None]
    return sum(values) if values else None


def evaluate_one(
    problem: dict[str, Any],
    output: Path,
    executable: Path,
    provider: OpenRouterProvider,
    arm: str,
    seed: int,
) -> dict[str, Any]:
    generation: ProviderResult | None = None
    confidence_result: ProviderResult | None = None
    errors: list[dict[str, str]] = []
    try:
        generation = provider.generation(generation_messages(problem))
    except Exception as exc:
        errors.append({"call": "generation", "type": type(exc).__name__, "message": str(exc)})
    if generation is not None and arm == CHEAP_ARM:
        try:
            confidence_result = provider.confidence(
                confidence_messages(problem, generation.text)
            )
        except Exception as exc:
            errors.append({"call": "confidence", "type": type(exc).__name__, "message": str(exc)})

    raw_path = output / "raw" / f"{arm}__{problem['id']}.json"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_record = {
        "id": problem["id"],
        "arm": arm,
        "model": provider.model,
        "generation": None
        if generation is None
        else {"text": generation.text, "response": generation.response},
        "confidence": None
        if confidence_result is None
        else {"text": confidence_result.text, "response": confidence_result.response},
        "errors": errors,
    }
    # All provider responses are durable before any candidate/confidence parsing.
    raw_path.write_text(json.dumps(raw_record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    generated_text = generation.text if generation is not None else ""
    candidate_parsed, candidate_text = extract_candidate(generated_text)
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
        "model": provider.model,
        "arm": arm,
        "seed": seed,
        "candidate_parsed": candidate_parsed,
        "lean_kind": lean_kind,
        "lean_status": lean_status,
        "correct": correct,
        "confidence": confidence,
        "confidence_source": "p_true" if arm == CHEAP_ARM else None,
        "tokens_in": sum(call.tokens_in for call in calls),
        "tokens_out": sum(call.tokens_out for call in calls),
        "reasoning_tokens": _sum_reasoning(calls),
        "cost_usd": sum(call.cost_usd for call in calls),
        "raw_path": _raw_label(output, arm, problem["id"]),
    }
    if set(row) != RESULT_KEYS:
        raise AssertionError(f"result schema mismatch: {set(row) ^ RESULT_KEYS}")
    return row


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")


def load_results(output: Path) -> list[dict[str, Any]]:
    path = output / "results.jsonl"
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _result_sort(row: dict[str, Any]) -> tuple[int, int, int, str]:
    return (
        0 if row["arm"] == CHEAP_ARM else 1,
        int(row["houses"]),
        int(row["categories"]),
        str(row["id"]),
    )


def run_arm(
    problems: list[dict[str, Any]],
    output: Path,
    executable: Path,
    *,
    model: str,
    arm: str,
    seed: int,
    workers: int,
    budget_usd: float | None = None,
    hard_call_bounds: dict[str, float] | None = None,
) -> list[dict[str, Any]]:
    existing_rows = load_results(output)
    existing = {(row["arm"], row["id"]): row for row in existing_rows}
    pending = [problem for problem in problems if (arm, problem["id"]) not in existing]
    provider = OpenRouterProvider(model, seed)
    completed = 0

    def retain(row: dict[str, Any]) -> None:
        nonlocal completed
        existing[(arm, row["id"])] = row
        completed += 1
        rows = sorted(existing.values(), key=_result_sort)
        _write_jsonl(output / "results.jsonl", rows)
        print(f"{arm}: {completed}/{len(pending)} {row['id']}", flush=True)

    if arm == FRONTIER_ARM:
        for problem in pending:
            spent = sum(
                float(row["cost_usd"])
                for row in existing.values()
                if row["arm"] == FRONTIER_ARM
            )
            bound = (hard_call_bounds or {}).get(problem["id"], 0.0)
            if budget_usd is not None and spent + bound > budget_usd + 1e-9:
                raise RuntimeError(
                    f"Opus hard budget guard stopped before {problem['id']}: "
                    f"spent={spent:.6f}, next_bound={bound:.6f}, ceiling={budget_usd:.2f}"
                )
            retain(evaluate_one(problem, output, executable, provider, arm, seed))
    elif workers <= 1:
        for problem in pending:
            retain(evaluate_one(problem, output, executable, provider, arm, seed))
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(evaluate_one, problem, output, executable, provider, arm, seed): problem
                for problem in pending
            }
            for future in as_completed(futures):
                retain(future.result())
    return [existing[(arm, problem["id"])] for problem in problems]


def prepare_working_set(
    compiled_path: Path, output: Path, executable: Path
) -> dict[str, Any]:
    problems = load_compiled_problems(compiled_path)
    uniqueness_rows: list[dict[str, Any]] = []
    for index, problem in enumerate(problems, start=1):
        compile_problem(executable, problem)
        outcome = solve_problem(problem, timeout_seconds=5.0)
        uniqueness_rows.append(
            {
                "id": problem["id"],
                "grid_size": problem["source"]["grid"],
                "houses": problem["size"]["houses"],
                "categories": problem["size"]["categories"],
                "status": outcome.status,
                "models": len(outcome.models),
                "elapsed_seconds": outcome.elapsed_seconds,
                "message": outcome.message,
            }
        )
        if index % 100 == 0:
            print(f"compiled and uniqueness-checked {index}/{len(problems)}", flush=True)
    _write_jsonl(output / "uniqueness.jsonl", uniqueness_rows)
    counts = Counter(row["status"] for row in uniqueness_rows)
    manifest = {
        "available": len(problems),
        "verified_unique": counts["unique"],
        "excluded": len(problems) - counts["unique"],
        "status_counts": dict(sorted(counts.items())),
        "total_clingo_seconds": sum(row["elapsed_seconds"] for row in uniqueness_rows),
        "grid_breakdown": dict(
            sorted(Counter(problem["source"]["grid"] for problem in problems).items())
        ),
    }
    _write_json(output / "prepared.json", manifest)
    if manifest["verified_unique"] != 1000 or manifest["excluded"] != 0:
        raise RuntimeError(f"expected 1000 unique puzzles, got {manifest}")
    return manifest


def wilson(successes: int, n: int, z: float = 1.959963984540054) -> dict[str, float]:
    if n == 0:
        return {"estimate": 0.0, "low": 0.0, "high": 0.0}
    p = successes / n
    denominator = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denominator
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * n)) / n) / denominator
    return {"estimate": p, "low": max(0.0, center - margin), "high": min(1.0, center + margin)}


def _outcomes(rows: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(rows)
    counts = {
        "solved": sum(row["lean_kind"] == "ACCEPT_SOLVED" for row in rows),
        "clue_violation": sum(row["lean_status"] == "clue_violation" for row in rows),
        "malformed": sum(row["lean_status"] == "malformed" for row in rows),
        "incomplete": sum(row["lean_status"] == "incomplete" for row in rows),
        "invalid": sum(row["lean_status"] == "invalid" for row in rows),
    }
    return {
        "counts": counts,
        "rates": {key: wilson(value, n) for key, value in counts.items()},
    }


def _cheap_block(rows: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(rows)
    solved = sum(bool(row["correct"]) for row in rows)
    wrong = n - solved
    curve: list[dict[str, Any]] = []
    for tau in TAUS:
        committed = [
            row
            for row in rows
            if row["confidence"] is not None and float(row["confidence"]) >= tau
        ]
        committed_wrong = sum(not row["correct"] for row in committed)
        curve.append(
            {
                "tau": tau,
                "coverage": len(committed) / n if n else 0.0,
                "selective_risk": committed_wrong / len(committed) if committed else 0.0,
                "committed": len(committed),
                "wrong": committed_wrong,
            }
        )
    return {
        "n": n,
        "outcomes": _outcomes(rows),
        "unchecked": {
            "coverage": 1.0 if n else 0.0,
            "accuracy": wilson(solved, n),
            "confident_wrong_rate": wilson(wrong, n),
        },
        "mode0": {
            "coverage": wilson(solved, n),
            "selective_risk": 0.0,
            "catastrophic_rate": 0.0,
            "committed_correct": solved,
        },
        "ptrue_curve": curve,
    }


def _arm_cost_block(rows: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(rows)
    solved = sum(bool(row["correct"]) for row in rows)
    cost = sum(float(row["cost_usd"]) for row in rows)
    return {
        "n": n,
        "coverage": solved / n if n else 0.0,
        "coverage_ci95": wilson(solved, n),
        "committed_correct": solved,
        "total_cost_usd": cost,
        "cost_per_verified_correct": cost / solved if solved else None,
        "malformed_rate": sum(row["lean_status"] == "malformed" for row in rows) / n
        if n
        else 0.0,
        "outcomes": _outcomes(rows),
    }


def compute_metrics(rows: list[dict[str, Any]], frontier_ids: set[str]) -> dict[str, Any]:
    cheap = [row for row in rows if row["arm"] == CHEAP_ARM]
    frontier = [row for row in rows if row["arm"] == FRONTIER_ARM]
    cheap_shared = [row for row in cheap if row["id"] in frontier_ids]
    by_houses = {
        str(house): _cheap_block([row for row in cheap if row["houses"] == house])
        for house in range(2, 7)
    }
    grids = sorted({str(row["grid_size"]) for row in cheap})
    by_grid = {
        grid: _cheap_block([row for row in cheap if row["grid_size"] == grid])
        for grid in grids
    }
    cheap_overall = _cheap_block(cheap)
    comparable = [
        point
        for point in cheap_overall["ptrue_curve"]
        if point["coverage"] >= cheap_overall["mode0"]["coverage"]["estimate"]
    ]
    best_risk = min((point["selective_risk"] for point in comparable), default=None)
    h5_note = (
        "H5 here is the HONEST single-shot version: \"cheap+Lean vs frontier+Lean, both "
        "gated to ~100% precision; cheap is cheaper but coverage-capped at its raw solve "
        "rate; this is NOT the retry/feedback H5 (that needs Stage 4/5).\""
    )
    return {
        "cheap_overall": cheap_overall,
        "by_houses": by_houses,
        "by_grid": by_grid,
        "H2": {
            "unchecked_confident_wrong_rate": cheap_overall["unchecked"][
                "confident_wrong_rate"
            ],
            "mode0_catastrophic_rate": 0.0,
            "drop": cheap_overall["unchecked"]["confident_wrong_rate"]["estimate"],
        },
        "H3": {
            "lean_point": {
                "coverage": cheap_overall["mode0"]["coverage"]["estimate"],
                "selective_risk": 0.0,
            },
            "ptrue_curve": cheap_overall["ptrue_curve"],
            "best_ptrue_risk_at_equal_or_higher_coverage": best_risk,
            "note": "P(True) is a weak, highly concentrated baseline; Lean is the correctness gate.",
        },
        "H11": {
            "primary_bins": {
                house: {
                    "n": block["n"],
                    "confident_wrong_rate": block["unchecked"]["confident_wrong_rate"],
                    "mode0_coverage": block["mode0"]["coverage"],
                    "malformed_rate": block["outcomes"]["rates"]["malformed"],
                    "clue_violation_rate": block["outcomes"]["rates"]["clue_violation"],
                }
                for house, block in by_houses.items()
            },
            "note": "Difficulty scaling is reported by house count with Wilson 95% intervals.",
        },
        "H5_single_shot": {
            "directional": True,
            "shared_subset_n": len(frontier_ids),
            "cheap_mode0": _arm_cost_block(cheap_shared),
            "frontier_mode0": _arm_cost_block(frontier),
            "note": h5_note + " The shared frontier subset is small and directional/preliminary.",
        },
        "malformed_rate": {
            CHEAP_ARM: _outcomes(cheap)["rates"]["malformed"],
            FRONTIER_ARM: _outcomes(frontier)["rates"]["malformed"],
            "prior_cheap_run": PRIOR_MALFORMED_RATE,
        },
    }


def _theoretical_opus_call_cost(problem: dict[str, Any]) -> float:
    prompt_chars = sum(len(message["content"]) for message in generation_messages(problem))
    conservative_input_tokens = math.ceil(prompt_chars / 3)
    return (
        conservative_input_tokens * OPUS_PROMPT_PRICE
        + FRONTIER_TOKEN_CAPS["request_max_tokens"] * OPUS_COMPLETION_PRICE
    )


def choose_frontier_n(
    problems: list[dict[str, Any]], probe_rows: list[dict[str, Any]], seed: int
) -> dict[str, Any]:
    probe_ids = {row["id"] for row in probe_rows}
    probe_costs = [float(row["cost_usd"]) for row in probe_rows]
    if len(probe_rows) != 3 or any(cost <= 0 for cost in probe_costs):
        raise RuntimeError("Opus connectivity probe did not produce three billed responses")
    projected_per_puzzle = max(sum(probe_costs) / len(probe_costs) * 1.25, max(probe_costs))
    candidates: list[dict[str, Any]] = []
    for n in (25, 30, 35, 40):
        subset = frontier_subset(problems, n, seed, probe_ids)
        projected = projected_per_puzzle * n
        hard_upper = sum(_theoretical_opus_call_cost(problem) for problem in subset)
        if projected <= OPUS_BUDGET_USD and hard_upper <= OPUS_BUDGET_USD:
            candidates.append(
                {
                    "n": n,
                    "projected_cost_usd": projected,
                    "hard_token_cap_upper_usd": hard_upper,
                    "ids": [problem["id"] for problem in subset],
                }
            )
    if not candidates:
        raise RuntimeError(
            f"even 25 Opus puzzles do not fit the $5 ceiling; probe costs={probe_costs}"
        )
    chosen = candidates[-1]
    chosen.update(
        {
            "budget_usd": OPUS_BUDGET_USD,
            "probe_n": 3,
            "probe_ids": sorted(probe_ids),
            "probe_costs_usd": probe_costs,
            "probe_total_cost_usd": sum(probe_costs),
            "projected_per_puzzle_usd_with_25pct_margin": projected_per_puzzle,
            "selection_rule": (
                "largest N in {25,30,35,40}, divisible across five house bins, whose "
                "probe projection and conservative token-cap upper bound are both <= $5"
            ),
        }
    )
    return chosen


def rescore_all(
    rows: list[dict[str, Any]], problems_by_id: dict[str, dict[str, Any]], output: Path, executable: Path
) -> list[dict[str, Any]]:
    for row in rows:
        problem = problems_by_id[row["id"]]
        raw_path = Path(row["raw_path"])
        if not raw_path.is_absolute():
            raw_path = Path.cwd() / raw_path
        raw = json.loads(raw_path.read_text(encoding="utf-8"))
        generation = raw.get("generation")
        text = generation.get("text", "") if generation else ""
        parsed, candidate_text = extract_candidate(text)
        lean_kind, lean_status, correct, lean_result = check_candidate(
            executable, problem, candidate_text
        )
        row.update(
            candidate_parsed=parsed,
            lean_kind=lean_kind,
            lean_status=lean_status,
            correct=correct,
        )
        raw["lean_result"] = lean_result
        raw_path.write_text(json.dumps(raw, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    _write_jsonl(output / "results.jsonl", sorted(rows, key=_result_sort))
    return rows


def render_summary(metrics: dict[str, Any], manifest: dict[str, Any]) -> str:
    h2 = metrics["H2"]
    h3 = metrics["H3"]
    h5 = metrics["H5_single_shot"]
    lines = [
        "# Stage 6 Mode-0 cleanup + frontier H5 single-shot",
        "",
        f"Cheap arm: **N={manifest['n'][CHEAP_ARM]}** with `{manifest['models'][CHEAP_ARM]['id']}`. "
        f"Frontier arm: **N={manifest['n'][FRONTIER_ARM]}** with "
        f"`{manifest['models'][FRONTIER_ARM]['id']}` on a paired subset.",
        "",
        "Lean `check_candidate` is the sole correctness judge. Oracle certificates contain no "
        "`expect`/gold field in either prompts or verifier requests.",
        "",
        "## Headline findings",
        "",
        f"- Malformed fix: cheap malformed rate fell from {PRIOR_MALFORMED_RATE:.3f} to "
        f"{metrics['malformed_rate'][CHEAP_ARM]['estimate']:.3f} now; frontier malformed rate "
        f"{metrics['malformed_rate'][FRONTIER_ARM]['estimate']:.3f}.",
        f"- H2: unchecked confident-wrong {h2['unchecked_confident_wrong_rate']['estimate']:.3f} "
        f"to Mode-0 catastrophic rate {h2['mode0_catastrophic_rate']:.3f} (drop {h2['drop']:.3f}).",
        f"- H3: Lean point ({h3['lean_point']['coverage']:.3f} coverage, 0.000 risk); "
        f"best swept P(True) risk at equal-or-higher coverage "
        f"{h3['best_ptrue_risk_at_equal_or_higher_coverage']:.3f}.",
        f"- H5 directional paired subset: cheap coverage {h5[CHEAP_ARM]['coverage']:.3f} at "
        f"${h5[CHEAP_ARM]['cost_per_verified_correct']:.4f}/verified correct; frontier coverage "
        f"{h5[FRONTIER_ARM]['coverage']:.3f} at "
        f"${h5[FRONTIER_ARM]['cost_per_verified_correct']:.4f}/verified correct.",
        "",
        "## H11: primary house-count bins (Wilson 95% CI)",
        "",
        "| Houses | N | Wrong rate [95% CI] | Mode-0 coverage [95% CI] | Malformed | Clue violation |",
        "|---:|---:|---:|---:|---:|---:|",
    ]
    for house, block in metrics["H11"]["primary_bins"].items():
        wrong = block["confident_wrong_rate"]
        coverage = block["mode0_coverage"]
        lines.append(
            f"| {house} | {block['n']} | {wrong['estimate']:.3f} "
            f"[{wrong['low']:.3f}, {wrong['high']:.3f}] | {coverage['estimate']:.3f} "
            f"[{coverage['low']:.3f}, {coverage['high']:.3f}] | "
            f"{block['malformed_rate']['estimate']:.3f} | "
            f"{block['clue_violation_rate']['estimate']:.3f} |"
        )
    lines += [
        "",
        "## H5 framing",
        "",
        "H5 here is the HONEST single-shot version: \"cheap+Lean vs frontier+Lean, both gated "
        "to ~100% precision; cheap is cheaper but coverage-capped at its raw solve rate; this "
        "is NOT the retry/feedback H5 (that needs Stage 4/5).\"",
        "",
        "This shared frontier subset is a DIRECTIONAL/preliminary cost-coverage probe because "
        "it is small. It can be scaled later.",
        "",
        "## Costs and scope",
        "",
        f"- Cheap total: ${manifest['costs_usd'][CHEAP_ARM]:.4f}.",
        f"- Opus probe projection: ${manifest['opus_cost_gate']['projected_cost_usd']:.4f} for "
        f"N={manifest['opus_cost_gate']['n']} vs the hard $5.00 ceiling; actual frontier total "
        f"${manifest['costs_usd'][FRONTIER_ARM]:.4f}.",
        "- Mode-0 single shot only: no retry, nudge, best-of-N, trace, or stepwise operation.",
        "- Oracle certificates only. Faithfulness and H1 are not tested.",
        "- P(True) is a weak baseline and was elicited only for the cheap arm.",
        "- Malformed and parsed clue-violation outcomes remain separate in every metrics block.",
        "- Per-grid secondary results are in `metrics.json`; rendered figures are reproducible "
        "from `plot_stage6.py`.",
        "",
    ]
    return "\n".join(lines)


def finalize(
    compiled_path: Path,
    output: Path,
    executable: Path,
    git_commit: str,
) -> dict[str, Any]:
    problems = load_compiled_problems(compiled_path)
    problems_by_id = {problem["id"]: problem for problem in problems}
    rows = rescore_all(load_results(output), problems_by_id, output, executable)
    cheap = [row for row in rows if row["arm"] == CHEAP_ARM]
    frontier = [row for row in rows if row["arm"] == FRONTIER_ARM]
    if len(cheap) != 1000:
        raise RuntimeError(f"expected 1000 cheap rows, found {len(cheap)}")
    probe = json.loads((output / "opus_cost_gate.json").read_text(encoding="utf-8"))
    frontier_ids = {row["id"] for row in frontier}
    if frontier_ids != set(probe["ids"]):
        raise RuntimeError("frontier results do not match the selected paired subset")
    metrics = compute_metrics(rows, frontier_ids)
    prepared = json.loads((output / "prepared.json").read_text(encoding="utf-8"))
    def breakdown(arm_rows: list[dict[str, Any]], key: str) -> dict[str, int]:
        return dict(sorted(Counter(str(row[key]) for row in arm_rows).items()))
    manifest = {
        "gate": "stage6_mode0_h5_cleanup",
        "date": date.today().isoformat(),
        "models": {
            CHEAP_ARM: {
                "id": CHEAP_MODEL,
                "provider": "openrouter",
                "endpoint": OPENROUTER_ENDPOINT,
                "seed_supported": True,
            },
            FRONTIER_ARM: {
                "id": FRONTIER_MODEL,
                "provider": "openrouter",
                "endpoint": OPENROUTER_ENDPOINT,
                "seed_supported": False,
            },
        },
        "seeds": {"sampling": SEED, "cheap_generation": SEED, "frontier_recorded": SEED},
        "n": {CHEAP_ARM: len(cheap), FRONTIER_ARM: len(frontier)},
        "grid_breakdown": {
            CHEAP_ARM: breakdown(cheap, "grid_size"),
            FRONTIER_ARM: breakdown(frontier, "grid_size"),
        },
        "house_bin_breakdown": {
            CHEAP_ARM: breakdown(cheap, "houses"),
            FRONTIER_ARM: breakdown(frontier, "houses"),
        },
        "verifier_version": PROTOCOL_VERSION,
        "git_commit": git_commit,
        "prompt_template_hash": prompt_template_hash(),
        "prompt_template_path": "eval/gates/stage6_mode0_h5_cleanup/prompt_template.txt",
        "reused_count": 0,
        "regenerated_count": len(cheap),
        "reuse_predicate": (
            "prior output reusable only if prompt hash, seed, sampling parameters, and model "
            "match and finish_reason is not length; predicate was false because prompt changed"
        ),
        "clingo_uniqueness_verified": prepared["verified_unique"],
        "clingo_uniqueness_excluded": prepared["excluded"],
        "token_caps": {CHEAP_ARM: CHEAP_TOKEN_CAPS, FRONTIER_ARM: FRONTIER_TOKEN_CAPS},
        "opus_cost_gate": probe,
        "costs_usd": {
            CHEAP_ARM: sum(float(row["cost_usd"]) for row in cheap),
            FRONTIER_ARM: sum(float(row["cost_usd"]) for row in frontier),
        },
        "tokens": {
            arm: {
                "input": sum(int(row["tokens_in"]) for row in arm_rows),
                "output_including_reasoning": sum(int(row["tokens_out"]) for row in arm_rows),
                "reasoning_reported": sum(int(row["reasoning_tokens"] or 0) for row in arm_rows),
            }
            for arm, arm_rows in ((CHEAP_ARM, cheap), (FRONTIER_ARM, frontier))
        },
        "raw_outputs_stored_before_parsing": True,
        "expect_excluded_from_prompt_and_verifier": True,
        "correctness_judge": "Lean check_candidate ACCEPT_SOLVED only",
        "scope": "Mode-0 single-shot only; no retries, nudges, best-of-N, traces, or stepwise ops",
    }
    _write_json(output / "metrics.json", metrics)
    _write_json(output / "manifest.json", manifest)
    (output / "summary.md").write_text(render_summary(metrics, manifest), encoding="utf-8")
    (output / "prompt_template.txt").write_text(PROMPT_TEMPLATE_TEXT, encoding="utf-8")
    return manifest


def git_head(root: Path) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True, capture_output=True, check=True
    ).stdout.strip()
