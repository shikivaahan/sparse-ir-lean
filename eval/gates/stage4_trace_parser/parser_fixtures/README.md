# parser_fixture_solutions.jsonl — Stage 4 synthetic parser fixtures

**Generator:** `scripts/make_stage4_parser_fixtures.py` (regenerable on demand)
**Source artifact:** `eval/gates/stage2_gate_a_compile_all/compiled_problems.jsonl`

## What this is

Per-puzzle candidate assignments used to drive the Stage 4 trace-parser gate's
`full_candidate` and `stepwise` trace generators across grid sizes. They are
intentionally minimal and exist ONLY so the Stage 4 gate can exercise the
parser end-to-end on real ZebraLogic-derived compiled puzzles.

## Provenance

* **Synthetic.** Values are enumerated from the category value list in
  order, repeating if a category has fewer values than houses. The result
  is structurally valid (`{"cat": {"house": value}}`) but is NOT a solution
  to the puzzle.
* **Not clingo gold.** No ASP encoding, no `solve_problem()` invocation,
  no reference-solution subsystem.
* **Semantic correctness is not claimed.** The Stage 4 parser checks
  trace structure, not whether the assignment solves the puzzle. These
  fixtures are sufficient for that.
* **Stage 3A reference-solution provenance is unaffected.** This file is
  owned by the Stage 4 parser gate only. It must not appear under
  `eval/gates/stage3a_reference_solutions/` or any similar name.

## How it is used

`src/sparseir_harness/trace_parser_gate.run_trace_parser_gate` reads
`parser_fixture_solutions.jsonl` from a caller-supplied directory. The
argument is named `parser_fixture_solutions_dir` for clarity. Only the
Stage 4 parser gate consumes these.

## Regeneration

```bash
set -a; source .env; set +a
uv run python scripts/make_stage4_parser_fixtures.py \
  --compiled-problems eval/gates/stage2_gate_a_compile_all/compiled_problems.jsonl \
  --output eval/gates/stage4_trace_parser/parser_fixtures/parser_fixture_solutions.jsonl
```

The source artifact has its own audit story from Stage 2 Gate A and is the
single point of truth for the puzzle surface this fixture covers.
