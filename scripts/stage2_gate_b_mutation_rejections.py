#!/usr/bin/env python3
"""Prove Lean rejects deterministic Stage 2 mutations of real Gate A problems."""

from __future__ import annotations

import argparse
import json
import shlex
import shutil
import subprocess
import sys
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any

from run_lean_verifier import invoke


PROTOCOL_VERSION = "0.1.0"
REQUIRED_ERROR_CODES = (
    "unsupported_schema_version",
    "invalid_domain",
    "size_mismatch",
    "category_size_mismatch",
    "duplicate_value",
    "duplicate_clue_id",
    "unknown_category",
    "unknown_value",
    "house_out_of_range",
)
TARGET_GRIDS = ("2x2", "4x4", "6x6")
UNARY_TYPES = {"found_at", "not_at"}


@dataclass(frozen=True)
class SourceProblem:
    problem_id: str
    external_id: str
    grid: str
    path: str
    problem: dict[str, Any]


@dataclass(frozen=True)
class Mutation:
    mutation_id: str
    source: SourceProblem
    mutation_kind: str
    expected_error_code: str
    expected_error_path: str
    description: str
    before_snippet: str
    after_snippet: str
    problem: dict[str, Any]


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"{path}:{line_number} is not a JSON object")
        rows.append(value)
    return rows


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as output:
        for row in rows:
            output.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _resolve(repo_root: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else repo_root / path


def _display(path: Path, repo_root: Path) -> str:
    path = path.resolve()
    return (
        path.relative_to(repo_root.resolve()).as_posix()
        if path.is_relative_to(repo_root.resolve())
        else path.as_posix()
    )


def load_gate_a_problems(repo_root: Path, gate_a_dir: Path) -> list[SourceProblem]:
    manifest = json.loads((gate_a_dir / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("gate") != "stage2_gate_a_compile_all" or manifest.get("status") != "pass":
        raise ValueError("Gate A manifest is missing or not passing")
    audit_manifest = gate_a_dir.parent / f"{gate_a_dir.name}_audit" / "manifest.json"
    if not audit_manifest.is_file():
        raise ValueError("passing Gate A dataset audit manifest is required")
    audit = json.loads(audit_manifest.read_text(encoding="utf-8"))
    if audit.get("status") != "pass" or audit.get("total_errors") != 0:
        raise ValueError("Gate A dataset audit is not passing with zero errors")

    rows = _read_jsonl(gate_a_dir / "source_manifest.jsonl")
    ingested = [row for row in rows if row.get("status") == "ingested"]
    if not ingested:
        raise ValueError("Gate A has no ingested real problems")
    problems: list[SourceProblem] = []
    for row in ingested:
        path_value = row.get("ingested_problem_path")
        if not isinstance(path_value, str):
            raise ValueError(f"Gate A source row has no ingested path: {row.get('problem_id')}")
        path = _resolve(repo_root, path_value)
        problem = json.loads(path.read_text(encoding="utf-8"))
        source = problem.get("source") if isinstance(problem, dict) else None
        if (
            not isinstance(source, dict)
            or problem.get("id") != row.get("problem_id")
            or source.get("external_id") != row.get("external_id")
            or source.get("grid") != row.get("grid")
        ):
            raise ValueError(f"Gate A problem provenance mismatch: {path_value}")
        problems.append(
            SourceProblem(
                problem_id=row["problem_id"],
                external_id=row["external_id"],
                grid=row["grid"],
                path=path_value,
                problem=problem,
            )
        )
    if len(problems) != manifest.get("total_ingested"):
        raise ValueError("Gate A manifest/source problem count mismatch")
    return sorted(problems, key=lambda item: item.external_id)


def _json_snippet(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _mutate(source: SourceProblem, error_code: str) -> tuple[dict[str, Any], str, str, str, str] | None:
    problem = deepcopy(source.problem)
    if error_code == "unsupported_schema_version":
        before = problem["schema_version"]
        problem["schema_version"] = "gate-b-unsupported"
        return problem, "$.schema_version", "Changed schema_version to an unsupported value.", _json_snippet(before), _json_snippet(problem["schema_version"])
    if error_code == "invalid_domain":
        before = problem["domain"]
        problem["domain"] = "gate-b-invalid-domain"
        return problem, "$.domain", "Changed domain away from zebra.", _json_snippet(before), _json_snippet(problem["domain"])
    if error_code == "size_mismatch":
        before = problem["size"]["categories"]
        problem["size"]["categories"] = before + 1
        return problem, "$.size.categories", "Increased the declared category count without adding a category.", _json_snippet(before), _json_snippet(problem["size"]["categories"])
    if error_code in {"category_size_mismatch", "duplicate_value"}:
        categories = problem.get("categories")
        if not isinstance(categories, dict):
            return None
        candidate = next(
            ((name, values) for name, values in sorted(categories.items()) if isinstance(values, list) and len(values) >= 2),
            None,
        )
        if candidate is None:
            return None
        name, values = candidate
        before = deepcopy(values)
        if error_code == "category_size_mismatch":
            values.pop()
            description = f"Removed one value from category {name}."
            path = f"$.categories.{name}"
        else:
            values[1] = values[0]
            description = f"Duplicated value {values[0]!r} inside category {name}."
            path = f"$.categories.{name}[1]"
        return problem, path, description, _json_snippet(before), _json_snippet(values)
    if error_code == "duplicate_clue_id":
        clues = problem.get("clues")
        if not isinstance(clues, list) or len(clues) < 2:
            return None
        before = clues[1]["id"]
        clues[1]["id"] = clues[0]["id"]
        return problem, "$.clues[1].id", "Reused the first clue ID on the second clue.", _json_snippet(before), _json_snippet(clues[1]["id"])
    if error_code in {"unknown_category", "unknown_value"}:
        clues = problem.get("clues")
        if not isinstance(clues, list):
            return None
        candidate = next(
            ((index, clue) for index, clue in enumerate(clues) if isinstance(clue, dict) and isinstance(clue.get("a"), dict)),
            None,
        )
        if candidate is None:
            return None
        index, clue = candidate
        field = "cat" if error_code == "unknown_category" else "val"
        before = clue["a"][field]
        clue["a"][field] = f"__gate_b_{error_code}__"
        description = f"Changed clue {clue['id']} operand a.{field} to an undeclared name."
        return problem, f"$.clues[{index}].a.{field}", description, _json_snippet(before), _json_snippet(clue["a"][field])
    if error_code == "house_out_of_range":
        clues = problem.get("clues")
        if not isinstance(clues, list):
            return None
        candidate = next(
            ((index, clue) for index, clue in enumerate(clues) if isinstance(clue, dict) and clue.get("type") in UNARY_TYPES),
            None,
        )
        if candidate is None:
            return None
        index, clue = candidate
        before = clue["house"]
        clue["house"] = problem["size"]["houses"] + 1
        return problem, f"$.clues[{index}].house", f"Moved clue {clue['id']} beyond the last house.", _json_snippet(before), _json_snippet(clue["house"])
    raise ValueError(f"unsupported mutation error code: {error_code}")


def generate_mutations(problems: list[SourceProblem]) -> list[Mutation]:
    mutations: list[Mutation] = []
    for error_code in REQUIRED_ERROR_CODES:
        selected: list[SourceProblem] = []
        for grid in TARGET_GRIDS:
            candidates = [problem for problem in problems if problem.grid == grid]
            source = next(
                (candidate for candidate in candidates if _mutate(candidate, error_code) is not None),
                None,
            )
            if source is not None:
                selected.append(source)
        if len(selected) < 3:
            for source in problems:
                if source not in selected and _mutate(source, error_code) is not None:
                    selected.append(source)
                if len(selected) == 3:
                    break
        if not selected:
            continue
        for source in selected:
            mutated = _mutate(source, error_code)
            if mutated is None:
                continue
            problem, path, description, before, after = mutated
            mutation_id = f"{error_code}--{source.external_id}"
            mutations.append(
                Mutation(
                    mutation_id=mutation_id,
                    source=source,
                    mutation_kind=error_code,
                    expected_error_code=error_code,
                    expected_error_path=path,
                    description=description,
                    before_snippet=before,
                    after_snippet=after,
                    problem=problem,
                )
            )
    return mutations


def _path_matches(expected: str, actual: Any) -> bool:
    if not isinstance(actual, str) or not actual:
        return False
    return actual.startswith(expected) if expected.endswith("[") else actual == expected


def _compile_mutation(
    mutation: Mutation,
    mutated_path: str,
    invoke_fn: Callable[[dict[str, Any]], dict[str, Any]],
) -> dict[str, Any]:
    request = {
        "protocol_version": PROTOCOL_VERSION,
        "request_id": mutation.mutation_id,
        "command": "compile",
        "payload": {"problem": json.dumps(mutation.problem, ensure_ascii=False)},
    }
    base = {
        "mutation_id": mutation.mutation_id,
        "mutated_problem_path": mutated_path,
        "source_problem_id": mutation.source.problem_id,
        "mutation_kind": mutation.mutation_kind,
        "expected_error_code": mutation.expected_error_code,
    }
    try:
        response = invoke_fn(request)
    except Exception as exc:
        return {
            **base,
            "actual_protocol_kind": None,
            "actual_error_code": None,
            "actual_error_path": None,
            "actual_error_message": str(exc),
            "status": "protocol_error",
        }
    if (
        not isinstance(response, dict)
        or response.get("protocol_version") != PROTOCOL_VERSION
        or response.get("request_id") != mutation.mutation_id
        or not isinstance(response.get("result"), dict)
    ):
        return {
            **base,
            "actual_protocol_kind": None,
            "actual_error_code": None,
            "actual_error_path": None,
            "actual_error_message": "malformed or mismatched verifier response",
            "status": "protocol_error",
        }
    result = response["result"]
    kind = result.get("kind")
    code = result.get("error_code")
    path = result.get("error_path")
    message = result.get("message")
    if kind == "COMPILED":
        status = "unexpected_compile"
    elif kind != "STATIC_ERROR" or not isinstance(code, str) or not isinstance(message, str):
        status = "protocol_error"
    elif code != mutation.expected_error_code:
        status = "wrong_error_code"
    elif not _path_matches(mutation.expected_error_path, path):
        status = "missing_error_path"
    else:
        status = "expected_rejection"
    return {
        **base,
        "actual_protocol_kind": kind if isinstance(kind, str) else None,
        "actual_error_code": code if isinstance(code, str) else None,
        "actual_error_path": path if isinstance(path, str) else None,
        "actual_error_message": message if isinstance(message, str) else None,
        "status": status,
    }


def _default_invoke(repo_root: Path) -> Callable[[dict[str, Any]], dict[str, Any]]:
    lake = shutil.which("lake")
    if lake is None:
        raise RuntimeError("lake is required to build the Stage 2 compiler")
    subprocess.run([lake, "build", "sparse-ir-lean"], cwd=repo_root, check=True)
    executable = repo_root / ".lake/build/bin/sparse-ir-lean"
    if not executable.is_file():
        raise RuntimeError(f"Lean compiler executable was not built: {executable}")
    return partial(invoke, executable=executable)


def _mutation_row(mutation: Mutation, mutated_path: str) -> dict[str, Any]:
    return {
        "mutation_id": mutation.mutation_id,
        "source_problem_id": mutation.source.problem_id,
        "source_external_id": mutation.source.external_id,
        "source_grid": mutation.source.grid,
        "source_problem_path": mutation.source.path,
        "mutated_problem_path": mutated_path,
        "mutation_kind": mutation.mutation_kind,
        "expected_error_code": mutation.expected_error_code,
        "expected_error_path_prefix_or_exact": mutation.expected_error_path,
        "description": mutation.description,
        "before_snippet": mutation.before_snippet,
        "after_snippet": mutation.after_snippet,
    }


def _examples(mutations: list[dict[str, Any]], results: list[dict[str, Any]]) -> str:
    results_by_id = {row["mutation_id"]: row for row in results}
    lines = ["# Stage 2 Gate B mutation examples", ""]
    for error_code in REQUIRED_ERROR_CODES:
        mutation = next((row for row in mutations if row["mutation_kind"] == error_code), None)
        if mutation is None:
            continue
        result = results_by_id.get(mutation["mutation_id"], {})
        lines.extend(
            [
                f"## `{error_code}`",
                "",
                f"- Source problem: `{mutation['source_problem_id']}`",
                f"- Mutation: {mutation['description']}",
                f"- Expected error code: `{mutation['expected_error_code']}`",
                f"- Actual error code: `{result.get('actual_error_code')}`",
                f"- Actual error path: `{result.get('actual_error_path')}`",
                f"- Before: `{mutation['before_snippet']}`",
                f"- After: `{mutation['after_snippet']}`",
                "",
            ]
        )
    return "\n".join(lines)


def _summary(command: str, manifest: dict[str, Any]) -> str:
    lines = [
        "# Stage 2 Gate B: static mutation rejections",
        "",
        f"- Exact command run: `{command}`",
        f"- Status: **{manifest['status'].upper()}**",
        f"- Total source problems used: {manifest['total_source_problems_used']}",
        f"- Total mutations generated: {manifest['total_mutations_generated']}",
        f"- Total rejected: {manifest['total_rejected']}",
        "",
        "## Error-code coverage",
        "",
        "| Error code | Mutations |",
        "|---|---:|",
    ]
    lines.extend(
        f"| `{code}` | {manifest['error_code_coverage'].get(code, 0)} |"
        for code in REQUIRED_ERROR_CODES
    )
    lines.extend(["", "## Grid coverage", "", "| Grid | Mutations |", "|---|---:|"])
    lines.extend(
        f"| `{grid}` | {count} |" for grid, count in manifest["grid_coverage"].items()
    )
    lines.extend(
        [
            "",
            "## Artifacts",
            "",
            "- `eval/gates/stage2_gate_b_mutation_rejections/manifest.json`",
            "- `eval/gates/stage2_gate_b_mutation_rejections/mutations.jsonl`",
            "- `eval/gates/stage2_gate_b_mutation_rejections/results.jsonl`",
            "- `eval/gates/stage2_gate_b_mutation_rejections/mutation_examples.md`",
            "",
            "## Rerun Gate B",
            "",
            f"```bash\n{command}\n```",
            "",
        ]
    )
    return "\n".join(lines)


def run_gate(
    repo_root: Path,
    gate_a_dir: Path,
    output_dir: Path,
    command: str,
    *,
    invoke_fn: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    source_problems: list[SourceProblem] | None = None,
) -> tuple[int, dict[str, Any]]:
    repo_root = repo_root.resolve()
    gate_a_dir = gate_a_dir.resolve()
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    mutated_dir = output_dir / "mutated_problems"
    if mutated_dir.exists():
        shutil.rmtree(mutated_dir)
    mutated_dir.mkdir()
    failures: list[dict[str, Any]] = []

    try:
        problems = source_problems if source_problems is not None else load_gate_a_problems(repo_root, gate_a_dir)
        mutations = generate_mutations(problems)
    except Exception as exc:
        problems, mutations = [], []
        failures.append({"error_code": "gate_a_input_error", "message": str(exc)})

    coverage = {code: sum(item.expected_error_code == code for item in mutations) for code in REQUIRED_ERROR_CODES}
    for code, count in coverage.items():
        if count == 0:
            failures.append({"error_code": "missing_mutation_category", "mutation_kind": code})
        elif len(problems) >= 3 and count < 3:
            failures.append(
                {"error_code": "insufficient_mutation_coverage", "mutation_kind": code, "count": count}
            )

    if invoke_fn is None and mutations:
        try:
            invoke_fn = _default_invoke(repo_root)
        except Exception as exc:
            failures.append({"error_code": "verifier_unavailable", "message": str(exc)})

    mutation_rows: list[dict[str, Any]] = []
    result_rows: list[dict[str, Any]] = []
    for mutation in mutations:
        target = mutated_dir / f"{mutation.mutation_id}.problem.json"
        target.write_text(
            json.dumps(mutation.problem, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        display_path = _display(target, repo_root)
        mutation_rows.append(_mutation_row(mutation, display_path))
        if invoke_fn is not None:
            result_rows.append(_compile_mutation(mutation, display_path, invoke_fn))

    failures.extend(row for row in result_rows if row["status"] != "expected_rejection")
    unexpected = sum(row["status"] == "unexpected_compile" for row in result_rows)
    wrong = sum(
        row["actual_protocol_kind"] == "STATIC_ERROR"
        and row["actual_error_code"] != row["expected_error_code"]
        for row in result_rows
    )
    mutations_by_id = {mutation.mutation_id: mutation for mutation in mutations}
    missing_path = sum(
        row["actual_protocol_kind"] == "STATIC_ERROR"
        and not _path_matches(
            mutations_by_id[row["mutation_id"]].expected_error_path,
            row["actual_error_path"],
        )
        for row in result_rows
    )
    rejected = sum(row["actual_protocol_kind"] == "STATIC_ERROR" for row in result_rows)
    grid_coverage = {
        grid: sum(mutation.source.grid == grid for mutation in mutations)
        for grid in sorted({mutation.source.grid for mutation in mutations})
    }
    for grid in TARGET_GRIDS:
        if any(problem.grid == grid for problem in problems) and grid_coverage.get(grid, 0) == 0:
            failures.append({"error_code": "missing_grid_coverage", "grid": grid})
    source_ids = {mutation.source.problem_id for mutation in mutations}
    passed = (
        bool(mutations)
        and len(result_rows) == len(mutations)
        and rejected == len(mutations)
        and unexpected == 0
        and wrong == 0
        and missing_path == 0
        and not failures
    )
    manifest = {
        "gate": "stage2_gate_b_mutation_rejections",
        "status": "pass" if passed else "fail",
        "total_source_problems_used": len(source_ids),
        "total_mutations_generated": len(mutations),
        "total_rejected": rejected,
        "total_unexpected_compiled": unexpected,
        "total_wrong_error_code": wrong,
        "total_missing_error_path": missing_path,
        "error_code_coverage": coverage,
        "grid_coverage": grid_coverage,
        "failures": failures,
    }
    _write_jsonl(output_dir / "mutations.jsonl", mutation_rows)
    _write_jsonl(output_dir / "results.jsonl", result_rows)
    (output_dir / "mutation_examples.md").write_text(
        _examples(mutation_rows, result_rows), encoding="utf-8"
    )
    (output_dir / "summary.md").write_text(_summary(command, manifest), encoding="utf-8")
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return (0 if passed else 1), manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gate-a-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    gate_a_dir = args.gate_a_dir if args.gate_a_dir.is_absolute() else repo_root / args.gate_a_dir
    output_dir = args.output if args.output.is_absolute() else repo_root / args.output
    command = shlex.join(
        ["uv", "run", "python", "scripts/stage2_gate_b_mutation_rejections.py", *sys.argv[1:]]
    )
    exit_code, manifest = run_gate(repo_root, gate_a_dir, output_dir, command)
    print(
        f"Stage 2 Gate B: {manifest['status'].upper()} "
        f"({manifest['total_rejected']}/{manifest['total_mutations_generated']} rejected)"
    )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
