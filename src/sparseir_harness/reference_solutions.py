"""Reference-only clingo solutions checked by the trusted Lean candidate checker."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

try:
    import clingo as _clingo
except ImportError:  # exercised by the explicit missing-clingo gate test
    _clingo = None


ROOT = Path(__file__).resolve().parents[2]
ENCODING_VERSION = "stage3a-clingo-reference-v1"


@dataclass
class SolveOutcome:
    status: str
    models: list[list[tuple[int, int, int]]]
    elapsed_seconds: float
    message: str | None = None


def _index_problem(problem: dict[str, Any]) -> tuple[list[str], list[list[str]], dict[tuple[str, str], tuple[int, int]]]:
    category_names = list(problem["categories"])
    values = [problem["categories"][category] for category in category_names]
    attributes = {
        (category, value): (category_index, value_index)
        for category_index, category in enumerate(category_names)
        for value_index, value in enumerate(values[category_index])
    }
    return category_names, values, attributes


def build_asp_program(problem: dict[str, Any]) -> str:
    """Encode a compiled-shape Zebra puzzle without reading `expect`."""
    category_names, values, attributes = _index_problem(problem)
    houses = problem["size"]["houses"]
    lines = [
        f"house(1..{houses}).",
        *(f"category({category})." for category in range(len(category_names))),
        *(
            f"value({category},{value})."
            for category, category_values in enumerate(values)
            for value in range(len(category_values))
        ),
        "1 { at(C,V,H) : house(H) } 1 :- value(C,V).",
        "1 { at(C,V,H) : value(C,V) } 1 :- category(C), house(H).",
    ]

    def attr(raw: dict[str, str]) -> tuple[int, int]:
        return attributes[(raw["cat"], raw["val"])]

    for clue in problem["clues"]:
        clue_type = clue["type"]
        if clue_type in {"found_at", "not_at"}:
            category, value = attributes[(clue["cat"], clue["val"])]
            atom = f"at({category},{value},{clue['house']})"
            lines.append(f":- not {atom}." if clue_type == "found_at" else f":- {atom}.")
            continue
        ac, av = attr(clue["a"])
        bc, bv = attr(clue["b"])
        prefix = f":- at({ac},{av},HA), at({bc},{bv},HB), "
        condition = {
            "same_house": "HA != HB",
            "direct_left": "HB != HA + 1",
            "direct_right": "HA != HB + 1",
            "side_by_side": "HA + 1 != HB, HB + 1 != HA",
            "left_of": "HA >= HB",
            "right_of": "HA <= HB",
            "one_between": "HA + 2 != HB, HB + 2 != HA",
            "two_between": "HA + 3 != HB, HB + 3 != HA",
        }[clue_type]
        lines.append(prefix + condition + ".")
    lines.append("#show at/3.")
    return "\n".join(lines) + "\n"


def solve_problem(
    problem: dict[str, Any],
    timeout_seconds: float,
    clingo_module: Any = _clingo,
) -> SolveOutcome:
    if clingo_module is None:
        return SolveOutcome("error", [], 0.0, "clingo is not installed")
    started = time.monotonic()
    try:
        control = clingo_module.Control(["--models=2", "--warn=none"])
        control.add("base", [], build_asp_program(problem))
        control.ground([("base", [])])
        models: list[list[tuple[int, int, int]]] = []

        def capture(model: Any) -> None:
            assignments = []
            for symbol in model.symbols(shown=True):
                if symbol.name == "at" and len(symbol.arguments) == 3:
                    assignments.append(tuple(argument.number for argument in symbol.arguments))
            models.append(sorted(assignments))

        with control.solve(on_model=capture, async_=True) as handle:
            if not handle.wait(timeout_seconds):
                handle.cancel()
                handle.wait()
                return SolveOutcome("timeout", models, time.monotonic() - started)
            result = handle.get()
        elapsed = time.monotonic() - started
        if len(models) >= 2:
            return SolveOutcome("nonunique", models[:2], elapsed)
        if len(models) == 1 and result.satisfiable and result.exhausted:
            return SolveOutcome("unique", models, elapsed)
        if not models and result.unsatisfiable:
            return SolveOutcome("unsat", [], elapsed)
        return SolveOutcome("error", models, elapsed, "clingo returned an indeterminate result")
    except Exception as exc:  # clingo errors must be retained as gate evidence
        return SolveOutcome("error", [], time.monotonic() - started, str(exc))


def candidate_from_model(
    problem: dict[str, Any], model: list[tuple[int, int, int]]
) -> dict[str, Any]:
    category_names, values, _ = _index_problem(problem)
    solution: dict[str, dict[str, str]] = {category: {} for category in category_names}
    for category, value, house in model:
        solution[category_names[category]][str(house)] = values[category][value]
    solution = {
        category: dict(sorted(assignments.items(), key=lambda item: int(item[0])))
        for category, assignments in solution.items()
    }
    return {"schema_version": "0.2", "problem_id": problem["id"], "solution": solution}


def _invoke_lean(request: dict[str, Any], executable: Path | None) -> dict[str, Any]:
    if executable is not None:
        command = [str(executable)]
    else:
        lake = shutil.which("lake")
        if lake is None:
            raise RuntimeError("lake was not found on PATH")
        command = [lake, "exe", "sparse-ir-lean"]
    completed = subprocess.run(
        command,
        input=json.dumps(request),
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"Lean verifier exited with {completed.returncode}: {completed.stderr.strip()}"
        )
    return json.loads(completed.stdout)


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def _relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def run_reference_gate(
    gate_a_dir: Path,
    output: Path,
    max_problems: int | None,
    timeout_seconds: float,
    store_reference_solutions: bool,
    *,
    clingo_module: Any = _clingo,
    solver: Callable[[dict[str, Any], float, Any], SolveOutcome] = solve_problem,
    lean_invoke: Callable[[dict[str, Any], Path | None], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    problem_paths = sorted((gate_a_dir / "ingested_problems").glob("*.problem.json"))
    selected_paths = problem_paths if max_problems is None else problem_paths[:max_problems]
    available_grids: Counter[str] = Counter()
    for path in problem_paths:
        available_grids[json.loads(path.read_text(encoding="utf-8"))["source"]["grid"]] += 1

    output.mkdir(parents=True, exist_ok=True)
    model_dir = output / "clingo_models"
    candidate_dir = output / "candidate_json"
    reference_dir = output / "reference_solutions"
    for directory in (model_dir, candidate_dir, reference_dir):
        directory.mkdir(parents=True, exist_ok=True)
        for stale in directory.glob("*.json"):
            stale.unlink()

    problem_rows: list[dict[str, Any]] = []
    reference_rows: list[dict[str, Any]] = []
    candidate_rows: list[dict[str, Any]] = []
    result_rows: list[dict[str, Any]] = []
    uniqueness_rows: list[dict[str, Any]] = []
    failure_rows: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    grid_coverage: dict[str, Counter[str]] = {
        grid: Counter(available=count) for grid, count in sorted(available_grids.items())
    }

    if clingo_module is None:
        failure_rows.append({"failure_type": "missing_clingo", "message": "clingo is not installed"})
        status = "blocked"
    else:
        if lean_invoke is None:
            lean_invoke = _invoke_lean
        executable = ROOT / ".lake" / "build" / "bin" / "sparse-ir-lean"
        executable_arg = executable if executable.is_file() else None
        clingo_version = getattr(clingo_module, "__version__", "unknown")
        for index, problem_path in enumerate(selected_paths, start=1):
            raw = problem_path.read_bytes()
            problem = json.loads(raw)
            problem_id = problem["id"]
            external_id = problem["source"]["external_id"]
            grid = problem["source"]["grid"]
            source_path = _relative(problem_path)
            source_sha256 = hashlib.sha256(raw).hexdigest()
            counts["attempted"] += 1
            grid_coverage[grid]["attempted"] += 1
            outcome = solver(problem, timeout_seconds, clingo_module)
            uniqueness = {
                "problem_id": problem_id,
                "external_id": external_id,
                "grid": grid,
                "status": outcome.status,
                "model_count_observed": len(outcome.models),
                "requested_model_limit": 2,
                "elapsed_seconds": round(outcome.elapsed_seconds, 6),
                "message": outcome.message,
            }
            uniqueness_rows.append(uniqueness)
            counts[outcome.status] += 1
            if outcome.status in {"unique", "nonunique"}:
                counts["clingo_solved"] += 1
                grid_coverage[grid]["clingo_solved"] += 1
            problem_rows.append(
                {
                    "problem_id": problem_id,
                    "external_id": external_id,
                    "grid": grid,
                    "source_problem_path": source_path,
                    "source_sha256": source_sha256,
                    "clingo_status": outcome.status,
                }
            )
            if outcome.status not in {"unique", "nonunique"}:
                failure_rows.append(
                    {
                        "problem_id": problem_id,
                        "failure_type": f"clingo_{outcome.status}",
                        "message": outcome.message,
                    }
                )
                continue

            model_payload = {
                "problem_id": problem_id,
                "models": [
                    [{"category_index": c, "value_index": v, "house": h} for c, v, h in model]
                    for model in outcome.models
                ],
            }
            model_path = model_dir / f"{external_id}.json"
            model_path.write_text(json.dumps(model_payload, indent=2) + "\n", encoding="utf-8")
            candidate = candidate_from_model(problem, outcome.models[0])
            candidate_path = candidate_dir / f"{external_id}.candidate.json"
            candidate_path.write_text(json.dumps(candidate, indent=2) + "\n", encoding="utf-8")
            candidate_rows.append(
                {
                    "problem_id": problem_id,
                    "external_id": external_id,
                    "grid": grid,
                    "candidate": candidate,
                    "candidate_path": _relative(candidate_path),
                }
            )
            request = {
                "protocol_version": "0.1.0",
                "request_id": f"reference-{external_id}",
                "command": "check_candidate",
                "payload": {"problem": json.dumps(problem), "candidate": json.dumps(candidate)},
            }
            try:
                response = lean_invoke(request, executable_arg)
                result = response["result"]
            except Exception as exc:
                counts["protocol_error"] += 1
                result = {"kind": "PROTOCOL_ERROR", "message": str(exc)}
            accepted = result.get("kind") == "ACCEPT_SOLVED"
            counts["lean_accept_solved" if accepted else "lean_reject"] += 1
            if accepted:
                grid_coverage[grid]["lean_accept_solved"] += 1
            else:
                failure_rows.append(
                    {"problem_id": problem_id, "failure_type": "lean_reject", "result": result}
                )
            result_rows.append(
                {"problem_id": problem_id, "external_id": external_id, "grid": grid, "result": result}
            )
            reference = {
                "generated_by": "clingo",
                "reference_only": True,
                "trusted_for_runtime": False,
                "source_problem_id": problem_id,
                "source_external_id": external_id,
                "source_grid": grid,
                "source_problem_path": source_path,
                "source_sha256": source_sha256,
                "clingo_version": clingo_version,
                "encoding_version": ENCODING_VERSION,
                "uniqueness_status": outcome.status,
                "candidate": candidate,
                "lean_check_result": result,
            }
            if store_reference_solutions:
                reference_path = reference_dir / f"{external_id}.reference_solution.json"
                reference_path.write_text(json.dumps(reference, indent=2) + "\n", encoding="utf-8")
                reference["reference_solution_path"] = _relative(reference_path)
                counts["reference_solutions_stored"] += 1
            reference_rows.append(reference)
            if index % 25 == 0 or index == len(selected_paths):
                print(f"processed {index}/{len(selected_paths)} Gate A problems", flush=True)

        all_attempted = counts["attempted"] == len(problem_paths)
        all_solved = counts["clingo_solved"] == counts["attempted"]
        all_stored = counts["reference_solutions_stored"] == counts["clingo_solved"]
        all_lean = counts["lean_accept_solved"] == counts["clingo_solved"]
        all_grids = all(
            coverage["lean_accept_solved"] > 0 for coverage in grid_coverage.values()
        )
        if (
            all_attempted
            and all_solved
            and all_stored
            and all_lean
            and counts["unique"] == counts["attempted"]
            and counts["nonunique"] == 0
            and counts["unsat"] == 0
            and counts["timeout"] == 0
            and counts["error"] == 0
            and counts["lean_reject"] == 0
            and counts["protocol_error"] == 0
            and all_grids
        ):
            status = "pass"
        else:
            status = "partial"

    _write_jsonl(output / "problems.jsonl", problem_rows)
    _write_jsonl(output / "reference_solutions.jsonl", reference_rows)
    _write_jsonl(output / "candidates.jsonl", candidate_rows)
    _write_jsonl(output / "results.jsonl", result_rows)
    _write_jsonl(output / "uniqueness.jsonl", uniqueness_rows)
    _write_jsonl(output / "failures.jsonl", failure_rows)
    manifest = {
        "gate": "stage3a_reference_solutions",
        "status": status,
        "total_problems_available": len(problem_paths),
        "total_problems_attempted": counts["attempted"],
        "total_clingo_solved": counts["clingo_solved"],
        "total_clingo_unique": counts["unique"],
        "total_clingo_nonunique": counts["nonunique"],
        "total_clingo_unsat": counts["unsat"],
        "total_clingo_timeout": counts["timeout"],
        "total_clingo_error": counts["error"],
        "total_reference_solutions_stored": counts["reference_solutions_stored"],
        "total_lean_accept_solved": counts["lean_accept_solved"],
        "total_lean_reject": counts["lean_reject"],
        "total_protocol_error": counts["protocol_error"],
        "grid_coverage": {grid: dict(coverage) for grid, coverage in grid_coverage.items()},
        "failure_count": len(failure_rows),
        "encoding_version": ENCODING_VERSION,
        "reference_only": True,
        "trusted_for_runtime": False,
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    examples = ["# Stage 3A clingo reference examples", ""]
    for reference in reference_rows[:3]:
        examples.extend(["```json", json.dumps(reference, indent=2), "```", ""])
    (output / "examples.md").write_text("\n".join(examples), encoding="utf-8")
    summary = f"""# Stage 3A reference solutions

Status: **{status.upper()}**

- Problems available: {len(problem_paths)}
- Problems attempted: {counts['attempted']}
- Clingo solved: {counts['clingo_solved']}
- Clingo unique: {counts['unique']}
- Clingo nonunique: {counts['nonunique']}
- Clingo unsat: {counts['unsat']}
- Clingo timeout: {counts['timeout']}
- Clingo error: {counts['error']}
- Reference solutions stored: {counts['reference_solutions_stored']}
- Lean ACCEPT_SOLVED: {counts['lean_accept_solved']}
- Lean rejects: {counts['lean_reject']}
- Protocol errors: {counts['protocol_error']}

Clingo generated these assignments as development-only references. They are
`reference_only=true`, `trusted_for_runtime=false`, and every stored candidate is
accepted or rejected only by Lean's `check_candidate` verdict.
"""
    (output / "summary.md").write_text(summary, encoding="utf-8")
    return manifest
