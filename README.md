# SparseIR Lean

SparseIR is a Lean-first checked-reasoning pipeline. The v0 domain is
ZebraLogicBench logic-grid constraint satisfaction: an untrusted reasoner searches
for an assignment, while Lean checks supplied certificates and candidates.

## Trust boundary

Lean is the sole correctness judge. If Lean rejects a future certificate, trace,
or candidate, the pipeline rejects it. Python and Inspect AI are untrusted
orchestration: they may load data, invoke the Lean executable, retain raw outputs,
and compute metrics, but they must never make or override correctness decisions.

The development-only clingo integration is an independent `reference_only`
differential oracle. It validates the Lean checker during development and must
never be placed on the inference path. There is no Horn/ProofWriter checker and no
solver in the trusted Lean code.

Stage 1 adds direct, trusted Lean parsing of canonical Zebra `problem.json` files.
Static puzzle validation, candidate checking, trace parsing, and artifact emission
remain deliberately absent. The verifier reports no checking capabilities until
their later stage gates pass.

## Stage 2 static compiler

`SparseIRLean.Compiler.compile` turns a `ParsedProblem` into a frozen
`CompiledPuzzle`. Stage 1 is JSON-shape only; Stage 2 owns every semantic
static check. The compiler enforces envelope acceptance
(`schema_version`, `domain`), size match, category cardinality, distinct
values, declared categories/values, puzzle-relative house bounds (1..N), and
unique clue IDs — and never inspects `expect`, solves, or tests uniqueness.

Static errors carry a structured code, JSON path, and message and return
through the same `STATIC_ERROR` seam as parse errors:

```text
invalid_json
invalid_schema
unsupported_schema_version
invalid_domain
size_mismatch
category_size_mismatch
duplicate_value
unknown_category
unknown_value
house_out_of_range
duplicate_clue_id
```

The CLI exposes the compiler through the `compile` command:

```bash
jq -Rs '{protocol_version:"0.1.0",request_id:"compile",command:"compile",
  payload:{problem:.}}' < tests/problems/lgp-test-2x2-33.problem.json \
  | lake exe sparse-ir-lean
```

## Pinned tools

- Lean `4.30.0`, selected by `lean-toolchain`
- Python `>=3.11`, with dependencies locked by `uv.lock`
- Inspect AI `0.3.241`
- clingo `5.8.0` (development only)

Install Lean through [elan](https://github.com/leanprover/elan), then create the
Python environment:

```bash
uv sync --dev
```

No provider SDK is configured and the Stage 0 Inspect task explicitly uses no
model.

## Frozen interfaces

| Interface | Version | Source |
| --- | --- | --- |
| Canonical envelope | `0.2` | `schemas/problem-envelope.schema.json` |
| Zebra problem and parse errors | `0.2` | `schemas/zebra-problem.schema.json` |
| Dataset layout | `0.1.0` | `src/sparseir_harness/data/zebra/manifest.json` |
| Verifier subprocess protocol | `0.1.0` | `schemas/verifier-protocol.schema.json` |

The verifier transport is one JSON request on stdin and one JSON response on
stdout. Only `info` is implemented at the subprocess boundary. Every checking
command continues to fail closed with the frozen Stage 0 error until its own gate
passes; Stage 1 exposes parsing as the trusted Lean library functions
`parseProblem` and `parseProblemJson`, not as a static-compiler result.

```bash
printf '%s' '{"protocol_version":"0.1.0","request_id":"readme","command":"info"}' \
  | lake exe sparse-ir-lean

uv run python scripts/run_lean_verifier.py
```

Python parses the response only to route and record it; verdict semantics remain
owned by Lean.

## Dataset grounding

The Python package contains three unmodified public ZebraLogicBench records under
`src/sparseir_harness/data/zebra/` from the `grid_mode/test` split at 2x2, 4x4,
and 6x6. The frozen manifest retains the external ID, split, normalized grid size,
source revision, path, and SHA-256 for every record. `ATTRIBUTION.md` records source
and license information. The records are bundled into the wheel so the installed
dataset-checking entry point does not depend on a repository checkout.

Stage 2 Gate A additionally pins the complete 1,000-record `grid_mode/test`
Parquet shard under `data/zebralogic/`. The gate deterministically converts the
published ZebraLogic template vocabulary into Stage 1 problem files, compiles
every problem in Lean, and writes raw-source and compiled-view indexes for human
review:

```bash
uv run python scripts/stage2_gate_a_compile_all.py \
  --output eval/gates/stage2_gate_a_compile_all
```

The loader checks provenance and on-disk integrity only. It does not interpret
clues or judge solutions:

```bash
uv run sparseir-check-dataset
```

## Stage 1 parser boundary

`SparseIRLean.Json` parses the envelope, source metadata, positive raw size,
categories, all ten Zebra clue forms, and opaque `expect` JSON. Unknown fields are
rejected. Cross-reference validation, category cardinality/distinctness, clue-ID
uniqueness, and puzzle-relative house bounds belong to the Stage 2 static compiler
and are intentionally not parser decisions.

The parser fixtures in `tests/problems/` are derived from the three pinned public
records across 2x2, 4x4, and 6x6 grids. The published problem schema freezes the
accepted JSON shape, unknown-field policy, and structured parse-error codes.

## Checks

```bash
lake build
lake test
uv run pytest
uv run ruff check .
uv run python scripts/diff_oracle.py --external-id lgp-test-2x2-33
uv run inspect eval eval/inspect_tasks/stage0.py \
  --model none \
  --log-dir /tmp/sparseir-inspect-stage0
```

The Inspect dry run loads all pinned records and performs no generation or
provider call. Scored evaluations do not begin until the checker trust anchor has
passed its later differential gate.
