# Stage 4 freeze record

**Status:** FROZEN — public interface, parser, error taxonomy, and gate evidence
are stable. This stage measures *parseability only* (lower JSON → `Trace` AST
in the trusted Lean verifier). Replay, semantic stepwise checking, and artifact
emission are explicitly out of scope here.

**Date:** 2026-07-06
**Branch:** `stage4-finish` (this PR)
**Evidence under:** `eval/gates/stage4_trace_parser/`
**Schema file:** `schemas/zebra-trace.schema.json`
**Lean module:** `SparseIRLean/Trace.lean`
**Trace AST:** see §1.2 below

## 0. What this freeze is, and is not, honest about

This record is derived from raw evidence stored under
`eval/gates/stage4_trace_parser/` and from inspecting the trusted Lean code
at the freeze commit. The verifier *still* reports `modes: [0]`,
`stepwise: false`, `tactics: false`, `audit_view: false` in `info`. No claim
of Mode 1 or Mode 2 trace replay, semantic stepwise checking, or audit view
is made here. The 22 private `StepKernel.supportedRules` names stay
implementation-internal and are not exposed on the public trace surface
(see §1.5).

## 1. Frozen public contract

### 1.1 `schema_version`

The frozen schema version string is **`"0.2"`**. `TraceParser.parse` rejects
any other value with `unsupported_schema_version` at JSON pointer
`$.schema_version`.

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

Additional top-level keys are rejected as `unexpected_field` at `$.<key>`.
Empty `ops` is rejected as `empty_ops` at `$.ops`. The JSON Schema in
`schemas/zebra-trace.schema.json` mirrors this exactly; drift between the
JSON Schema and the trusted parser is detected by
`tests/test_stage4_trace_parser.py::test_frozen_trace_schema_validates_against_lean_parser`
(which now runs both validators on every entry of the parity corpus).

### 1.3 Trace styles

`TraceStyle` is derived (not declared) from the ops list:

- **full_candidate** — the `ops` list contains at least one `assign_all`.
- **stepwise** — no `assign_all` (only `place` / `eliminate` / `conclude`).

A `conclude` op is **not parser-required**. A non-empty stepwise trace
without `conclude` parses to `TRACE_PARSED` correctly. "Trace lacks a
conclude op" is a *Stage 5 / replay* concern (`goal_not_concluded`),
explicitly out of Stage 4 parser responsibility. Likewise: parser does not
require `conclude` to be the last op, doesn't forbid multiple concludes,
doesn't forbid mixing `assign_all` and stepwise ops, doesn't validate that
problem_id matches a real puzzle, doesn't check that categories/houses/values
match the puzzle, doesn't check that a justification is logically forced.
Each of those is a Stage 5 / replay concern.

### 1.4 Frozen operation AST

| Op | Required fields | Optional fields | Public notes |
|---|---|---|---|
| `assign_all` | `op`, `solution` | — | `solution` is `{category: {house: value}}`; must declare ≥ 1 category and ≥ 1 assignment per category. Stage 4 does not check the assignment against the puzzle. |
| `place` | `op`, `cat`, `house`, `val`, `justify` | — | `house` is a positive integer (≥ 1). |
| `eliminate` | `op`, `cat`, `house`, `val`, `justify` | — | `house` is a positive integer. |
| `conclude` | `op`, `status` | `solution` | `status` must equal the literal string `"solved"`. |

Unknown op strings are rejected as `unknown_op` at `$.ops[i].op`. Extra
fields inside any op are rejected as `unexpected_field` at the offending
JSON pointer.

### 1.5 Frozen public justification contract

The justification object on each `place`/`eliminate` op is a **tagged
union**, exactly two legal shapes:

```jsonc
// clue-based justification
{ "clue": "<non-empty clue id>", "from": [ /* optional, default [] */ ] }
```

```jsonc
// structural bijection justification
{ "rule": "bijection", "from": [ /* optional, default [] */ ] }
```

The `from` array is the same in both branches — it is a list of
`{cat, house, val}` cells used to cite supporting reasoning. Empty `from`
is documented to be allowed.

* `{"clue": ..., "from": ...?}`: the cited clue must be a non-empty
  string id. The clue existence / semantic-force check is Stage 5; this
  parser only checks the shape.
