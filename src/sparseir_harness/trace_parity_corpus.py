"""Differential parity corpus: traces that exercise the boundary surface
between the published JSON Schema (schemas/zebra-trace.schema.json) and the
trusted Lean parser (SparseIRLean/Trace.lean).

For each entry, the JSON Schema validator verdict and the Lean parser verdict
must agree. This module is the substrate for the real parity gate; see
tests/test_stage4_trace_parser.py::test_differential_schema_parser_parity.

Each entry is `(name, trace_dict, expected_valid)`. expected_valid is True if
both validators must accept; False if both validators must reject. The exact
error code is intentionally not pinned at the corpus layer — the goal of the
parity gate is verdicts-agree, not codes-agree (codes are covered by the
existing taxonomy-coverage gate in trace_parser_gate.py).
"""

from __future__ import annotations

from typing import Any


def _full_candidate_solution() -> dict[str, Any]:
    return {
        "schema_version": "0.2",
        "problem_id": "zl_parity",
        "ops": [
            {
                "op": "assign_all",
                "solution": {"Color": {"1": "red", "2": "blue"}},
            },
            {"op": "conclude", "status": "solved"},
        ],
    }


def _stepwise_clue_trace() -> dict[str, Any]:
    return {
        "schema_version": "0.2",
        "problem_id": "zl_parity",
        "ops": [
            {
                "op": "place",
                "cat": "Color",
                "house": 1,
                "val": "red",
                "justify": {"clue": "c1"},
            },
            {"op": "conclude", "status": "solved"},
        ],
    }


def _stepwise_bijection_trace() -> dict[str, Any]:
    return {
        "schema_version": "0.2",
        "problem_id": "zl_parity",
        "ops": [
            {
                "op": "eliminate",
                "cat": "Color",
                "house": 1,
                "val": "red",
                "justify": {
                    "rule": "bijection",
                    "from": [{"cat": "Color", "house": 2, "val": "blue"}],
                },
            },
            {"op": "conclude", "status": "solved"},
        ],
    }


