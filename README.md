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

Stage 0 establishes interfaces and dataset grounding only. Problem parsing,
candidate checking, trace parsing, and artifact emission are deliberately absent.
The verifier reports no checking capabilities until later stage gates pass.

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

## Frozen Stage 0 interfaces

| Interface | Version | Source |
| --- | --- | --- |
| Canonical envelope | `0.2` | `schemas/problem-envelope.schema.json` |
| Dataset layout | `0.1.0` | `src/sparseir_harness/data/zebra/manifest.json` |
| Verifier subprocess protocol | `0.1.0` | `schemas/verifier-protocol.schema.json` |

The verifier transport is one JSON request on stdin and one JSON response on
stdout. At Stage 0, only `info` is implemented. Every checking command fails closed
with `STATIC_ERROR/not_implemented_stage_0`.

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

The loader checks provenance and on-disk integrity only. It does not interpret
clues or judge solutions:

```bash
uv run sparseir-check-dataset
```

## Stage 0 checks

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