* `{"rule": "bijection", "from": ...?}`: the `rule` literal string is
  restricted to the exact value `"bijection"`. Any other value (including
  any of the 22 private kernel rule names) is rejected as
  `unknown_justify_rule`. The structural bijection variant is the
  *only* structural-rule name on the public trace surface.
* A justify object that lacks both `clue` and `rule` is rejected as
  `malformed_justify`.
* A justify object that contains both `clue` and `rule` is rejected as
  `malformed_justify`.
* The 22 `StepKernel.supportedRules` names are *not* constructors in
  `TraceJustification` (see `SparseIRLean/Trace.lean`); the public AST
  cannot express any of them and the trusted parser rejects them if the
  model tries to push one in via `{"rule": "<name>"}`. The dedicated
  test `test_frozen_trace_schema_rejects_internal_rule_names` enumerates
  the 22 names and asserts both the JSON Schema and the parser reject each.

The derivation `{{clue, from} | {rule: bijection, from}} → private kernel
consequence-rule schema` is the **Stage 5 bridge** and is **not** built or
claimed here.

### 1.6 Honest AST

```lean
inductive TraceJustification where
  | clue (clueId : String) (fromCells : List TraceCell)
  | bijection (fromCells : List TraceCell)
```

The inductive is the canonical honest AST. Stage 5 will introduce a bridge
from this AST to the private kernel consequence rule; that bridge is *not*
part of this stage.

## 2. Trace parse error taxonomy (frozen)

26 codes, each with a deterministic JSON-pointer path. The full taxonomy is
exercised end-to-end by `_malformed_cases()` in
`src/sparseir_harness/trace_parser_gate.py`; the parity test
`test_frozen_trace_schema_validates_against_lean_parser` exercises an
additional 122 boundary cases where both Schema and Lean verdicts must
agree.

| # | Code | Path example | Where it triggers |
|---|---|---|---|
| 1 | `invalid_json` | `$` | Top-level JSON cannot be parsed. |
| 2 | `missing_schema_version` | `$.schema_version` | Top-level `schema_version` absent. |
| 3 | `unsupported_schema_version` | `$.schema_version` | `schema_version` ≠ `"0.2"`. |
| 4 | `missing_problem_id` | `$.problem_id` | Top-level `problem_id` absent. |
| 5 | `malformed_problem_id` | `$.problem_id` | `problem_id` is not a non-empty string. |
| 6 | `missing_ops` | `$.ops` | Top-level `ops` absent. |
| 7 | `ops_not_array` | `$.ops` | `ops` is not an array. |
| 8 | `empty_ops` | `$.ops` | `ops` is an empty array. |
| 9 | `malformed_op` | `$.ops[i]` | an `ops[i]` is not an object. |
| 10 | `unknown_op` | `$.ops[i].op` | `op` is not one of the four known strings. |
| 11 | `assign_all_missing_solution` | `$.ops[i].solution` | `assign_all` without `solution`. |
| 12 | `assign_all_malformed_solution` | `$.ops[i].solution` | `assign_all` `solution` is malformed (empty object, empty category, non-canonical house key, house `0`, etc.). |
| 13 | `place_missing_cat` | `$.ops[i].cat` | `place` without `cat`. |
| 14 | `place_missing_house` | `$.ops[i].house` | `place` without `house`, or house ≤ 0. |
| 15 | `place_missing_val` | `$.ops[i].val` | `place` without `val`. |
| 16 | `eliminate_missing_cat` | `$.ops[i].cat` | `eliminate` without `cat`. |
| 17 | `eliminate_missing_house` | `$.ops[i].house` | `eliminate` without `house`, or house ≤ 0. |
| 18 | `eliminate_missing_val` | `$.ops[i].val` | `eliminate` without `val`. |
| 19 | `missing_justify` | `$.ops[i].justify` | `place`/`eliminate` without `justify`. |
| 20 | `malformed_justify` | `$.ops[i].justify` | `justify` is not an object, lacks both `clue` and `rule`, or contains both. |
| 21 | `unknown_justify_rule` | `$.ops[i].justify.rule` | `justify.rule` is present but not the literal `"bijection"`. |
| 22 | `malformed_from_cell` | `$.ops[i].justify.from[j]` | A from-cell is malformed. |
| 23 | `conclude_missing_status` | `$.ops[i].status` | `conclude` without `status`. |
| 24 | `conclude_bad_status` | `$.ops[i].status` | `status` is not the literal `"solved"`. |
| 25 | `conclude_malformed_solution` | `$.ops[i].solution` | `conclude` `solution` is malformed. |
| 26 | `unexpected_field` | `$.<key>` or `$.ops[i].<key>` | An extra key is present. |

