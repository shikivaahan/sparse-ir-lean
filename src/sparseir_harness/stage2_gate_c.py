"""Stage 2 Gate C dataset, provider-output extraction, and artifact support.

The provider is untrusted. This module extracts, but never repairs, a JSON object
and sends every provider output through the Lean Stage 1/2 compile protocol.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PROTOCOL_VERSION = "0.1.0"
PROVIDER = "openrouter"
MODEL = "deepseek/deepseek-v4-flash"
GATE = "stage2_gate_c_provider_static"
DATASET_RELATIVE_PATH = "eval/datasets/stage2_gate_c_provider_static.jsonl"
GATE_RELATIVE_PATH = "eval/gates/stage2_gate_c_provider_static"
LOG_DIR_RELATIVE_PATH = "eval/logs/stage2_gate_c_provider_static"
REQUIRED_TASK_KINDS = (
    "valid_reemit_problem",
    "drop_required_field",
    "wrong_domain",
    "wrong_schema_version",
    "unknown_category",
    "unknown_value",
    "duplicate_clue_id",
    "bad_house_index",
    "category_size_mismatch",
    "freeform_convert_to_problem_json",
)
BASE_EXTERNAL_IDS = (
    "lgp-test-2x2-33",
    "lgp-test-4x4-27",
    "lgp-test-6x6-5",
)


@dataclass(frozen=True)
class Extraction:
    """A conservatively extracted provider JSON object."""

    status: str
    value: dict[str, Any] | None


def _json_object(text: str) -> dict[str, Any] | None:
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def extract_json_object(raw: str) -> Extraction:
    """Extract one JSON object without changing its contents."""
    exact = _json_object(raw)
    if exact is not None:
        return Extraction("exact_json", exact)

    for match in re.finditer(r"```(?:json)?\s*(.*?)```", raw, flags=re.IGNORECASE | re.DOTALL):
        fenced = _json_object(match.group(1).strip())
        if fenced is not None:
            return Extraction("fenced_json", fenced)

    decoder = json.JSONDecoder()
    for index, character in enumerate(raw):
        if character != "{":
            continue
        try:
            value, _end = decoder.raw_decode(raw[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return Extraction("embedded_json", value)
    return Extraction("not_json", None)


def _instruction(task_kind: str) -> tuple[str, str, str | None]:
    instructions = {
        "valid_reemit_problem": (
            "Re-emit the supplied problem exactly as one valid problem.json object.",
            "Lean should compile the re-emitted problem if no accidental changes are made.",
            None,
        ),
        "drop_required_field": (
            "Return the supplied problem after deleting the top-level size field.",
            "Lean should report a structural parse/schema diagnostic.",
            "parse_error",
        ),
        "wrong_domain": (
            "Return the supplied problem after changing domain to a non-zebra string.",
            "Lean should report the actual diagnostic for the wrong domain.",
            "parse_error",
        ),
        "wrong_schema_version": (
            "Return the supplied problem after changing schema_version to 999.0.",
            "Lean should report the actual diagnostic for the unsupported schema version.",
            "parse_error",
        ),
        "unknown_category": (
            "Return the supplied problem after changing one clue category reference to GhostCategory.",
            "Lean should report a static unknown-category diagnostic if the requested flaw is present.",
            "static_error",
        ),
        "unknown_value": (
            "Return the supplied problem after changing one clue value reference to GhostValue.",
            "Lean should report a static unknown-value diagnostic if the requested flaw is present.",
            "static_error",
        ),
        "duplicate_clue_id": (
            "Return the supplied problem after assigning the first clue id to a second clue too.",
            "Lean should report a static duplicate-clue-id diagnostic if the flaw is present.",
            "static_error",
        ),
        "bad_house_index": (
            "Return the supplied problem after making one clue house index 999. Preserve the clue shape.",
            "Lean should report a static house-bounds diagnostic if the requested flaw is present.",
            "static_error",
        ),
        "category_size_mismatch": (
            "Return the supplied problem after deleting one value from one category array.",
            "Lean should report a static category-size diagnostic if the requested flaw is present.",
            "static_error",
        ),
        "freeform_convert_to_problem_json": (
            "Convert the supplied Zebra artifact into your best canonical problem.json emission. "
            "Preserve its meaning and provenance, but handle the task as realistic free-form conversion.",
            "The untrusted emission may compile or receive a useful Lean parse/static diagnostic.",
            None,
        ),
    }
    return instructions[task_kind]


def _prompt(task_kind: str, problem: dict[str, Any]) -> tuple[str, str, str | None]:
    instruction, expected, family = _instruction(task_kind)
    source = json.dumps(problem, ensure_ascii=False, indent=2)
    prompt = (
        "You emit candidate Zebra problem.json documents for a static compiler evaluation.\n"
        "Output only one JSON object when possible: no explanation and no markdown fence.\n"
        "Do not solve the puzzle, produce a candidate solution, or discuss reasoning traces.\n\n"
        f"Task: {instruction}\n\n"
        "Source problem:\n"
        f"{source}\n"
    )
    return prompt, expected, family


def _load_gate_a_bases(repo_root: Path) -> list[tuple[dict[str, Any], str]]:
    source_manifest = (
        repo_root / "eval/gates/stage2_gate_a_compile_all/source_manifest.jsonl"
    )
    if not source_manifest.is_file():
        raise FileNotFoundError("Gate A source manifest is required to generate Gate C data")
    manifest_rows = [json.loads(line) for line in source_manifest.read_text().splitlines() if line]
    by_external_id = {
        row["external_id"]: row for row in manifest_rows if row.get("status") == "ingested"
    }
    bases: list[tuple[dict[str, Any], str]] = []
    for external_id in BASE_EXTERNAL_IDS:
        row = by_external_id.get(external_id)
        if row is None or row.get("status") != "ingested":
            raise ValueError(f"Gate A has no ingested base for {external_id}")
        relative_path = row["ingested_problem_path"]
        path = repo_root / relative_path
        if not path.is_file():
            raise FileNotFoundError(f"Gate A ingested problem is missing: {relative_path}")
        problem = json.loads(path.read_text(encoding="utf-8"))
        bases.append((problem, relative_path))
    return bases


def generate_dataset(repo_root: Path, destination: Path | None = None) -> list[dict[str, Any]]:
    """Generate the explicit 30-row Gate C dataset from Gate A outputs."""
    destination = destination or repo_root / DATASET_RELATIVE_PATH
    rows: list[dict[str, Any]] = []
    for problem, source_path in _load_gate_a_bases(repo_root):
        source = problem["source"]
        for task_kind in REQUIRED_TASK_KINDS:
            prompt, expected, family = _prompt(task_kind, problem)
            sample_id = f"gate-c-{source['grid']}-{task_kind}"
            rows.append(
                {
                    "sample_id": sample_id,
                    "source_problem_id": problem["id"],
                    "source_external_id": source["external_id"],
                    "source_grid": source["grid"],
                    "source_problem_path": source_path,
                    "task_kind": task_kind,
                    "prompt": prompt,
                    "expected_behavior": expected,
                    "target_error_family_or_null": family,
                    "metadata": {
                        "gate": GATE,
                        "source_dataset": source["dataset"],
                        "source_split": source["split"],
                        "provider_output_is_untrusted": True,
                        "requested_flaw_is_not_assumed": family is not None,
                    },
                }
            )
    destination.parent.mkdir(parents=True, exist_ok=True)
    _write_jsonl(destination, rows)
    return rows


def load_dataset(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def invoke_lean(request: dict[str, Any], repo_root: Path) -> dict[str, Any]:
    completed = subprocess.run(
        ["lake", "exe", "sparse-ir-lean"],
        cwd=repo_root,
        input=json.dumps(request),
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"Lean verifier exited with {completed.returncode}: {completed.stderr.strip()}"
        )
    try:
        response = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Lean verifier returned invalid JSON") from exc
    if not isinstance(response, dict):
        raise RuntimeError("Lean verifier response is not an object")
    return response


def classify_provider_output(
    sample: dict[str, Any],
    raw_output: str,
    invoke_fn: Callable[[dict[str, Any]], dict[str, Any]],
) -> tuple[Extraction, dict[str, Any]]:
    """Extract and classify one output, always consulting Lean Stage 1/2."""
    extraction = extract_json_object(raw_output)
    problem_text = (
        json.dumps(extraction.value, ensure_ascii=False)
        if extraction.value is not None
        else raw_output
    )
    request_id = f"stage2-gate-c:{sample['sample_id']}"
    request = {
        "protocol_version": PROTOCOL_VERSION,
        "request_id": request_id,
        "command": "compile",
        "payload": {"problem": problem_text},
    }
    base = {
        "sample_id": sample["sample_id"],
        "task_kind": sample["task_kind"],
        "source_problem_id": sample["source_problem_id"],
        "source_grid": sample["source_grid"],
        "provider_model": MODEL,
        "lean_protocol_kind": None,
        "lean_error_code": None,
        "lean_error_path": None,
        "lean_error_message": None,
        "compiled_problem_id_or_null": None,
    }
    try:
        response = invoke_fn(request)
    except Exception as exc:
        return extraction, {**base, "classification": "protocol_error", "lean_error_message": str(exc)}

    if (
        response.get("protocol_version") != PROTOCOL_VERSION
        or response.get("request_id") != request_id
        or not isinstance(response.get("result"), dict)
    ):
        return extraction, {
            **base,
            "classification": "protocol_error",
            "lean_error_message": "malformed or mismatched Lean response envelope",
        }
    result = response["result"]
    kind = result.get("kind")
    base["lean_protocol_kind"] = kind if isinstance(kind, str) else None
    if kind == "COMPILED":
        compiled = result.get("compiled")
        problem_id = compiled.get("problem_id") if isinstance(compiled, dict) else None
        if extraction.value is None or not isinstance(problem_id, str) or not problem_id:
            return extraction, {
                **base,
                "classification": "protocol_error",
                "lean_error_message": "malformed COMPILED response",
            }
        return extraction, {
            **base,
            "classification": "compiled",
            "compiled_problem_id_or_null": problem_id,
        }
    if kind != "STATIC_ERROR":
        return extraction, {
            **base,
            "classification": "protocol_error",
            "lean_error_message": f"unexpected Lean result kind: {kind!r}",
        }

    code = result.get("error_code")
    path = result.get("error_path")
    message = result.get("message")
    if (
        not isinstance(code, str)
        or not code
        or not isinstance(path, str)
        or not path
        or not isinstance(message, str)
        or not message
    ):
        return extraction, {
            **base,
            "classification": "protocol_error",
            "lean_error_message": "malformed STATIC_ERROR response",
        }
    if extraction.value is None:
        classification = "provider_output_not_json"
    elif code in {"invalid_json", "invalid_schema", "invalid_domain", "unsupported_schema_version"}:
        classification = "parse_error"
    else:
        classification = "static_error"
    return extraction, {
        **base,
        "lean_error_code": code,
        "lean_error_path": path,
        "lean_error_message": message,
        "classification": classification,
    }


def _write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as output:
        for row in rows:
            output.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _preview(value: str, limit: int = 240) -> str:
    compact = " ".join(value.split())
    return compact if len(compact) <= limit else compact[: limit - 1] + "…"


def _find_inspect_log(repo_root: Path) -> str | None:
    log_dir = repo_root / LOG_DIR_RELATIVE_PATH
    logs = sorted(log_dir.glob("*.eval"), key=lambda path: path.stat().st_mtime)
    return logs[-1].relative_to(repo_root).as_posix() if logs else None


def initialize_artifacts(repo_root: Path, dataset: list[dict[str, Any]]) -> None:
    gate_dir = repo_root / GATE_RELATIVE_PATH
    gate_dir.mkdir(parents=True, exist_ok=True)
    for directory in (gate_dir / "raw_outputs", gate_dir / "extracted_json"):
        if directory.exists():
            shutil.rmtree(directory)
        directory.mkdir()
    _write_jsonl(gate_dir / "provider_outputs.jsonl", [])
    _write_jsonl(gate_dir / "classifications.jsonl", [])
    write_dataset_index(gate_dir / "dataset_index.md", dataset)
    write_summary_and_manifest(repo_root, dataset, [], [])


def record_provider_result(
    repo_root: Path,
    dataset: list[dict[str, Any]],
    sample: dict[str, Any],
    raw_output: str,
    invoke_fn: Callable[[dict[str, Any]], dict[str, Any]],
) -> dict[str, Any]:
    gate_dir = repo_root / GATE_RELATIVE_PATH
    raw_relative = f"{GATE_RELATIVE_PATH}/raw_outputs/{sample['sample_id']}.txt"
    raw_path = repo_root / raw_relative
    raw_path.write_text(raw_output, encoding="utf-8")
    extraction, classification = classify_provider_output(sample, raw_output, invoke_fn)
    extracted_relative: str | None = None
    if extraction.value is not None:
        extracted_relative = (
            f"{GATE_RELATIVE_PATH}/extracted_json/{sample['sample_id']}.problem.json"
        )
        (repo_root / extracted_relative).write_text(
            json.dumps(extraction.value, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    provider_row = {
        "sample_id": sample["sample_id"],
        "task_kind": sample["task_kind"],
        "source_problem_id": sample["source_problem_id"],
        "source_grid": sample["source_grid"],
        "provider": PROVIDER,
        "model": MODEL,
        "raw_output_path": raw_relative,
        "raw_output_preview": _preview(raw_output),
        "extraction_status": extraction.status,
        "extracted_json_path": extracted_relative,
    }
    classification["raw_output_path"] = raw_relative
    classification["extracted_json_path_or_null"] = extracted_relative

    provider_path = gate_dir / "provider_outputs.jsonl"
    classification_path = gate_dir / "classifications.jsonl"
    provider_rows = load_dataset(provider_path) + [provider_row]
    classification_rows = load_dataset(classification_path) + [classification]
    provider_rows.sort(key=lambda row: row["sample_id"])
    classification_rows.sort(key=lambda row: row["sample_id"])
    _write_jsonl(provider_path, provider_rows)
    _write_jsonl(classification_path, classification_rows)
    write_summary_and_manifest(repo_root, dataset, provider_rows, classification_rows)
    return classification


def write_dataset_index(path: Path, dataset: list[dict[str, Any]]) -> None:
    lines = [
        "# Stage 2 Gate C dataset index",
        "",
        "The JSONL dataset is `eval/datasets/stage2_gate_c_provider_static.jsonl`.",
        "Provider outputs are untrusted; expected behavior never overrides Lean's result.",
        "",
        "| sample_id | task_kind | source_problem_id | grid | expected_behavior | prompt preview |",
        "|---|---|---|---:|---|---|",
    ]
    for row in dataset:
        preview = _preview(row["prompt"], 120).replace("|", "\\|")
        expected = row["expected_behavior"].replace("|", "\\|")
        lines.append(
            f"| {row['sample_id']} | {row['task_kind']} | {row['source_problem_id']} | "
            f"{row['source_grid']} | {expected} | {preview} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _coverage(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    return dict(sorted(Counter(row[key] for row in rows if row.get(key)).items()))


def write_summary_and_manifest(
    repo_root: Path,
    dataset: list[dict[str, Any]],
    provider_rows: list[dict[str, Any]],
    classification_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    gate_dir = repo_root / GATE_RELATIVE_PATH
    task_coverage = _coverage(provider_rows, "task_kind")
    classifications = _coverage(classification_rows, "classification")
    code_coverage = _coverage(classification_rows, "lean_error_code")
    inspect_log_path = _find_inspect_log(repo_root)
    diagnostics = [
        row
        for row in classification_rows
        if row.get("classification") in {"parse_error", "static_error", "provider_output_not_json"}
    ]
    diagnostics_useful = all(
        row.get("lean_error_code") and row.get("lean_error_path") and row.get("lean_error_message")
        for row in diagnostics
    )
    dataset_ids = {row["sample_id"] for row in dataset}
    provider_ids = {row["sample_id"] for row in provider_rows}
    classification_ids = {row["sample_id"] for row in classification_rows}
    complete = (
        len(provider_rows) == len(dataset) == len(classification_rows)
        and len(dataset) >= 30
        and provider_ids == dataset_ids == classification_ids
    )
    passed = (
        complete
        and set(REQUIRED_TASK_KINDS).issubset(task_coverage)
        and classifications.get("protocol_error", 0) == 0
        and diagnostics_useful
        and inspect_log_path is not None
    )
    manifest = {
        "gate": GATE,
        "status": "pass" if passed else "incomplete",
        "provider": PROVIDER,
        "model": MODEL,
        "total_samples": len(dataset),
        "total_provider_calls": len(provider_rows),
        "total_compiled": classifications.get("compiled", 0),
        "total_parse_error": classifications.get("parse_error", 0),
        "total_static_error": classifications.get("static_error", 0),
        "total_provider_output_not_json": classifications.get("provider_output_not_json", 0),
        "total_protocol_error": classifications.get("protocol_error", 0),
        "task_kind_coverage": task_coverage,
        "lean_error_code_coverage": code_coverage,
        "lean_error_path_present": sum(bool(row.get("lean_error_path")) for row in diagnostics),
        "inspect_log_path": inspect_log_path,
        "dataset_path": DATASET_RELATIVE_PATH,
    }
    (gate_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    run_command = (
        "set -a; source .env; set +a; export OPENAI_API_KEY=\"$OPENROUTER_API_KEY\"; "
        "export XDG_DATA_HOME=/tmp/sparseir-inspect-data; "
        "export TIKTOKEN_CACHE_DIR=/tmp/sparseir-tiktoken-cache; "
        ".venv/bin/inspect eval evals/stage2_gate_c_provider_static.py "
        "--model openai/deepseek/deepseek-v4-flash "
        "--model-base-url https://openrouter.ai/api/v1 "
        "--log-dir eval/logs/stage2_gate_c_provider_static --max-connections 4 "
        "--max-tokens 8192 --temperature 0 --max-retries 2 --timeout 180 --display plain"
    )
    viewer_command = (
        ".venv/bin/inspect view start --log-dir eval/logs/stage2_gate_c_provider_static"
    )
    examples = diagnostics[:3]
    lines = [
        "# Stage 2 Gate C provider-output static-error evaluation",
        "",
        f"- Gate C passed: **{'yes' if passed else 'no'}**",
        f"- Dataset path: `{DATASET_RELATIVE_PATH}`",
        f"- Inspect log path: `{inspect_log_path or 'pending'}`",
        f"- Total samples: {len(dataset)}",
        f"- Total provider calls: {len(provider_rows)}",
        "- Inspect score: `lean_compiles` (`C` = compiled, `I` = rejected; "
        "the explanation contains the Lean diagnostic)",
        f"- Task-kind coverage: `{json.dumps(task_coverage, sort_keys=True)}`",
        f"- Classification counts: `{json.dumps(classifications, sort_keys=True)}`",
        f"- Lean error-code coverage: `{json.dumps(code_coverage, sort_keys=True)}`",
        "",
        "## Exact commands",
        "",
        "```bash",
        run_command,
        "```",
        "",
        "```bash",
        viewer_command,
        "```",
        "",
        "## Example Lean diagnostics",
        "",
    ]
    if examples:
        for row in examples:
            lines.extend(
                [
                    f"- `{row['sample_id']}`: `{row['lean_error_code']}` at "
                    f"`{row['lean_error_path']}` — {row['lean_error_message']}",
                    f"  Raw provider output: `{row['raw_output_path']}`",
                ]
            )
    else:
        lines.append("- Pending provider results.")
    (gate_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return manifest