def parity_corpus() -> list[tuple[str, dict[str, Any], bool]]:
    """Return (name, trace_object, expected_valid) entries.

    Each entry is hand-curated to cover a specific boundary shape. Both
    validators (Schema validator + Lean parser) must agree on the verdict for
    every entry. The path/code taxonomy is exercised separately by
    trace_parser_gate._malformed_cases().

    Coverage summary (counts updated by the parity test runner):
        valid_full_candidate          : 5
        valid_stepwise_clue           : 6
        valid_stepwise_bijection      : 4
        invalid_top_level             : ~12
        invalid_schema_version        : ~7
        invalid_problem_id            : ~7
        invalid_ops                   : ~10
        invalid_op_string             : ~3
        invalid_assign_all            : ~6
        invalid_place_missing_field   : 4 (per cell field)
        invalid_eliminate_missing_field: 4
        invalid_cell_type             : many
        invalid_solution_shape        : many
        invalid_house_key             : many
        invalid_justification_shape   : many
        invalid_conclude              : ~5
    """
    corpus: list[tuple[str, dict[str, Any], bool]] = []

    valid = _full_candidate_solution()

    # ---- valid shapes (both validators must accept) ----

    # minimal valid full-candidate
    corpus.append(("valid-min-full", valid, True))
    # minimal valid clue-stepwise
    corpus.append(("valid-min-stepwise-clue", _stepwise_clue_trace(), True))
    # minimal valid bijection-stepwise
    corpus.append(("valid-min-stepwise-bijection", _stepwise_bijection_trace(), True))
    # full_candidate with all valid optional fields populated
    corpus.append(
        (
            "valid-rich-full",
            {
                "schema_version": "0.2",
                "problem_id": "zl_parity",
                "ops": [
                    {
                        "op": "assign_all",
                        "solution": {
                            "Color": {"1": "red", "2": "blue"},
                            "Drink": {"1": "tea", "2": "coffee"},
                        },
                    },
                    {
                        "op": "conclude",
                        "status": "solved",
                        "solution": {
                            "Color": {"1": "red", "2": "blue"},
                        },
                    },
                ],
            },
            True,
        )
    )

    # stepwise with various valid justify shapes
    corpus.append(
        (
            "valid-stepwise-clue-empty-from",
            {
                "schema_version": "0.2",
                "problem_id": "zl_parity",
                "ops": [
                    {
                        "op": "place",
                        "cat": "Color",
                        "house": 1,
                        "val": "red",
                        "justify": {"clue": "c1", "from": []},
                    },
                    {"op": "conclude", "status": "solved"},
                ],
            },
            True,
        )
    )
    corpus.append(
        (
            "valid-stepwise-bijection-empty-from",
            {
                "schema_version": "0.2",
                "problem_id": "zl_parity",
                "ops": [
                    {
                        "op": "place",
                        "cat": "Color",
                        "house": 1,
                        "val": "red",
                        "justify": {"rule": "bijection"},
                    },
                    {"op": "conclude", "status": "solved"},
                ],
            },
            True,
        )
    )
    corpus.append(
        (
            "valid-stepwise-clue-multi-from",
            {
                "schema_version": "0.2",
                "problem_id": "zl_parity",
                "ops": [
                    {
                        "op": "eliminate",
                        "cat": "Color",
                        "house": 1,
                        "val": "red",
                        "justify": {
                            "clue": "c1",
                            "from": [
                                {"cat": "Color", "house": 2, "val": "blue"},
                                {"cat": "Color", "house": 3, "val": "red"},
                            ],
                        },
                    },
                    {"op": "conclude", "status": "solved"},
                ],
            },
            True,
        )
    )

    # single op: pure conclude (parser does NOT require other ops)
    corpus.append(
        (
            "valid-only-conclude",
            {
                "schema_version": "0.2",
                "problem_id": "zl_parity",
                "ops": [{"op": "conclude", "status": "solved"}],
            },
            True,
        )
    )
    # single op: place without conclude (parser does NOT require conclude)
    corpus.append(
        (
            "valid-place-only-no-conclude",
            {
                "schema_version": "0.2",
                "problem_id": "zl_parity",
                "ops": [
                    {
                        "op": "place",
                        "cat": "Color",
                        "house": 1,
                        "val": "red",
                        "justify": {"clue": "c1"},
                    }
                ],
            },
            True,
        )
    )

    # large but well-formed house indexes
    corpus.append(
        (
            "valid-large-houses",
            {
                "schema_version": "0.2",
                "problem_id": "zl_parity",
                "ops": [
                    {
                        "op": "assign_all",
                        "solution": {"C": {"1": "v", "2": "v", "1000": "v"}},
                    },
                    {"op": "conclude", "status": "solved"},
                ],
            },
            True,
        )
    )

    # ---- invalid top-level shapes ----

    corpus.append(
        (
            "invalid-empty-top-object",
            {"schema_version": "0.2", "problem_id": "zl_parity"},
            False,  # missing ops
        )
    )
    corpus.append(
        ("invalid-top-array", ["not", "an", "object"], False)
    )
    corpus.append(
        ("invalid-top-null", None, False)
    )
    corpus.append(
        ("invalid-top-string", "just a string", False)
    )
    corpus.append(
        ("invalid-top-int", 7, False)
    )

    # extra top-level keys must be rejected (both reject)
    corpus.append(
        (
            "invalid-top-extra-key",
            {
                "schema_version": "0.2",
                "problem_id": "zl_parity",
                "ops": [{"op": "conclude", "status": "solved"}],
                "extra": True,
            },
            False,
        )
    )

    # ---- invalid schema_version ----

    for bad in ("0.1", "0.3", "2", "0.2.0", ""):
        t = {
            "schema_version": bad,
            "problem_id": "zl_parity",
            "ops": [{"op": "conclude", "status": "solved"}],
        }
        corpus.append((f"invalid-schema-version-{bad!r}", t, False))

    for bad in (None, 0, 0.2, True, False, [], {}):
        t = {
            "schema_version": bad,
            "problem_id": "zl_parity",
            "ops": [{"op": "conclude", "status": "solved"}],
        }
        corpus.append((f"invalid-schema-version-type-{type(bad).__name__}", t, False))

    # ---- invalid problem_id ----

    t = {
        "schema_version": "0.2",
        "ops": [{"op": "conclude", "status": "solved"}],
    }
    corpus.append(("invalid-problem_id-missing", t, False))

    for bad in (None, 0, True, False, "", [], {}):
        t = {
            "schema_version": "0.2",
            "problem_id": bad,
            "ops": [{"op": "conclude", "status": "solved"}],
        }
        corpus.append((f"invalid-problem_id-type-{type(bad).__name__}", t, False))

    # ---- invalid ops ----

    t = {
        "schema_version": "0.2",
        "problem_id": "zl_parity",
    }
    corpus.append(("invalid-ops-missing", t, False))

    for bad_ops in (None, True, False, 0, 1, 7, 1.5, "string", {}):
        t = {
            "schema_version": "0.2",
            "problem_id": "zl_parity",
            "ops": bad_ops,
        }
        corpus.append((f"invalid-ops-type-{type(bad_ops).__name__}", t, False))

    t = {
        "schema_version": "0.2",
        "problem_id": "zl_parity",
        "ops": [],
    }
    corpus.append(("invalid-ops-empty-array", t, False))

    # mixed types in ops array
    for bad_op in (None, True, 7, "string", [], {}):
        t = {
            "schema_version": "0.2",
            "problem_id": "zl_parity",
            "ops": [bad_op],
        }
        corpus.append((f"invalid-op-type-{type(bad_op).__name__}", t, False))

    # ---- invalid op strings ----

    for bad in ("Guess", "PLACE", "place ", "", "place\t", "assignall"):
        t = {
            "schema_version": "0.2",
            "problem_id": "zl_parity",
            "ops": [{"op": bad}],
        }
        corpus.append((f"invalid-op-name-{bad!r}", t, False))

    # ---- invalid assign_all ----

    corpus.append(
        (
            "invalid-assign-all-empty-solution",
            {
                "schema_version": "0.2",
                "problem_id": "zl_parity",
                "ops": [{"op": "assign_all"}, {"op": "conclude", "status": "solved"}],
            },
            False,
        )
    )
    corpus.append(
        (
            "invalid-assign-all-solution-empty-object",
            {
                "schema_version": "0.2",
                "problem_id": "zl_parity",
                "ops": [
                    {"op": "assign_all", "solution": {}},
                    {"op": "conclude", "status": "solved"},
                ],
            },
            False,
        )
    )
    corpus.append(
        (
            "invalid-assign-all-solution-empty-cat-assignments",
            {
                "schema_version": "0.2",
                "problem_id": "zl_parity",
                "ops": [
                    {"op": "assign_all", "solution": {"Color": {}}},
                    {"op": "conclude", "status": "solved"},
                ],
            },
            False,
        )
    )
    corpus.append(
        (
            "invalid-assign-all-solution-house-zero",
            {
                "schema_version": "0.2",
                "problem_id": "zl_parity",
                "ops": [
                    {"op": "assign_all", "solution": {"Color": {"0": "red"}}},
                    {"op": "conclude", "status": "solved"},
                ],
            },
            False,
        )
    )
    corpus.append(
        (
            "invalid-assign-all-solution-house-non-canonical",
            {
                "schema_version": "0.2",
                "problem_id": "zl_parity",
                "ops": [
                    {"op": "assign_all", "solution": {"Color": {"01": "red"}}},
                    {"op": "conclude", "status": "solved"},
                ],
            },
            False,
        )
    )
    corpus.append(
        (
            "invalid-assign-all-solution-house-string-empty",
            {
                "schema_version": "0.2",
                "problem_id": "zl_parity",
                "ops": [
                    {"op": "assign_all", "solution": {"Color": {"": "red"}}},
                    {"op": "conclude", "status": "solved"},
                ],
            },
            False,
        )
    )

    # ---- invalid place / eliminate (cell field type) ----

    for field, bad_types in (
        ("cat", (None, 0, True, False, "", [], {})),
        ("val", (None, 0, True, False, "", [], {})),
    ):
        for bad in bad_types:
            for op_name in ("place", "eliminate"):
                t = {
                    "schema_version": "0.2",
                    "problem_id": "zl_parity",
                    "ops": [
                        {
                            "op": op_name,
                            "cat": "Color",
                            "house": 1,
                            "val": "red",
                            "justify": {"clue": "c1"},
                        },
                    ],
                }
                t["ops"][0][field] = bad
                corpus.append(
                    (
                        f"invalid-{op_name}-{field}-type-{type(bad).__name__}",
                        t,
                        False,
                    )
                )

    # house boundary cases (place)
    for bad_house in (0, -1, 1.5, "1", "abc", None, True, [], {}):
        t = {
            "schema_version": "0.2",
            "problem_id": "zl_parity",
            "ops": [
                {
                    "op": "place",
                    "cat": "Color",
                    "house": bad_house,
                    "val": "red",
                    "justify": {"clue": "c1"},
                },
                {"op": "conclude", "status": "solved"},
            ],
        }
        corpus.append(
            (f"invalid-place-house-type-{type(bad_house).__name__}", t, False)
        )

    # ---- invalid justification ----

    # empty object (neither clue nor rule)
    corpus.append(
        (
            "invalid-justify-empty",
            {
                "schema_version": "0.2",
                "problem_id": "zl_parity",
                "ops": [
                    {
                        "op": "place",
                        "cat": "Color",
                        "house": 1,
                        "val": "red",
                        "justify": {},
                    },
                    {"op": "conclude", "status": "solved"},
                ],
            },
            False,
        )
    )

    # both clue AND rule
    corpus.append(
        (
            "invalid-justify-clue-and-rule",
            {
                "schema_version": "0.2",
                "problem_id": "zl_parity",
                "ops": [
                    {
                        "op": "place",
                        "cat": "Color",
                        "house": 1,
                        "val": "red",
                        "justify": {"clue": "c1", "rule": "bijection"},
                    },
                    {"op": "conclude", "status": "solved"},
                ],
            },
            False,
        )
    )

    # unknown rule name
    corpus.append(
        (
            "invalid-justify-rule-given-found-at-place",
            {
                "schema_version": "0.2",
                "problem_id": "zl_parity",
                "ops": [
                    {
                        "op": "place",
                        "cat": "Color",
                        "house": 1,
                        "val": "red",
                        "justify": {"rule": "given_found_at_place"},
                    },
                    {"op": "conclude", "status": "solved"},
                ],
            },
            False,
        )
    )

    # unknown rule name (one of the 22 private kernel rule names)
    corpus.append(
        (
            "invalid-justify-rule-private-bijection-name",
            {
                "schema_version": "0.2",
                "problem_id": "zl_parity",
                "ops": [
                    {
                        "op": "place",
                        "cat": "Color",
                        "house": 1,
                        "val": "red",
                        "justify": {
                            "rule": "bijection_place_eliminates_other_values_same_house"
                        },
                    },
                    {"op": "conclude", "status": "solved"},
                ],
            },
            False,
        )
    )

    # justify: null
    corpus.append(
        (
            "invalid-justify-null",
            {
                "schema_version": "0.2",
                "problem_id": "zl_parity",
                "ops": [
                    {
                        "op": "place",
                        "cat": "Color",
                        "house": 1,
                        "val": "red",
                        "justify": None,
                    },
                    {"op": "conclude", "status": "solved"},
                ],
            },
            False,
        )
    )

    # justify: list
    corpus.append(
        (
            "invalid-justify-list",
            {
                "schema_version": "0.2",
                "problem_id": "zl_parity",
                "ops": [
                    {
                        "op": "place",
                        "cat": "Color",
                        "house": 1,
                        "val": "red",
                        "justify": ["clue", "c1"],
                    },
                    {"op": "conclude", "status": "solved"},
                ],
            },
            False,
        )
    )

    # clue: empty string
    corpus.append(
        (
            "invalid-justify-clue-empty-string",
            {
                "schema_version": "0.2",
                "problem_id": "zl_parity",
                "ops": [
                    {
                        "op": "place",
                        "cat": "Color",
                        "house": 1,
                        "val": "red",
                        "justify": {"clue": ""},
                    },
                    {"op": "conclude", "status": "solved"},
                ],
            },
            False,
        )
    )

    # from: list-not-array
    corpus.append(
        (
            "invalid-justify-from-not-array",
            {
                "schema_version": "0.2",
                "problem_id": "zl_parity",
                "ops": [
                    {
                        "op": "place",
                        "cat": "Color",
                        "house": 1,
                        "val": "red",
                        "justify": {"clue": "c1", "from": "string"},
                    },
                    {"op": "conclude", "status": "solved"},
                ],
            },
            False,
        )
    )

    # from: cell missing house
    corpus.append(
        (
            "invalid-justify-from-cell-missing-house",
            {
                "schema_version": "0.2",
                "problem_id": "zl_parity",
                "ops": [
                    {
                        "op": "place",
                        "cat": "Color",
                        "house": 1,
                        "val": "red",
                        "justify": {
                            "clue": "c1",
                            "from": [{"cat": "Color", "val": "blue"}],
                        },
                    },
                    {"op": "conclude", "status": "solved"},
                ],
            },
            False,
        )
    )

    # from: cell house=0 (in a structural justify path; same code path)
    corpus.append(
        (
            "invalid-justify-from-cell-house-zero",
            {
                "schema_version": "0.2",
                "problem_id": "zl_parity",
                "ops": [
                    {
                        "op": "place",
                        "cat": "Color",
                        "house": 1,
                        "val": "red",
                        "justify": {
                            "rule": "bijection",
                            "from": [{"cat": "Color", "house": 0, "val": "blue"}],
                        },
                    },
                    {"op": "conclude", "status": "solved"},
                ],
            },
            False,
        )
    )

    # ---- invalid conclude ----

    # missing status
    corpus.append(
        (
            "invalid-conclude-missing-status",
            {
                "schema_version": "0.2",
                "problem_id": "zl_parity",
                "ops": [{"op": "conclude"}],
            },
            False,
        )
    )
    # bad status
    for bad in ("unknown", "SOLVED", "solved ", " solved", "solved.", ""):
        t = {
            "schema_version": "0.2",
            "problem_id": "zl_parity",
            "ops": [{"op": "conclude", "status": bad}],
        }
        corpus.append((f"invalid-conclude-status-{bad!r}", t, False))

    # conclude with empty solution object
    corpus.append(
        (
            "invalid-conclude-empty-solution",
            {
                "schema_version": "0.2",
                "problem_id": "zl_parity",
                "ops": [{"op": "conclude", "status": "solved", "solution": {}}],
            },
            False,
        )
    )

    # ---- nested extra keys (rejected by both schemas and parser) ----

    corpus.append(
        (
            "invalid-cell-extra-key",
            {
                "schema_version": "0.2",
                "problem_id": "zl_parity",
                "ops": [
                    {
                        "op": "place",
                        "cat": "Color",
                        "house": 1,
                        "val": "red",
                        "justify": {
                            "rule": "bijection",
                            "from": [
                                {
                                    "cat": "Color",
                                    "house": 2,
                                    "val": "blue",
                                    "extra": True,
                                }
                            ],
                        },
                    },
                    {"op": "conclude", "status": "solved"},
                ],
            },
            False,
        )
    )

    corpus.append(
        (
            "invalid-op-extra-key",
            {
                "schema_version": "0.2",
                "problem_id": "zl_parity",
                "ops": [
                    {
                        "op": "place",
                        "cat": "Color",
                        "house": 1,
                        "val": "red",
                        "justify": {"rule": "bijection"},
                        "extra": True,
                    },
                    {"op": "conclude", "status": "solved"},
                ],
            },
            False,
        )
    )

    return corpus