The taxonomy was 25 codes at the prior freeze; it is now 26. The new code
`unknown_justify_rule` was added when the public justification contract was
extended from a single `clue/from` shape to a tagged union (`clue/from` or
`bijection/from`). No vanity count is preserved.

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

`info` reports:

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

- `modes: [0]` — Mode 0 (the end-only candidate check via `check_candidate`)
  is implemented. The trust story for Modes 1/2 requires stepwise trace
  replay, which is Stage 5.
- `stepwise: false` — the Stage 4 parser is shipped; the stepwise
  *checker* (Stage 5 trace replay) is not.
- `tactics: false` — unbuilt.
- `audit_view: false` — `Pretty.lean` is a stub. The H8 human-shift-left
  argument is not yet supported by a Lean-rendered view; this is documented
  in the README and the report as outstanding.

The north-star architecture (Modes 0/1/2, tactics, audit view) remains in
the spec; the capabilities object is the only place that pins what is
*currently implemented*.

## 5. Gate evidence

All counts are derived from raw artifacts stored under
`eval/gates/stage4_trace_parser/`, not from headline `summary.md` figures.

### 5.1 Core parser gate

- Total traces: **3028**
- Valid full-candidate traces: **1000** — all returned `TRACE_PARSED`
  with `trace_style="full_candidate"`.
- Valid stepwise traces: **2000** — all returned `TRACE_PARSED` with
  `trace_style="stepwise"`. The 2000 stepwise traces are split equally:
  - **1000 clue-based** (`{"clue": ..., "from": ...?}` only)
  - **1000 bijection-based** (`{"rule": "bijection", "from": ...?}` only)
  Both subsets pass at 100% via the trusted parser.
- Malformed fixtures: **28** cases exercising the **26** reachable error
  codes (every code in §2 above is exercised at least once; `malformed_justify`
  is exercised 3x to cover the "empty", "neither clue nor rule", and
  "both clue and rule" sub-cases). All 28 returned `REJECT` with the
  expected `failure_code` and `path`.
- Protocol errors: **0**.
- Failures: **0**.
- Parse error coverage: **26 / 26** (the full reachable `TraceParseErrorCode`
  taxonomy).

### 5.2 JSON Schema ↔ Lean parser differential parity

This is now a REAL differential gate. The test
`test_frozen_trace_schema_validates_against_lean_parser` ingests every
entry of `src/sparseir_harness/trace_parity_corpus.py` (122 hand-curated
boundary cases) and asserts that:

* The published JSON Schema validator (`jsonschema` Draft 2020-12) verdict
  matches the trusted `SparseIRLean/Trace.lean` parse verdict.
* Both verdicts match the hand-curated expectation.

Parity run (this freeze):
- Corpus entries: **122**
- Schema-accepts / Lean-accepts agreement: **122 / 122**
- Schema-rejects / Lean-rejects agreement: **122 / 122**
- Disagreements: **0**
- Hand-curated expectation mismatches (drift in either validator
  vs expectation): **0**

Coverage areas inside the corpus:
* top-level shape: empty, list, null, bool, int, float, string, extra keys
* `schema_version` boundary: wrong string, empty, null, number, bool, list, dict
* `problem_id` boundary: missing, null, empty, number, bool, list, dict
* `ops` boundary: missing, null, bool, int, string, dict, empty array, mixed types
* per-op boundary: malformed shape, unknown op strings, place/eliminate/conclude
* cell boundary: missing cat/house/val, missing on each;
  house-type boundary (0, -1, 1.5, "1", null, true, [], {});
  cat/val-type boundary (null, 0, true, false, "", list, dict)
* solution boundary: missing, empty `{}`, empty category `{}`, house `0`,
  house `"01"`, house `""`, mixed garbage
