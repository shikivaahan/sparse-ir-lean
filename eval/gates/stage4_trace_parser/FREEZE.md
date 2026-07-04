# Stage 4 freeze record

**Status:** FROZEN — public interface, parser, error taxonomy, and gate evidence are
stable. This stage measures *parseability only*. Replay, semantic checks, and
artifact emission are explicitly out of scope here.

**Date:** 2026-07-04
**Branch:** `dev`
**Evidence under:** `eval/gates/stage4_trace_parser/`
**Schema file:** `schemas/zebra-trace.schema.json`

## 1. Frozen public contract

### 1.1 `schema_version`

The frozen schema version string is **`"0.2"`**. Lean `TraceParser.parse` rejects any
other value with `unsupported_schema_version` at JSON pointer `$.schema_version`.

### 1.2 Top-level shape

```json
{
  "schema_version": "0.2",
  "problem_id": "<non-empty string>",
  "ops": [
    /* one or more ops, see 1.4 */
  ]
}
```

Additional top-level keys are rejected as `unexpected_field` at `$.<key>`. Empty
`ops` is rejected as `empty_ops` at `$.ops`. The JSON Schema in
`schemas/zebra-trace.schema.json` mirrors this exactly; schema-drift is detected by
`tests/test_stage4_trace_parser.py::test_frozen_trace_schema_validates_against_lean_parser`.

### 1.3 Trace styles

`TraceStyle` is derived (not declared) from the ops list:

- **full_candidate** — the `ops` list contains at least one `assign_all`.
- **stepwise** — no `assign_all` (only `place` / `eliminate` / `conclude`).

A `conclude` op is required in both styles (the parser enforces it via the
`empty_ops` rejection; downstream replay — Stage 5 — is what checks that
`conclude` is present at the end of the op list).

### 1.4 Frozen operation AST

| Op | Required fields | Optional fields | Public notes |
|---|---|---|---|
| `assign_all` | `op`, `solution` | — | `solution` is `{category: {house: value}}`. Stage 4 does not check that categories/houses/values match the puzzle. |
| `place` | `op`, `cat`, `house`, `val`, `justify` | — | `house` is a positive integer. |
| `eliminate` | `op`, `cat`, `house`, `val`, `justify` | — | `house` is a positive integer. |
| `conclude` | `op`, `status` | `solution` | `status` must equal the literal string `"solved"`. |

Unknown op strings are rejected as `unknown_op` at `$.ops[<i>].op`. Extra fields
inside any op are rejected as `unexpected_field` at the offending JSON pointer.

### 1.5 Frozen public justification contract

```json
{
  "clue": "<non-empty string>",
  "from": [
    {"cat": "<non-empty string>", "house": <int >= 1>, "val": "<non-empty string>"}
  ]
}
```

- `clue` is **required** on every `place` and `eliminate`.
- `from` is **optional**. When present, it must be an array of cells; empty `[]` is
  allowed.
- The **internal Lean consequence-rule names** (e.g. `given_found_at_place`,
  `direct_left_place_from_fixed`, all 22 entries of `StepKernel.supportedRules`)
  are **not** part of the public interface. The JSON Schema explicitly forbids any
  extra `rule` / `rule_id` / `schema` / `kernel` key in `justify`, and a dedicated
  test (`test_frozen_trace_schema_rejects_internal_rule_names`) iterates the 22
  names to make drift obvious.
- The derivation `{"clue", "from"} → consequence-rule schema` is the **Stage 5
  bridge** and is **not** built or claimed here.

## 2. Trace parse error taxonomy (frozen)

22 codes, each with a deterministic JSON-pointer path. The
`expected_code` column shows the value used in committed fixtures.

