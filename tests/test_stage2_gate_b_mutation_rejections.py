from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
GATE_A = ROOT / "eval/gates/stage2_gate_a_compile_all"
SCRIPT = ROOT / "scripts/stage2_gate_b_mutation_rejections.py"
sys.path.insert(0, str(SCRIPT.parent))
SPEC = importlib.util.spec_from_file_location("stage2_gate_b_mutation_rejections", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
gate_b = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = gate_b
SPEC.loader.exec_module(gate_b)
ALL_SOURCES = gate_b.load_gate_a_problems(ROOT, GATE_A)
SMALL_SOURCES = [
    next(problem for problem in ALL_SOURCES if problem.external_id == f"lgp-test-{grid}-0")
    for grid in ("2x2", "4x4", "6x6")
]


def _mutation_lookup() -> dict[str, Any]:
    return {
        mutation.mutation_id: mutation for mutation in gate_b.generate_mutations(SMALL_SOURCES)
    }


def _response(request: dict[str, Any], *, mode: str = "expected") -> dict[str, Any]:
    mutation = _mutation_lookup()[request["request_id"]]
    if mode == "compiled":
        result = {"kind": "COMPILED", "compiled": {"problem_id": mutation.source.problem_id}}
    else:
        expected_path = mutation.expected_error_path
        if expected_path.endswith("["):
            expected_path += "0]"
        result = {
            "kind": "STATIC_ERROR",
            "error_code": (
                "gate_b_wrong_code" if mode == "wrong" else mutation.expected_error_code
            ),
            "message": "deterministic test rejection",
        }
        if mode != "missing_path":
            result["error_path"] = expected_path
    return {
        "protocol_version": "0.1.0",
        "request_id": request["request_id"],
        "result": result,
    }


def _run(tmp_path: Path, mode: str = "expected") -> tuple[int, dict[str, Any], Path]:
    output = tmp_path / "gate-b"
    exit_code, manifest = gate_b.run_gate(
        ROOT,
        GATE_A,
        output,
        "gate-b-test",
        invoke_fn=lambda request: _response(request, mode=mode),
        source_problems=SMALL_SOURCES,
    )
    return exit_code, manifest, output


def test_every_required_mutation_category_is_generated_deterministically() -> None:
    first = gate_b.generate_mutations(SMALL_SOURCES)
    second = gate_b.generate_mutations(SMALL_SOURCES)

    assert len(first) == 27
    assert {mutation.expected_error_code for mutation in first} == set(
        gate_b.REQUIRED_ERROR_CODES
    )
    assert {
        code: sum(mutation.expected_error_code == code for mutation in first)
        for code in gate_b.REQUIRED_ERROR_CODES
    } == {code: 3 for code in gate_b.REQUIRED_ERROR_CODES}
    assert {mutation.source.grid for mutation in first} == {"2x2", "4x4", "6x6"}
    assert [mutation.mutation_id for mutation in first] == [
        mutation.mutation_id for mutation in second
    ]
    assert [mutation.problem for mutation in first] == [mutation.problem for mutation in second]


def test_expected_rejections_pass_and_write_all_artifacts(tmp_path: Path) -> None:
    exit_code, manifest, output = _run(tmp_path)
    mutations = [
        json.loads(line)
        for line in (output / "mutations.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    results = [
        json.loads(line)
        for line in (output / "results.jsonl").read_text(encoding="utf-8").splitlines()
    ]

    assert exit_code == 0
    assert manifest["status"] == "pass"
    assert manifest["total_rejected"] == manifest["total_mutations_generated"] == 27
    assert manifest["error_code_coverage"] == {
        code: 3 for code in gate_b.REQUIRED_ERROR_CODES
    }
    assert all(row["expected_error_code"] == row["mutation_kind"] for row in mutations)
    assert all(row["status"] == "expected_rejection" for row in results)
    assert {path.name for path in output.iterdir()} >= {
        "manifest.json",
        "mutations.jsonl",
        "results.jsonl",
        "mutation_examples.md",
        "summary.md",
        "mutated_problems",
    }
    assert len(list((output / "mutated_problems").glob("*.problem.json"))) == 27


def test_unexpected_compiled_result_fails_gate(tmp_path: Path) -> None:
    exit_code, manifest, output = _run(tmp_path, "compiled")

    assert exit_code == 1
    assert manifest["status"] == "fail"
    assert manifest["total_unexpected_compiled"] == 27
    assert "unexpected_compile" in (output / "results.jsonl").read_text(encoding="utf-8")


def test_wrong_error_code_fails_gate(tmp_path: Path) -> None:
    exit_code, manifest, output = _run(tmp_path, "wrong")

    assert exit_code == 1
    assert manifest["total_wrong_error_code"] == 27
    assert "wrong_error_code" in (output / "results.jsonl").read_text(encoding="utf-8")


def test_missing_error_path_fails_gate(tmp_path: Path) -> None:
    exit_code, manifest, output = _run(tmp_path, "missing_path")

    assert exit_code == 1
    assert manifest["total_missing_error_path"] == 27
    assert "missing_error_path" in (output / "results.jsonl").read_text(encoding="utf-8")