* justification boundary: empty, null, list, neither-clue-nor-rule,
  both-clue-and-rule, rule=`"bijection"`, rule=`given_found_at_place`,
  rule=private-bijection-like; `clue=""`, `from=""` (non-array),
  malformed from-cell, from-cell with house=0
* conclude boundary: missing status, status variants (`"unknown"`, `"SOLVED"`,
  `"solved "`, etc), empty solution `{}`
* nested extra-keys: cell extra, from-cell extra, op extra

The parity corpus is committed at
`src/sparseir_harness/trace_parity_corpus.py` and the test is committed
at `tests/test_stage4_trace_parser.py::test_frozen_trace_schema_validates_against_lean_parser`.

### 5.3 Provider trace-shape validation (stored full-candidate)

Re-parsed against the new parser:
- Total stored full-candidate samples: **140**
- `TRACE_PARSED`: **140 / 140** (parseability rate = 1.0)
- Status: **pass** (parseability only — does not check semantic correctness
  or puzzle solvability)
- **Evidence interpretation:** the 140 stored provider outputs are
  strong-exemplar schema-following evidence (the prompt supplies a near-
  exact `assign_all` exemplar with a single solution, and the model
  reproduces the shape). They establish that the model can comply with a
  fully specified schema when one is given, and that the new parser accepts
  every compliant output.

### 5.4 Provider trace-shape validation (stored adversarial)

Re-parsed against the new parser:
- Total stored adversarial samples: **260** (140 positive, 120 adversarial)
- Positive samples that returned `TRACE_PARSED`: **140 / 140**
- Adversarial samples that returned `REJECT` (matching the expected
  structured bucket): **120 / 120**

### 5.5 Provider stepwise trace-shape diagnostic (NEW this freeze)

A new stepwise diagnostic was run as part of this freeze to characterize
behaviour on the *new* tagged-union justification contract and catch any
private-kernel-rule leakage.

- Diagnostic: `scripts/stage4_provider_stepwise.py`
- Output: `eval/gates/stage4_trace_parser/provider_stepwise/`
- Model: `deepseek/deepseek-v4-flash`
- Total samples: **36** across 3 scenarios (12 per scenario):
  - `stepwise_clue_only`: prompt restricts to `{clue, from?}` justifications.
  - `stepwise_bijection_or_clue`: prompt allows either form.
  - `stepwise_bijection_only`: prompt restricts to `{rule: bijection, from?}`.
- Source puzzle set: a deterministic subset of
  `eval/gates/stage2_gate_a_compile_all/compiled_problems.jsonl` covering
  multiple grid sizes (`2x3`, `2x4`, etc.).
- Sample counts:

  | Status | Count |
  |---|---|
  | `parsed` (`TRACE_PARSED`) | 20 |
  | `schema_rejected` | 13 |
  | `invalid_json` | 2 |
  | `provider_error` | 1 |

  Failure codes observed: `unknown_op` (13), `invalid_json` (2),
  `provider_error` (1).
- Private kernel rule name leakage: **0** out of 36 raw outputs. The
  prompt's explicit prohibition held; no model output contained one of the
  22 forbidden rule names.
- Status: **partial** (parseability is the only criterion). 20/36 = 55.5%
  parsed cleanly. The 13 `unknown_op` rejections are dominated by the
  model forgetting the `op` discriminator on some output objects — a
  known failure mode for the model under stepwise prompts, and *exactly*
  what Stage 4's `unknown_op` parse error is supposed to catch.

### 5.6 Validation commands

```bash
# Lean parser + walkthrough tests
~/.elan/bin/lake.exe build
~/.elan/bin/lake.exe test                # exit 0

# Python test suite (Stage 4 only — the dataset-dependent tests need
# data/zebralogic/, which lives outside the public tree)
uv run pytest tests/test_stage4_trace_parser.py -v   # 8 / 8 passed
uv run pytest tests/test_interfaces.py tests/test_compiler_cli.py \
                   tests/test_verifier_cli.py tests/test_packaging.py \
                   tests/test_dataset.py -v           # all passed

# Lint
uv run ruff check .                     # All checks passed

# Real differential schema/parser parity (122 entries, zero disagreements)
uv run pytest tests/test_stage4_trace_parser.py::test_frozen_trace_schema_validates_against_lean_parser -v

# Re-run the trace_parser_gate end-to-end against dataset-derived references
set -a; source .env; set +a
mkdir -p /tmp/stage4-run
uv run python -c "
import sys; sys.path.insert(0, 'src')
from sparseir_harness.trace_parser_gate import run_trace_parser_gate
from pathlib import Path
m = run_trace_parser_gate(
    Path('eval/gates/stage2_gate_a_compile_all'),
    Path('eval/gates/stage3a_reference_solutions'),
    Path('/tmp/stage4-run'),
    20260629,
)
assert m['status'] == 'pass' and m['total_traces'] == 3028
"
```

