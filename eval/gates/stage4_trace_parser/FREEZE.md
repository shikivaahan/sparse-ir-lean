# Stage 4 freeze record

**Status:** FROZEN — public interface, parser, error taxonomy, and gate evidence
are stable. This stage measures *parseability only* (lower JSON → `Trace` AST
in the trusted Lean verifier). Replay, semantic stepwise checking, and artifact
emission are explicitly out of scope here.

**Date:** 2026-07-06
**Branch:** `stage4-finish` (PR #1)
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
(which runs both validators on every entry of the parity corpus, see §5.2).

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
- `audit_view: false` — `Pretty.lean` is a stub.

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
- Source fixtures (NOT clingo gold — see §5.7):
  `eval/gates/stage4_trace_parser/parser_fixtures/parser_fixture_solutions.jsonl`.

### 5.2 JSON Schema ↔ Lean parser differential parity

This is a real differential gate on a hand-curated boundary corpus. The
test
`tests/test_stage4_trace_parser.py::test_frozen_trace_schema_validates_against_lean_parser`
ingests every entry of `src/sparseir_harness/trace_parity_corpus.py` and
asserts that:

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

The parity corpus is committed at
`src/sparseir_harness/trace_parity_corpus.py` and the test is committed
at `tests/test_stage4_trace_parser.py::test_frozen_trace_schema_validates_against_lean_parser`.

This 122-case corpus is **separate evidence** from the per-provider-output
agreement recorded in §5.6. The corpus proves the two implementations
agree across the hand-curated boundary surface; the §5.6 numbers prove
they agree on actual model outputs from `deepseek/deepseek-v4-flash`.

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
  fully specified schema when one is given, and that the new parser
  accepts every compliant output.

### 5.4 Provider trace-shape validation (stored adversarial)

Re-parsed against the new parser:
- Total stored adversarial samples: **260** (140 positive, 120 adversarial)
- Positive samples that returned `TRACE_PARSED`: **140 / 140**
- Adversarial samples that returned `REJECT` (matching the expected
  structured bucket): **120 / 120**

### 5.5 Provider stepwise trace-shape diagnostic (NEW this freeze)

A new stepwise diagnostic was run as part of this freeze to characterize
behaviour on the *new* tagged-union justification contract and to catch
any private-kernel-rule leakage.

- Diagnostic script: `scripts/stage4_provider_stepwise.py`
- Stored evidence: `eval/gates/stage4_trace_parser/provider_stepwise/`
- Model: `deepseek/deepseek-v4-flash`
- Total samples attempted: **36**
- Source puzzle set: a deterministic subset of
  `eval/gates/stage2_gate_a_compile_all/compiled_problems.jsonl` covering
  multiple grid sizes (e.g. `2x3`, `2x4`).

Each provider output is independently evaluated on **four** layers:

1. `provider_output_present` — did the provider call return text?
2. `raw_json_valid` — does that text parse as JSON with a top-level object?
3. `schema_valid` — does that object satisfy `schemas/zebra-trace.schema.json`?
4. `lean_trace_parsed` — does it satisfy the trusted Lean `parse_trace`?

The script **actually runs both** the JSON Schema validator and the Lean
parser per sample (the 122-case hand-curated corpus is not used to infer
these counts). The per-sample verdict for each layer is recorded in
`analyze_results.jsonl`.

#### Per-layer counts (real evidence, denominators explicit)

| Layer | Count | Denominator | Rate |
|---|---|---|---|
| Samples attempted | 36 | — | — |
| Provider returned output | 35 | 36 attempted | 97.2% |
| Provider errors | 1 | 36 attempted | 2.8% |
| Raw JSON (top-level object) valid | 33 | 35 returned | **94.3%** |
| JSON Schema valid | 20 | 33 raw-JSON valid | **60.6%** |
| Lean `TRACE_PARSED` | 20 | 36 attempted | 55.6% |
| Lean `TRACE_PARSED` | 20 | 35 returned | 57.1% |
| **Schema↔Lean disagreement count** | **0** | 33 raw-JSON valid | agreement rate **100.0%** |

(Schema-valid and Lean-`TRACE_PARSED` agree exactly on every sample: 20/33
samples pass both, 13/33 fail both, 0 disagree.)

Status: **partial** — 20/35 returned outputs parse cleanly under both
validators (the remaining 15 fail schema and Lean simultaneously, mostly
on `unknown_op` because the model forgets the `op` discriminator on some
output objects). The point of the diagnostic is shape compliance and
private-rule leakage, not end-to-end solve correctness.

#### Failure codes observed (from Lean, on actual provider outputs)

| Code | Count |
|---|---|
| `unknown_op` | 13 |
| `invalid_json` | 2 (raw text was not JSON; Lean therefore had nothing to parse) |
| `provider_error` | 1 |
| `protocol_error` | 0 |

#### Private kernel rule name leakage

* Out of 35 raw outputs that returned text: **0** contain any of the 22
  forbidden private kernel rule names as substrings. The prompt's
  explicit prohibition held.

#### Scenarios

| Scenario | Samples | TRACE_PARSED | REJECT |
|---|---|---|---|
| `stepwise_clue_only` | 12 | 9 | 3 |
| `stepwise_bijection_or_clue` | 12 | 3 | 8 (+ 1 provider error) |
| `stepwise_bijection_only` | 12 | 8 | 4 |

### 5.6 Stored provider outputs reparse

Stored outputs from prior runs were re-parsed against the current parser
to confirm no regressions:

| Stored output set | Samples | Result against current parser |
|---|---|---|
| `provider_validation/raw_outputs.jsonl` | 140 | 140 / 140 `TRACE_PARSED` |
| `provider_adversarial/raw_outputs.jsonl` (full) | 260 | 140 positive `TRACE_PARSED`, 120 adversarial `REJECT` with expected codes |
| `provider_stepwise/raw_outputs.jsonl` | 36 | 20 `TRACE_PARSED` (analyzed per-layer in §5.5) |

The 120 adversarial rejections span **12 mutation classes × 10 outputs**
(missing ops, unknown op, unexpected top-level field, malformed
assign_all solution, missing justify, malformed justify, malformed
justify.from, bad conclude status, wrapper object, missing
schema_version, unsupported schema_version, missing problem_id).

### 5.7 Stage 4 parser fixtures — explicit provenance

The Stage 4 gate consumes:

* **Real ZebraLogic-derived compiled puzzles** from
  `eval/gates/stage2_gate_a_compile_all/compiled_problems.jsonl`
  (the audit-true puzzle surface).
* **Synthetic per-puzzle candidate assignments** from
  `eval/gates/stage4_trace_parser/parser_fixtures/parser_fixture_solutions.jsonl`.
  This file is regenerable via
  `scripts/make_stage4_parser_fixtures.py`.

These synthetic assignments:

* are **structurally valid** (`{"cat": {"house": value}}`), generated by
  value enumeration;
* are **NOT clingo gold**, **NOT semantically correct**, and make **no
  claim of puzzle solvability**;
* are owned exclusively by the Stage 4 parser gate;
* do not appear under `eval/gates/stage3a_reference_solutions/` or any
  name that could be confused with Stage 3A reference solutions.

The `parser_fixture_solutions_dir` parameter on
`run_trace_parser_gate` is named for clarity so it cannot be
accidentally swapped with Stage 3A's reference-solution input. The
Stage 3A reference-solution subsystem
(`src/sparseir_harness/reference_solutions.py`) is untouched.

### 5.8 Validation commands

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

# Re-run the trace_parser_gate end-to-end against the Stage-4-owned synthetic
# fixture path
set -a; source .env; set +a
uv run python -c "
import sys; sys.path.insert(0, 'src')
from sparseir_harness.trace_parser_gate import run_trace_parser_gate
from pathlib import Path
m = run_trace_parser_gate(
    Path('eval/gates/stage2_gate_a_compile_all'),
    Path('eval/gates/stage4_trace_parser/parser_fixtures'),
    Path('/tmp/stage4-run'),
    20260629,
)
assert m['status'] == 'pass' and m['total_traces'] == 3028
"

# Re-derive provider-output metrics from the already-stored raw_outputs.jsonl
# (no provider call; this re-runs both validators on each stored raw output)
uv run python scripts/stage4_provider_stepwise.py \
  --reanalyze-from eval/gates/stage4_trace_parser/provider_stepwise
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
   driver could certify unjustified steps.
4. **`Pretty.lean` is still a stub.**
5. **Stepwise trust in `info`.** `stepwise: false` reflects reality; it
   should flip to `true` only after Stage 5 ships trace replay with a
   clingo-differentially validated kernel.
6. **Stage 5 driver should thread state server-side.** Until that lands,
   the public trace contract does not need to change, but the driver must
   not accept caller-supplied intermediate states.

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