| Code | Path example | Where it triggers |
|---|---|---|
| `invalid_json` | `$` | Top-level JSON cannot be parsed. |
| `missing_schema_version` | `$.schema_version` | Top-level `schema_version` absent. |
| `unsupported_schema_version` | `$.schema_version` | `schema_version` ≠ `"0.2"`. |
| `missing_problem_id` | `$.problem_id` | Top-level `problem_id` absent. |
| `missing_ops` | `$.ops` | Top-level `ops` absent. |
| `ops_not_array` | `$.ops` | `ops` is not an array. |
| `empty_ops` | `$.ops` | `ops` is an empty array. |
| `unknown_op` | `$.ops[i].op` | `op` is not one of the four known strings. |
| `assign_all_missing_solution` | `$.ops[i].solution` | `assign_all` without `solution`. |
| `assign_all_malformed_solution` | `$.ops[i].solution` | `assign_all` `solution` is not an object of assignments. |
| `place_missing_cat` | `$.ops[i].cat` | `place` without `cat`. |
| `place_missing_house` | `$.ops[i].house` | `place` without `house`. |
| `place_missing_val` | `$.ops[i].val` | `place` without `val`. |
| `eliminate_missing_cat` | `$.ops[i].cat` | `eliminate` without `cat`. |
| `eliminate_missing_house` | `$.ops[i].house` | `eliminate` without `house`. |
| `eliminate_missing_val` | `$.ops[i].val` | `eliminate` without `val`. |
| `missing_justify` | `$.ops[i].justify` | `place` / `eliminate` without `justify`. |
| `malformed_justify` | `$.ops[i].justify` | `justify` is not an object. |
| `malformed_from_cell` | `$.ops[i].justify.from[j]` | a from-cell is malformed. |
| `conclude_missing_status` | `$.ops[i].status` | `conclude` without `status`. |
| `conclude_bad_status` | `$.ops[i].status` | `status` is not the literal `"solved"`. |
| `unexpected_field` | `$.<key>` or `$.ops[i].<key>` | An extra key is present. |

## 3. `parse_trace` CLI command (frozen)

- Command name: `parse_trace`.
- Request shape:
  ```json
  {
    "protocol_version": "0.1.0",
    "request_id": "<arbitrary>",
    "command": "parse_trace",
    "payload": {"trace": "<trace JSON string>"}
  }
  ```
  `payload.trace_json` is also accepted as an alias.
- Success result (`TRACE_PARSED`):
  ```json
  {"kind":"TRACE_PARSED", "problem_id":"<id>", "op_count":<int >= 1>, "trace_style":"full_candidate"|"stepwise"}
  ```
- Rejection result (`REJECT`):
  ```json
  {"kind":"REJECT", "failure":{"status":"malformed_trace", "failure_code":"<code>", "path":"<json pointer>", "message":"<text>"}}
  ```
- Invalid request shape: `{"kind":"STATIC_ERROR", "error_code":"invalid_request", ...}`.

The protocol is documented in `schemas/verifier-protocol.schema.json`.

## 4. Runtime capability claims (corrected)

`info` now reports:

```json
{
  "kind": "INFO",
  "domain": "zebra",
  "schema_version": "0.2",
  "trust": "trusted_for_results",
  "capabilities": {
    "modes": [0],
    "stepwise": false,
    "tactics": false,
    "audit_view": false
  }
}
```

This is honest:

- `modes: [0]` — Mode 0 (the end-only candidate check via `check_candidate`) is
  implemented. The trust story for Modes 1/2 requires stepwise trace replay,
  which is Stage 5.
- `stepwise: false` — the Stage 4 parser is shipped; the stepwise *checker* is
  not. Earlier capability claims of `stepwise: true` were untrue.
- `tactics: false` — unbuilt.
- `audit_view: false` — `Pretty.lean` is a stub. The H8 human-shift-left
  argument is not yet supported by a Lean-rendered view; this is documented in
  the README and the report as outstanding.

The north-star architecture (Modes 0/1/2, tactics, audit view) remains in the
spec; the capabilities object is the only place that pins what is *currently
implemented*.

## 5. Gate evidence

All counts are derived from raw artifacts (`traces.jsonl`, `results.jsonl`,
`provider_validation/parse_results.jsonl`, `provider_adversarial/parse_results.jsonl`),
not from the headline `summary.md`.

### 5.1 Core parser gate

- Total traces: **2022**
- Valid full-candidate traces: **1000** — all returned `TRACE_PARSED` with
  `trace_style="full_candidate"`.
- Valid stepwise traces: **1000** — all returned `TRACE_PARSED` with
  `trace_style="stepwise"`.
- Malformed traces: **22** — all returned `REJECT` with the expected
  `failure_code` and `path` (verified by re-running the expected-vs-actual
  comparison at freeze time).
- Protocol errors: **0**.
- Failures: **0**.
- Parse error coverage: **22 / 22**.

### 5.2 Provider trace-shape validation

- Total samples: **140**
- `TRACE_PARSED`: **140 / 140** (parseability rate = 1.0)
- Status: **pass** (parseability only — does not check semantic correctness or
  puzzle solvability)

### 5.3 Provider adversarial parser diagnostics