## 6. Known non-Stage-4 limitations (downstream, not Stage 4 failures)

These are not Stage 4 defects. They are recorded so the Stage 5 handoff is
explicit.

1. **Trace replay is not implemented.** `parse_trace` lowers a trace JSON
   into a `Trace` AST; nothing in the trusted code re-runs the ops, applies
   them to a checker state, localizes first-failure, or emits a checked
   artifact. That driver is Stage 5.
2. **`{clue/from} or {bijection/from} → internal kernel consequence-rule
   derivation is a Stage 5 task.** The kernel's 22 `supportedRules` are
   *private* to Lean and must never be supplied by the model. The bridge
   that infers which schema applies, given `(op, justify, currentState)`,
   is unbuilt.
3. **Stepwise G1 Lean↔clingo differential validation remains outstanding
   Stage 3 debt.** The candidate half of G1 (Mode 0 vs clingo) is closed.
   The stepwise half is still example-based, not clingo-fuzzed; it must
   be closed before Stage 5 replay is implemented, otherwise the Stage 5
   driver could certify unjustified steps. The stepwise public AST and the
   bijection-justification variant are Stage-4-ready for when that G1
   closure lands.
4. **`Pretty.lean` is still a stub.** `render_audit` returns
   `not_implemented`. The faithfulness argument relies on a Lean-rendered
   view being auditable by humans before compute; that surface is missing.
5. **Stepwise trust in `info`.** `stepwise: false` reflects reality; it
   should flip to `true` only after Stage 5 ships trace replay with a
   clingo-differentially validated kernel.
6. **Stage 5 driver should thread state server-side.** Until that lands,
   the public trace contract does not need to change, but the driver must
   not accept caller-supplied intermediate states (per the Stage 3 audit
   finding that motivated this whole seam).

## 7. What is *not* part of the Stage 4 freeze

- Any claim that a parsed trace is correct or that the puzzle is solved.
- Any claim that the model's reasoning is faithful to the original natural
  language puzzle.
- Any cost, capability, or comparative-model result.
- Modes 1/2, tactics, recursion, second backend, `Pretty.lean`.
- Parser-level validation that a `conclude` is present, is final, or is
  semantically valid (these are all Stage 5 / replay concerns and the
  parser explicitly does not enforce them).

These are preserved as future work in the spec but are explicitly *not*
advertised by the runtime capabilities.

## 8. Reproduce the freeze evidence

```bash
git checkout stage4-finish
~/.elan/bin/lake.exe build
~/.elan/bin/lake.exe test
uv run ruff check .
uv run pytest tests/test_stage4_trace_parser.py -v

# Inspect the committed raw counts (no re-run needed):
python -c "
import json
traces = [json.loads(l) for l in open('eval/gates/stage4_trace_parser/traces.jsonl')]
results = [json.loads(l) for l in open('eval/gates/stage4_trace_parser/results.jsonl')]
print('traces:', len(traces), '| results:', len(results))
print('all results match expected:', all(
    (t['expected_kind']=='TRACE_PARSED' and r['result']['kind']=='TRACE_PARSED') or
    (t['expected_kind']=='REJECT' and r['result']['kind']=='REJECT' and
     r['result']['failure']['failure_code']==t['expected_code'])
    for t, r in zip(traces, results)))
"
```

A `True` from the script plus all 8 Stage 4 pytests passing plus `ruff
check .` clean plus `lake test` exit 0 is the freeze predicate.

## 9. Stage handoff

```
Stage 4: frozen (this record)
Stage 3 stepwise G1 debt: open — must be closed before Stage 5 trust
Stage 5: not started (must not be considered trusted/frozen until the
         stepwise kernel has independent G1-style validation)
```
