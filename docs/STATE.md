# Operational State

Last updated: 2026-06-29.

## Current state

- Branch: `stage3-stepwise-g1-closure`, with the full Stage 3 stepwise G1
  closure staged for PR. Stage 4 PR #1 merged; repo-hygiene / CI PR merged and
  public CI is green.
- Implementation: Stages 0 through 3 complete. Full-candidate and stepwise checker
  paths are implemented and their evidence gates pass.
- Active stage: Stage 3 complete. Do not start Stage 4 or Stage 6 in this turn.
- Frozen interfaces: canonical envelope `0.2`, dataset layout `0.1.0`, verifier
  subprocess protocol `0.1.0`, Stage 1 parser, Stage 2 static compiler, and the
  Stage 4 public trace contract `parse_trace`.
- Gate A: PASS; 1,000/1,000 real ZebraLogic problems compiled.
- Gate A audit: PASS; zero findings across source, ingested, and compiled rows.
- Gate B: PASS; 27/27 deterministic malformed problems rejected correctly.
- Gate B+: PASS; 22,042/22,042 fuzz mutations rejected and 2,495/2,495 valid
  controls compiled.
- Gate C provider smoke: PASS; OpenRouter, Inspect, raw-output retention, and the
  Lean classification loop worked end to end.
- Gate C deferred issue: error-seeking tasks need task-compliance scoring so an
  ignored requested mutation is `provider_task_noncompliance`, not ordinary
  `COMPILED`. This is non-blocking for Lean/Stage 3A, but Gate C provider metrics
  must not be relied on until it is patched.
- Stage 3A checker gate: all constructed candidate and clue cases receive the
  expected Lean verdict, with all ten clue types and requested invariant errors.
- Stage 3A reference gate: PASS; 1,000/1,000 Gate A problems attempted,
  1,000 clingo solutions, 1,000 unique, 1,000 stored reference solutions, and
  1,000 Lean `ACCEPT_SOLVED` results. Zero nonunique, UNSAT, timeout, clingo
  error, Lean reject, or protocol error cases across all 25 grids.
- Source `expect.source_solution` rows remain blank and unused. Generated
  solutions are explicitly clingo reference-only and `trusted_for_runtime=false`.
- Stage 3B differential gate: PASS; 10,000/10,000 complete bijective candidates
  checked by both Lean and clingo. The 1,000 references were accepted by both;
  all 9,000 mutations were clue violations in both. Zero disagreements and zero
  protocol errors across all 25 grids, six mutation families, and all ten target
  clue types.
- Stage 3C stepwise-kernel gate: PASS; 22/22 supported local rules, 14/14
  rejection codes, and 10/10 clue types covered across 37 deterministic real-
  problem-derived cases. Zero deferred rules, failures, or protocol errors.
- Stage 3 stepwise G1 closure gate: PASS — closes the missing stepwise half of
  G1 with two independent clingo oracles (global and justification-local).
  139,846 SAT-consistent step queries across 1,000 gold + 10,000 fuzzed
  puzzles (all 25 grids). Zero unsound Lean accepts over the full corpus.
  Zero Lean↔clingo local-rule differential disagreements over the 18 supported
  place/eliminate consequence rules and all ten clue families. Headline
  metrics, design note, and per-rule/per-clue counts live in
  `eval/gates/stage3_stepwise_g1/`.
- Stage 3 status: COMPLETE. The Mode 0 verifier path is ready through
  `check_candidate`; the scored Mode 0 evaluation harness belongs to Stage 6 and
  has not started.
- Verification: `lake build`, `lake test`, 159+ pytest tests, Ruff, lock check,
  and diff check all pass.
- Stage 2 evidence: local ignored `stage_reports/STAGE2.md`.

## Stage boundary

Stage 2 status: COMPLETE for the static compiler/typechecker.

Stage 2 proves that real ZebraLogic `problem.json` files compile, the ingested
dataset corresponds to real source rows, malformed problem certificates receive
stable Lean error codes and useful paths, broad fuzzing found no static false
accepts or false rejects, and provider-produced problem JSON can be classified by
Lean diagnostics.

Stage 2 does not prove that any solution or candidate assignment is correct, any
reasoning trace is valid, any model reasoned in SparseIR, any Mode 0/1/2 result
works, realistic NL/source-to-problem faithfulness, or reliable provider
task-compliance metrics for error-seeking prompts.

## Private context status

`spec.md`, `docs/`, and `stage_reports/` remain locally excluded through
`.git/info/exclude`, untracked, and absent from reachable history. They must not
be committed.

## Next action

Stage 3 is complete. Stage 4 trace JSON parsing is next under the roadmap. The
user may instead explicitly prioritize the Stage 6 scored Mode 0 harness, but it
has not started. Do not begin either without a new task.