- Total samples: **260** (140 positive, 120 adversarial)
- Positive samples that returned `TRACE_PARSED`: **140 / 140**
- Adversarial samples that returned `REJECT` (matching the expected structured
  bucket): **120 / 120**
- Status: **pass** (parseability only)

### 5.4 Validation commands

```bash
# Lean parser + walkthrough tests
~/.elan/bin/lake.exe build
~/.elan/bin/lake.exe test          # exit 0

# Python test suite (skips the live-provider test_oracle)
uv run pytest tests/ --ignore=tests/test_oracle.py    # 200 passed

# Lint
uv run ruff check .               # All checks passed

# Schema-vs-parser drift check (added in this freeze)
uv run pytest tests/test_stage4_trace_parser.py -k schema
#   test_frozen_trace_schema_validates_against_lean_parser PASS
#   test_frozen_trace_schema_rejects_internal_rule_names PASS
```

The existing 2022 core gate runs through the trusted parser; the schema test
loads `schemas/zebra-trace.schema.json` and exercises both happy paths and each
of the 22 reject cases directly. The internal-rule-names test enumerates the
22 names from `StepKernel.supportedRules` and asserts the schema rejects each as
an unknown property.

## 6. Known non-Stage-4 limitations (downstream, not Stage 4 failures)

These are not Stage 4 defects. They are recorded so the Stage 5 handoff is
explicit.

1. **Trace replay is not implemented.** `parse_trace` lowers a trace JSON into
   a `Trace` AST; nothing in the trusted code re-runs the ops, applies them to a
   checker state, localizes first-failure, or emits a checked artifact. That
   driver is Stage 5.
2. **`{"clue", "from"}` → internal kernel consequence-rule derivation is a
   Stage 5 task.** The kernel's 22 `supportedRules` are *private* to Lean and
   must never be supplied by the model. The bridge that infers which schema
   applies, given `(op, clue, from)` and the current candidate sets, is
   unbuilt.
3. **Stepwise G1 Lean↔clingo differential validation remains outstanding
   Stage 3 debt.** The candidate half of G1 (Mode 0 vs clingo) is closed. The
   stepwise half is still example-based, not clingo-fuzzed; it must be closed
   before Stage 5 replay is implemented, otherwise the Stage 5 driver could
   certify unjustified steps.
4. **`Pretty.lean` is still a stub.** `render_audit` returns
   `not_implemented`. The faithfulness argument relies on a Lean-rendered view
   being auditable by humans before compute; that surface is missing.
5. **Stepwise trust in `info`.** `stepwise: false` reflects reality; it should
   flip to `true` only after Stage 5 ships trace replay with a clingo-differentially
   validated kernel.
6. **Stage 5 driver should thread state server-side.** Until that lands, the
   public trace contract does not need to change, but the driver must not
   accept caller-supplied intermediate states (per the Stage 3 audit finding
   that motivated this whole seam).

## 7. What is *not* part of the Stage 4 freeze

- Any claim that a parsed trace is correct or that the puzzle is solved.
- Any claim that the model's reasoning is faithful to the original natural
  language puzzle.
- Any cost, capability, or comparative-model result.
- Modes 1/2, tactics, recursion, second backend, `Pretty.lean`.

These are preserved as future work in the spec but are explicitly *not*
advertised by the runtime capabilities.

## 8. Reproduce the freeze evidence

```bash
git checkout dev
~/.elan/bin/lake.exe build
~/.elan/bin/lake.exe test
uv run ruff check .
uv run pytest tests/ --ignore=tests/test_oracle.py

# Inspect the committed raw counts (no re-run needed):
python -c "
import json
traces = [json.loads(l) for l in open('eval/gates/stage4_trace_parser/traces.jsonl')]
results = [json.loads(l) for l in open('eval/gates/stage4_trace_parser/results.jsonl')]
print('traces:', len(traces), '| results:', len(results))
print('by category:', {k: sum(t['category']==k for t in traces) for k in {t['category'] for t in traces}})
print('all results match expected:', all(
    (t['expected_kind']=='TRACE_PARSED' and r['result']['kind']=='TRACE_PARSED') or
    (t['expected_kind']=='REJECT' and r['result']['kind']=='REJECT' and
     r['result']['failure']['failure_code']==t['expected_code'])
    for t, r in zip(traces, results)))
"
```

A `True` from the script plus all 200 pytests passing plus `ruff check .` clean
plus `lake test` exit 0 is the freeze predicate.
