#!/usr/bin/env python3
"""Ingest and compile the full pinned ZebraLogicBench eval fixture set."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any

from run_lean_verifier import invoke
from sparseir_harness.zebralogic_ingest import (
    DATASET_ID,
    UPSTREAM_URL,
    IngestionError,
    SourceRecord,
    convert_source_record,
    file_sha256,
    load_official_source,
)


PROTOCOL_VERSION = "0.1.0"
MINIMUM_FULL_GATE_PROBLEMS = 4
FIXTURE_ROOT_NAMES = {
    "data",
    "dataset",
    "datasets",
    "eval",
    "fixture",
    "fixtures",
    "problem",
    "problems",
    "test",
    "tests",
    "vendor",
}
SKIPPED_DIRS = {
    ".git": "Git metadata",
    ".lake": "Lean build cache",
    ".pytest_cache": "pytest cache",
    ".ruff_cache": "Ruff cache",
    ".venv": "Python virtual environment",
    "__pycache__": "Python bytecode cache",
    "agent_output": "generated agent output",
    "agent_outputs": "generated agent output",
    "artifacts": "generated run artifacts",
    "node_modules": "dependency cache",
    "output": "generated run output",
    "outputs": "generated run output",
    "run_artifacts": "generated run artifacts",
    "runs": "generated run artifacts",
    "stage_reports": "generated stage reports",
    "venv": "Python virtual environment",
}
SKIPPED_RELATIVE_DIRS = {Path("eval/gates"): "generated gate artifacts"}


@dataclass(frozen=True)
class Discovery:
    fixtures: list[Path]
    roots_scanned: list[str]
    skipped: list[tuple[str, str]]


@dataclass(frozen=True)
class IngestedProblem:
    record: SourceRecord
    problem: dict[str, Any]
    path: Path


def _relative_or_absolute(path: Path, repo_root: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _skip_reason(path: Path, repo_root: Path) -> str | None:
    relative = path.relative_to(repo_root)
    if relative in SKIPPED_RELATIVE_DIRS:
        return SKIPPED_RELATIVE_DIRS[relative]
    return SKIPPED_DIRS.get(path.name)


def _walk_directories(repo_root: Path) -> tuple[list[Path], list[tuple[str, str]]]:
    directories: list[Path] = []
    skipped: set[tuple[str, str]] = set()
    for current, dirnames, _filenames in os.walk(repo_root, topdown=True):
        current_path = Path(current)
        kept: list[str] = []
        for dirname in sorted(dirnames):
            child = current_path / dirname
            reason = _skip_reason(child, repo_root)
            if reason is None:
                kept.append(dirname)
                directories.append(child)
            else:
                skipped.add((child.relative_to(repo_root).as_posix(), reason))
        dirnames[:] = kept
    return directories, sorted(skipped)


def discover_problem_fixtures(repo_root: Path) -> Discovery:
    """Find converted fixtures below test/data/eval-like roots, excluding generated trees."""
    repo_root = repo_root.resolve()
    directories, skipped = _walk_directories(repo_root)
    candidates = sorted(
        (path for path in directories if path.name.lower() in FIXTURE_ROOT_NAMES),
        key=lambda path: (len(path.parts), path.as_posix()),
    )
    roots: list[Path] = []
    for candidate in candidates:
        if not any(candidate.is_relative_to(root) for root in roots):
            roots.append(candidate)

    fixtures: set[Path] = set()
    for fixture_root in roots:
        for current, dirnames, filenames in os.walk(fixture_root, topdown=True):
            current_path = Path(current)
            kept: list[str] = []
            for dirname in sorted(dirnames):
                child = current_path / dirname
                reason = _skip_reason(child, repo_root)
                if reason is None:
                    kept.append(dirname)
                else:
                    skipped.append((child.relative_to(repo_root).as_posix(), reason))
            dirnames[:] = kept
            for filename in filenames:
                if filename.endswith(".problem.json"):
                    fixtures.add(current_path / filename)
    return Discovery(
        fixtures=sorted(fixtures, key=lambda path: path.relative_to(repo_root).as_posix()),
        roots_scanned=sorted(path.relative_to(repo_root).as_posix() for path in roots),
        skipped=sorted(set(skipped)),
    )


def _source_manifest_row(
    record: SourceRecord,
    ingested_path: str,
    status: str,
    skip_reason: str | None,
) -> dict[str, Any]:
    return {
        "problem_id": record.problem_id,
        "dataset": DATASET_ID,
        "external_id": record.external_id,
        "split": record.split,
        "grid": record.grid,
        "source_file": record.source_file,
        "source_row_index": record.source_row_index,
        "source_record_id": record.source_record_id,
        "source_sha256": record.source_sha256,
        "source_file_sha256": record.source_file_sha256,
        "upstream_url": record.upstream_url,
        "ingested_problem_path": ingested_path,
        "status": status,
        "skip_reason": skip_reason,
    }


def _record_from_problem(path: Path, repo_root: Path) -> tuple[SourceRecord, dict[str, Any]]:
    raw_bytes = path.read_bytes()
    problem = json.loads(raw_bytes)
    if not isinstance(problem, dict):
        raise IngestionError("converted fixture must be a JSON object")
    source = problem.get("source")
    if not isinstance(source, dict) or source.get("dataset") != DATASET_ID:
        raise IngestionError("converted fixture is not a ZebraLogic problem")
    problem_id = problem.get("id")
    external_id = source.get("external_id")
    split = source.get("split")
    grid = source.get("grid")
    if not all(isinstance(value, str) and value for value in (problem_id, external_id, split, grid)):
        raise IngestionError("converted fixture has incomplete source provenance")
    digest = hashlib.sha256(raw_bytes).hexdigest()
    return (
        SourceRecord(
            raw=problem,
            problem_id=problem_id,
            external_id=external_id,
            split=split,
            grid=grid,
            source_file=path.relative_to(repo_root).as_posix(),
            source_row_index=None,
            source_record_id=external_id,
            source_sha256=digest,
            source_file_sha256=digest,
            upstream_url=UPSTREAM_URL,
        ),
        problem,
    )


def _load_bundled_source_copies(repo_root: Path) -> tuple[list[SourceRecord], list[str]]:
    root = repo_root / "src/sparseir_harness/data/zebra"
    manifest_path = root / "manifest.json"
    if not manifest_path.is_file():
        return [], []
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    source = manifest.get("source", {})
    upstream_url = source.get("url") if isinstance(source.get("url"), str) else UPSTREAM_URL
    records: list[SourceRecord] = []
    for entry in manifest.get("records", []):
        path = root / entry["path"]
        raw = json.loads(path.read_text(encoding="utf-8"))
        external_id = entry["external_id"]
        digest = file_sha256(path)
        records.append(
            SourceRecord(
                raw=raw,
                problem_id=f"zl_{external_id}",
                external_id=external_id,
                split=entry["split"],
                grid=entry["grid"],
                source_file=path.relative_to(repo_root).as_posix(),
                source_row_index=None,
                source_record_id=external_id,
                source_sha256=digest,
                source_file_sha256=digest,
                upstream_url=upstream_url,
            )
        )
    return records, [root.relative_to(repo_root).as_posix()]


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as output:
        for row in rows:
            output.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _failure_row(
    ingested: IngestedProblem,
    protocol_kind: str,
    error_code: str,
    error_path: str | None,
    error_message: str,
) -> dict[str, Any]:
    source = ingested.problem["source"]
    return {
        "path": ingested.path.as_posix(),
        "problem_id": ingested.record.problem_id,
        "external_id": source["external_id"],
        "split": source["split"],
        "grid": source["grid"],
        "status": "failed",
        "protocol_kind": protocol_kind,
        "error_code": error_code,
        "error_path": error_path,
        "error_message": error_message,
    }


def compile_problem(
    ingested: IngestedProblem,
    invoke_fn: Callable[[dict[str, Any]], dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    request_id = f"stage2-gate-a:{ingested.record.external_id}"
    request = {
        "protocol_version": PROTOCOL_VERSION,
        "request_id": request_id,
        "command": "compile_view",
        "payload": {"problem": json.dumps(ingested.problem, ensure_ascii=False)},
    }
    try:
        response = invoke_fn(request)
    except Exception as exc:
        return _failure_row(ingested, "", "verifier_error", None, str(exc)), None
    if not isinstance(response, dict) or response.get("protocol_version") != PROTOCOL_VERSION:
        return _failure_row(
            ingested, "", "invalid_protocol", None, "response envelope is malformed"
        ), None
    if response.get("request_id") != request_id or not isinstance(response.get("result"), dict):
        return _failure_row(
            ingested, "", "invalid_protocol", None, "response does not match request"
        ), None
    result = response["result"]
    kind = result.get("kind")
    protocol_kind = kind if isinstance(kind, str) else ""
    if kind == "STATIC_ERROR":
        code = result.get("error_code")
        path = result.get("error_path")
        message = result.get("message")
        if (
            not isinstance(code, str)
            or not code
            or (path is not None and not isinstance(path, str))
            or not isinstance(message, str)
        ):
            return _failure_row(
                ingested, protocol_kind, "invalid_protocol", None, "malformed STATIC_ERROR"
            ), None
        return _failure_row(ingested, protocol_kind, code, path, message), None
    if kind != "COMPILED":
        return _failure_row(
            ingested,
            protocol_kind,
            "unexpected_protocol_kind",
            None,
            f"expected COMPILED, received {protocol_kind or 'an invalid result kind'}",
        ), None

    compiled = result.get("compiled")
    required_types = {
        "problem_id": str,
        "houses": int,
        "categories": int,
        "compiled_categories": list,
        "compiled_clues": list,
    }
    if not isinstance(compiled, dict) or any(
        not isinstance(compiled.get(field), expected) for field, expected in required_types.items()
    ):
        return _failure_row(
            ingested, protocol_kind, "invalid_protocol", None, "COMPILED view is malformed"
        ), None
    if compiled["problem_id"] != ingested.record.problem_id:
        return _failure_row(
            ingested, protocol_kind, "invalid_protocol", None, "compiled problem_id mismatch"
        ), None
    result_row = {
        "path": ingested.path.as_posix(),
        "problem_id": ingested.record.problem_id,
        "external_id": ingested.record.external_id,
        "split": ingested.record.split,
        "grid": ingested.record.grid,
        "status": "compiled",
        "protocol_kind": "COMPILED",
        "error_code": None,
        "error_path": None,
        "error_message": None,
    }
    compiled_row = {
        "problem_id": ingested.record.problem_id,
        "external_id": ingested.record.external_id,
        "grid": ingested.record.grid,
        "houses": compiled["houses"],
        "categories": compiled["categories"],
        "compiled_categories": compiled["compiled_categories"],
        "compiled_clues": compiled["compiled_clues"],
        "source_problem_path": ingested.path.as_posix(),
        "source_sha256": ingested.record.source_sha256,
    }
    return result_row, compiled_row


def _raw_index(ingested: list[IngestedProblem]) -> str:
    lines = [
        "# Raw ingested ZebraLogic problems",
        "",
        "| Problem ID | Grid | Source file | Ingested problem | Clue examples |",
        "|---|---:|---|---|---|",
    ]
    for item in ingested:
        examples = ", ".join(
            f"{clue['id']}:{clue['type']}" for clue in item.problem["clues"][:3]
        )
        lines.append(
            f"| `{item.record.problem_id}` | {item.record.grid} | "
            f"`{item.record.source_file}` | `{item.path.as_posix()}` | {examples} |"
        )
    return "\n".join(lines) + "\n"


def _compiled_index(compiled_rows: list[dict[str, Any]]) -> str:
    lines = [
        "# Lean-compiled ZebraLogic problems",
        "",
        "| Problem ID | Grid | Houses | Categories | Clues | Compiled clue examples |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for row in compiled_rows:
        clues = row["compiled_clues"]
        examples = ", ".join(f"{clue['id']}:{clue['type']}" for clue in clues[:3])
        lines.append(
            f"| `{row['problem_id']}` | {row['grid']} | {row['houses']} | "
            f"{row['categories']} | {len(clues)} | {examples} |"
        )
    return "\n".join(lines) + "\n"


def _summary(command: str, manifest: dict[str, Any]) -> str:
    coverage = (
        "full eval-intended coverage"
        if manifest["status"] == "pass"
        else "only smoke/incomplete coverage"
    )
    def roots(values: list[str]) -> str:
        return ", ".join(f"`{value}`" for value in values) or "(none)"

    return "\n".join(
        [
            "# Stage 2 Gate A: full ZebraLogic eval compilation",
            "",
            f"- Status: **{manifest['status'].upper()}**",
            f"- Coverage: **{coverage}**",
            f"- Exact command run: `{command}`",
            f"- Total source records seen: {manifest['total_source_records_seen']}",
            f"- Total ingested: {manifest['total_ingested']}",
            f"- Total compiled: {manifest['total_compiled']}",
            f"- Total failed: {manifest['total_failed']}",
            f"- Total skipped: {manifest['total_skipped']}",
            f"- Source roots scanned: {roots(manifest['source_roots_scanned'])}",
            f"- Fixture roots scanned: {roots(manifest['fixture_roots_scanned'])}",
            "- Raw source manifest: `eval/gates/stage2_gate_a_compile_all/source_manifest.jsonl`",
            "- Compiled manifest: `eval/gates/stage2_gate_a_compile_all/compiled_problems.jsonl`",
            "",
            "## Rerun Gate A",
            "",
            f"```bash\n{command}\n```",
            "",
        ]
    )


def _default_invoke(repo_root: Path) -> Callable[[dict[str, Any]], dict[str, Any]]:
    lake = shutil.which("lake")
    if lake is None:
        raise RuntimeError("lake is required to build the Stage 2 compiler")
    subprocess.run([lake, "build", "sparse-ir-lean"], cwd=repo_root, check=True)
    executable = repo_root / ".lake/build/bin/sparse-ir-lean"
    if not executable.is_file():
        raise RuntimeError(f"Lean compiler executable was not built: {executable}")
    return partial(invoke, executable=executable)


def run_gate(
    repo_root: Path,
    output_dir: Path,
    command: str,
    invoke_fn: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    canonical_records: list[SourceRecord] | None = None,
    source_roots: list[str] | None = None,
) -> tuple[int, dict[str, Any]]:
    repo_root = repo_root.resolve()
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    ingested_dir = output_dir / "ingested_problems"
    if ingested_dir.exists():
        shutil.rmtree(ingested_dir)
    ingested_dir.mkdir()

    discovery = discover_problem_fixtures(repo_root)
    failures: list[dict[str, Any]] = []
    skips: list[dict[str, Any]] = []
    source_rows: list[dict[str, Any]] = []
    canonical: dict[tuple[str, str, str, str], tuple[SourceRecord, dict[str, Any]]] = {}

    if canonical_records is None:
        try:
            canonical_records, official_roots = load_official_source(repo_root)
        except Exception as exc:
            canonical_records, official_roots = [], []
            failures.append(
                {
                    "error_code": "source_unavailable",
                    "error_path": str(repo_root / "data/zebralogic"),
                    "error_message": str(exc),
                }
            )
        source_roots = sorted(set((source_roots or []) + official_roots))
    else:
        source_roots = source_roots or []

    for record in canonical_records:
        try:
            problem = convert_source_record(record)
        except Exception as exc:
            reason = f"ingestion failed: {exc}"
            source_rows.append(_source_manifest_row(record, "", "skipped", reason))
            failure = {
                "problem_id": record.problem_id,
                "external_id": record.external_id,
                "error_code": "ingestion_error",
                "error_path": record.source_file,
                "error_message": str(exc),
            }
            failures.append(failure)
            skips.append(failure)
            continue
        if record.key in canonical:
            reason = f"duplicate stable key; canonical source is {canonical[record.key][0].source_file}"
            source_rows.append(_source_manifest_row(record, "", "skipped", reason))
            skip = {"source_file": record.source_file, "reason": reason}
            skips.append(skip)
            continue
        canonical[record.key] = (record, problem)

    bundled_records: list[SourceRecord] = []
    if canonical_records and (repo_root / "src/sparseir_harness/data/zebra/manifest.json").is_file():
        try:
            bundled_records, bundled_roots = _load_bundled_source_copies(repo_root)
            source_roots = sorted(set(source_roots + bundled_roots))
        except Exception as exc:
            failures.append(
                {
                    "error_code": "source_parse_error",
                    "error_path": "src/sparseir_harness/data/zebra/manifest.json",
                    "error_message": str(exc),
                }
            )
    fixture_records: list[tuple[SourceRecord, dict[str, Any]]] = []
    for fixture in discovery.fixtures:
        try:
            fixture_records.append(_record_from_problem(fixture, repo_root))
        except Exception as exc:
            failures.append(
                {
                    "error_code": "fixture_parse_error",
                    "error_path": fixture.relative_to(repo_root).as_posix(),
                    "error_message": str(exc),
                }
            )

    duplicate_sources: list[tuple[SourceRecord, dict[str, Any] | None]] = [
        (record, None) for record in bundled_records
    ] + fixture_records
    for record, ready_problem in duplicate_sources:
        if record.key in canonical:
            canonical_record = canonical[record.key][0]
            ingested_name = f"{record.external_id}.problem.json"
            ingested_path = _relative_or_absolute(ingested_dir / ingested_name, repo_root)
            reason = f"duplicate stable key; canonical source is {canonical_record.source_file}"
            source_rows.append(_source_manifest_row(record, ingested_path, "skipped", reason))
            skips.append({"source_file": record.source_file, "reason": reason})
            continue
        try:
            problem = ready_problem if ready_problem is not None else convert_source_record(record)
        except Exception as exc:
            reason = f"ingestion failed: {exc}"
            source_rows.append(_source_manifest_row(record, "", "skipped", reason))
            failure = {
                "problem_id": record.problem_id,
                "external_id": record.external_id,
                "error_code": "ingestion_error",
                "error_path": record.source_file,
                "error_message": str(exc),
            }
            failures.append(failure)
            skips.append(failure)
            continue
        canonical[record.key] = (record, problem)

    ingested: list[IngestedProblem] = []
    for record, problem in sorted(canonical.values(), key=lambda item: item[0].external_id):
        target = ingested_dir / f"{record.external_id}.problem.json"
        target.write_text(
            json.dumps(problem, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        display_path = Path(_relative_or_absolute(target, repo_root))
        ingested.append(IngestedProblem(record=record, problem=problem, path=display_path))
        source_rows.append(
            _source_manifest_row(record, display_path.as_posix(), "ingested", None)
        )

    if invoke_fn is None and ingested:
        try:
            invoke_fn = _default_invoke(repo_root)
        except Exception as exc:
            failures.append(
                {
                    "error_code": "verifier_unavailable",
                    "error_path": ".lake/build/bin/sparse-ir-lean",
                    "error_message": str(exc),
                }
            )
    results: list[dict[str, Any]] = []
    compiled_rows: list[dict[str, Any]] = []
    if invoke_fn is not None:
        for item in ingested:
            result, compiled = compile_problem(item, invoke_fn)
            results.append(result)
            if compiled is None:
                failures.append(result)
            else:
                compiled_rows.append(compiled)

    if not ingested:
        failures.append(
            {
                "error_code": "no_problems_discovered",
                "error_path": None,
                "error_message": "zero ZebraLogic problems were available for Gate A",
            }
        )
    elif len(ingested) < MINIMUM_FULL_GATE_PROBLEMS:
        failures.append(
            {
                "error_code": "smoke_coverage_only",
                "error_path": None,
                "error_message": (
                    f"only {len(ingested)} unique problems are available; this is smoke coverage "
                    "and not enough for Stage 2 Gate A"
                ),
            }
        )

    total_compiled = len(compiled_rows)
    passed = (
        len(ingested) >= MINIMUM_FULL_GATE_PROBLEMS
        and total_compiled == len(ingested)
        and not failures
    )
    manifest = {
        "gate": "stage2_gate_a_compile_all",
        "status": "pass" if passed else "fail",
        "total_source_records_seen": len(source_rows),
        "total_ingested": len(ingested),
        "total_compiled": total_compiled,
        "total_failed": len(failures),
        "total_skipped": sum(row["status"] == "skipped" for row in source_rows),
        "total_duplicates": sum("duplicate stable key" in (row["skip_reason"] or "") for row in source_rows),
        "fixture_roots_scanned": discovery.roots_scanned,
        "source_roots_scanned": sorted(set(source_roots)),
        "failures": failures,
        "skips": skips,
    }

    source_rows.sort(key=lambda row: (row["external_id"], row["status"], row["source_file"]))
    _write_jsonl(output_dir / "source_manifest.jsonl", source_rows)
    _write_jsonl(output_dir / "results.jsonl", results)
    _write_jsonl(output_dir / "compiled_problems.jsonl", compiled_rows)
    (output_dir / "raw_problem_index.md").write_text(_raw_index(ingested), encoding="utf-8")
    (output_dir / "compiled_problem_index.md").write_text(
        _compiled_index(compiled_rows), encoding="utf-8"
    )
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (output_dir / "summary.md").write_text(_summary(command, manifest), encoding="utf-8")
    return (0 if passed else 1), manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path, help="Gate A artifact directory")
    args = parser.parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    output_dir = args.output if args.output.is_absolute() else repo_root / args.output
    command = shlex.join(
        ["uv", "run", "python", "scripts/stage2_gate_a_compile_all.py", *sys.argv[1:]]
    )
    exit_code, manifest = run_gate(repo_root, output_dir, command)
    print(
        f"Stage 2 Gate A: {manifest['status'].upper()} "
        f"({manifest['total_compiled']}/{manifest['total_ingested']} compiled; "
        f"{manifest['total_source_records_seen']} source records seen)"
    )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
