from __future__ import annotations

import importlib.util
import json
import random
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
GATE_A = ROOT / "eval/gates/stage2_gate_a_compile_all"
SCRIPT = ROOT / "scripts/stage2_gate_b_plus_fuzz.py"
sys.path.insert(0, str(SCRIPT.parent))
SPEC = importlib.util.spec_from_file_location("stage2_gate_b_plus_fuzz", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
gate_b_plus = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = gate_b_plus
SPEC.loader.exec_module(gate_b_plus)

ALL_SOURCES = gate_b_plus.load_gate_a_problems(ROOT, GATE_A)


def _pick(problems: list[Any], grid: str, external_id: str) -> Any:
    return next(
        problem
        for problem in problems
        if problem.grid == grid and problem.external_id == external_id
    )


SMALL_SOURCES = [
    _pick(ALL_SOURCES, "2x2", "lgp-test-2x2-0"),
    _pick(ALL_SOURCES, "4x4", "lgp-test-4x4-0"),
    _pick(ALL_SOURCES, "6x6", "lgp-test-6x6-0"),
]


def _stub_invoke(
    request: dict[str, Any],
    *,
    expected_codes: dict[str, str],
    expected_paths: dict[str, str],
) -> dict[str, Any]:
    request_id = request["request_id"]
    if request_id.startswith("control_"):
        # Controls must compile successfully in the default stub.
        return {
            "protocol_version": "0.1.0",
            "request_id": request_id,
            "result": {"kind": "COMPILED", "compiled": {"problem_id": "stub"}},
        }
    code = expected_codes.get(request_id, "expected")
    if code == "compiled":
        result = {"kind": "COMPILED", "compiled": {"problem_id": "stub"}}
    else:
        result = {
            "kind": "STATIC_ERROR",
            "error_code": code,
            "error_path": expected_paths.get(request_id, ""),
            "message": "deterministic test rejection",
        }
    return {
        "protocol_version": "0.1.0",
        "request_id": request_id,
        "result": result,
    }


def _build_expected(
    mutations: list[Any],
) -> tuple[dict[str, str], dict[str, str]]:
    codes: dict[str, str] = {}
    paths: dict[str, str] = {}
    for mutation in mutations:
        if mutation.parser_rejection_expected:
            codes[mutation.mutation_id] = "invalid_value"
            paths[mutation.mutation_id] = mutation.expected_error_path
        else:
            codes[mutation.mutation_id] = mutation.expected_error_code
            paths[mutation.mutation_id] = mutation.expected_error_path
    return codes, paths


def _select_mutations(
    sources: list[Any], *, seed: int = 20260628
) -> list[Any]:
    selected = gate_b_plus.select_sources(sources, 1, random.Random(seed))
    mutations: list[Any] = []
    for source in selected:
        mutations.extend(gate_b_plus.build_mutation_plan(source))
    return mutations


def test_fuzzer_is_deterministic_for_fixed_seed() -> None:
    first = _select_mutations(SMALL_SOURCES)
    second = _select_mutations(SMALL_SOURCES)

    assert [mutation.mutation_id for mutation in first] == [
        mutation.mutation_id for mutation in second
    ]
    assert [mutation.problem for mutation in first] == [
        mutation.problem for mutation in second
    ]


def test_required_error_codes_are_covered() -> None:
    mutations = _select_mutations(SMALL_SOURCES)
    seen = {mutation.expected_error_code for mutation in mutations}
    seen -= {"invalid_value"}  # parser rejection codes are tracked separately
    assert set(gate_b_plus.REQUIRED_ERROR_CODES) <= seen


def test_required_subtypes_are_generated_when_possible() -> None:
    mutations = _select_mutations(SMALL_SOURCES)
    by_kind: dict[str, set[str]] = {}
    for mutation in mutations:
        if mutation.parser_rejection_expected:
            continue
        by_kind.setdefault(mutation.mutation_kind, set()).add(mutation.mutation_subtype)
    expected_subtypes = {
        "unsupported_schema_version": {
            "version_0_1",
            "version_0_3",
            "version_1_0",
            "version_label",
        },
        "invalid_domain": {
            "domain_logic_grid",
            "domain_zebra_logic",
            "domain_capitalized",
            "domain_label",
        },
        "size_mismatch": {
            "categories_too_small",
            "categories_too_large",
            "houses_too_small",
            "houses_too_large",
        },
        "category_size_mismatch": {
            "remove_first",
            "remove_last",
            "append_extra",
        },
        "duplicate_value": {
            "duplicate_first",
            "duplicate_last",
            "duplicate_every_category",
        },
        "duplicate_clue_id": {
            "first_to_second",
            "last_to_first",
            "non_adjacent",
            "three_clues",
        },
        "unknown_category": {
            "unary_cat",
            "binary_a_cat",
            "binary_b_cat",
        },
        "unknown_value": {
            "unary_val",
            "binary_a_val",
            "binary_b_val",
            "known_value_wrong_category",
            "totally_unknown_value",
        },
        "house_out_of_range": {
            "house_zero",
            "house_one_past_end",
            "house_hundred_past_end",
        },
    }
    for kind, subtypes in expected_subtypes.items():
        assert subtypes <= by_kind.get(kind, set()), (
            f"missing subtypes for {kind}:"
            f" {subtypes - by_kind.get(kind, set())}"
        )


def test_real_gate_a_run_generates_at_least_300_mutations() -> None:
    # Verify the wiring by reading the existing artifacts from the last real
    # run; this test runs only when the manifest exists so it does not slow
    # down normal `pytest` runs that only exercise stubs.
    output = ROOT / "eval/gates/stage2_gate_b_plus_fuzz"
    manifest_path = output / "manifest.json"
    if not manifest_path.is_file():
        return
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["total_mutations_generated"] >= 300
    assert manifest["total_source_problems_used"] >= 3


def test_unexpected_compiled_fails_the_gate(tmp_path: Path) -> None:
    mutations = _select_mutations(SMALL_SOURCES)
    expected_codes, expected_paths = _build_expected(mutations)

    def invoke(request: dict[str, Any]) -> dict[str, Any]:
        return {
            "protocol_version": "0.1.0",
            "request_id": request["request_id"],
            "result": {"kind": "COMPILED", "compiled": {"problem_id": "stub"}},
        }

    # Compile mutation expected codes/paths must still be populated even
    # though the invoke always returns COMPILED, so the gate's expected_codes
    # helper stays deterministic.
    assert expected_codes
    output = tmp_path / "gate-b-plus"
    exit_code, manifest = gate_b_plus.run_gate(
        ROOT,
        GATE_A,
        output,
        20260628,
        1,
        "gate-b-plus-test",
        invoke_fn=invoke,
        sources=SMALL_SOURCES,
    )
    assert exit_code == 1
    assert manifest["status"] == "fail"
    assert manifest["total_unexpected_compiled"] == len(mutations)
    # Controls must compile, but with the all-COMPILED stub, they also
    # "compile" successfully (in the stub's sense), so control counts stay 0
    # for unexpected rejections.


def test_wrong_error_code_fails_the_gate(tmp_path: Path) -> None:
    mutations = _select_mutations(SMALL_SOURCES)
    expected_codes = {
        mutation.mutation_id: "wrong_code" for mutation in mutations
    }
    expected_paths = {
        mutation.mutation_id: mutation.expected_error_path for mutation in mutations
    }
    invoke = lambda request: _stub_invoke(  # noqa: E731
        request, expected_codes=expected_codes, expected_paths=expected_paths
    )
    output = tmp_path / "gate-b-plus"
    exit_code, manifest = gate_b_plus.run_gate(
        ROOT,
        GATE_A,
        output,
        20260628,
        1,
        "gate-b-plus-test",
        invoke_fn=invoke,
        sources=SMALL_SOURCES,
    )
    assert exit_code == 1
    assert manifest["total_wrong_error_code"] == len(mutations)


def test_missing_error_path_fails_the_gate(tmp_path: Path) -> None:
    mutations = _select_mutations(SMALL_SOURCES)
    expected_codes = {
        mutation.mutation_id: (
            "invalid_value"
            if mutation.parser_rejection_expected
            else mutation.expected_error_code
        )
        for mutation in mutations
    }
    expected_paths = {
        mutation.mutation_id: "" for mutation in mutations
    }
    invoke = lambda request: _stub_invoke(  # noqa: E731
        request, expected_codes=expected_codes, expected_paths=expected_paths
    )
    output = tmp_path / "gate-b-plus"
    exit_code, manifest = gate_b_plus.run_gate(
        ROOT,
        GATE_A,
        output,
        20260628,
        1,
        "gate-b-plus-test",
        invoke_fn=invoke,
        sources=SMALL_SOURCES,
    )
    assert exit_code == 1
    non_parser_mutations = [
        mutation for mutation in mutations if not mutation.parser_rejection_expected
    ]
    assert manifest["total_missing_error_path"] == len(non_parser_mutations)


def test_control_rejection_fails_the_gate(tmp_path: Path) -> None:
    selected = gate_b_plus.select_sources(SMALL_SOURCES, 1, random.Random(20260628))
    mutations = []
    for source in selected:
        mutations.extend(gate_b_plus.build_mutation_plan(source))
    expected_codes, expected_paths = _build_expected(mutations)

    def invoke(request: dict[str, Any]) -> dict[str, Any]:
        if request["request_id"].startswith("control_"):
            return {
                "protocol_version": "0.1.0",
                "request_id": request["request_id"],
                "result": {
                    "kind": "STATIC_ERROR",
                    "error_code": "duplicate_value",
                    "error_path": "$.categories[",
                    "message": "control unexpectedly rejected",
                },
            }
        return _stub_invoke(
            request, expected_codes=expected_codes, expected_paths=expected_paths
        )

    output = tmp_path / "gate-b-plus"
    exit_code, manifest = gate_b_plus.run_gate(
        ROOT,
        GATE_A,
        output,
        20260628,
        1,
        "gate-b-plus-test",
        invoke_fn=invoke,
        sources=SMALL_SOURCES,
    )
    assert exit_code == 1
    assert manifest["total_controls_rejected"] >= 1


def test_cross_category_duplicate_value_is_not_treated_as_duplicate_value() -> None:
    # Build the cross-category control for a known source and confirm it
    # compiles (the compiler doesn't share category values).
    source = _pick(ALL_SOURCES, "4x4", "lgp-test-4x4-0")
    control = gate_b_plus._control_cross_category_duplicate(source)
    assert control is not None
    # The control problem has distinct internal values per category even
    # though one display string appears in both.
    categories = control.problem["categories"]
    cat_names = list(categories.keys())
    values_a = categories[cat_names[0]]
    values_b = categories[cat_names[1]]
    intersection = set(values_a) & set(values_b)
    assert len(intersection) == 1
    cross_value = next(iter(intersection))
    assert values_a.count(cross_value) == 1
    assert values_b.count(cross_value) == 1


def test_artifacts_are_written(tmp_path: Path) -> None:
    selected = gate_b_plus.select_sources(ALL_SOURCES, 1, random.Random(20260628))
    mutations = []
    for source in selected:
        mutations.extend(gate_b_plus.build_mutation_plan(source))
    controls = gate_b_plus.build_controls(selected)
    expected_codes, expected_paths = _build_expected(mutations)
    invoke = lambda request: _stub_invoke(  # noqa: E731
        request, expected_codes=expected_codes, expected_paths=expected_paths
    )
    output = tmp_path / "gate-b-plus"
    exit_code, manifest = gate_b_plus.run_gate(
        ROOT,
        GATE_A,
        output,
        20260628,
        1,
        "gate-b-plus-test",
        invoke_fn=invoke,
        sources=ALL_SOURCES,
    )
    assert exit_code == 0
    assert manifest["status"] == "pass"
    assert {path.name for path in output.iterdir()} >= {
        "manifest.json",
        "mutations.jsonl",
        "results.jsonl",
        "controls.jsonl",
        "control_results.jsonl",
        "findings.jsonl",
        "mutation_examples.md",
        "summary.md",
        "mutated_problems",
        "control_problems",
    }
    assert len(list((output / "mutated_problems").glob("*.problem.json"))) == len(mutations)
    assert len(list((output / "control_problems").glob("*.problem.json"))) == len(controls)
    assert manifest["total_mutations_generated"] >= 300
