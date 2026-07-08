# Stage 3 stepwise G1 — design note

## What this gate compares

The gate tests the trusted Lean ``StepKernel`` against two independent clingo
oracles. The oracles encode only the structural bijection and per-house choice
constraints, plus the puzzle's clues, plus the partial ``StepState`` lowered
into ``at(C,V,H)`` facts. They deliberately do not re-implement any Lean rule
in Python.

## Why two oracles

A stepwise kernel can accept a step for two distinct reasons:

1. The step is **globally forced** by the puzzle and the current state. Every
   satisfying completion of the puzzle+state places the value in that house
   (for ``place``) or never places the value in that house (for ``eliminate``).
2. The cited justification is **locally sufficient** under the structural
   bijection and current state.

Global entailment is the blocking trust claim: if Lean accepts a step that is
not globally forced, Lean has emitted an unsound verdict over the puzzle.

Justification-local entailment is the *StepKernel-as-cited-rule-checker*
contract. The kernel is allowed to reject a globally entailed step if the
cited rule does not itself force the move. Therefore the differential gate
isolates those two questions and reports them separately.

## Oracles

### Global entailment

```text
Puzzle   = bijection base + all clues
State    = placed cells forced + non-placed cells enumerated over `possible`
Query    = base + state + forbid step atom
          place(item, house)   ⇒ forbid  at(item, house)
          eliminate(item, house) ⇒ forbid  not at(item, house)
Result   = UNSAT ⇒ globally forced; SAT ⇒ counterexample model recorded
```

### Justification-local entailment

```text
For clue-backed rules:
  Query  = bijection base + state + ONLY the single cited clue
For bijection rules:
  Query  = bijection base + state   (no cited clue)
Result   = same as global; reported alongside the global verdict per case
```

## Corpus

* **Gold**: the 1,000 rows of ``compiled_problems.jsonl`` re-emitted as
  ``schema_version 0.2`` problem.json files by the committed
  ``problem_fabricator``. No external ``data/zebralogic/source.json`` is
  required.
* **Fuzzed**: 10,000+ deterministically generated ZebraLogic puzzles built
  from a fixed RNG seed and the bounded CATEGORY_POOL / VALUE_POOL vocabularies.
  Each generated puzzle is checked against ``clingo`` (development-only oracle)
  via the gold ``check_candidate`` path so the gate trusts Lean for the verdict
  and clingo only as the differential semantic reference.

## Step proposals

The ``step_proposer`` enumerates place/eliminate steps over a SAT-consistent
partial state. It includes:

* singleton-cell and singleton-value bijection cases
* ``given_found_at_place`` and ``given_not_at_eliminate`` for unary clues
* place from placed partner for ``same_house``/``direct_left``/``direct_right``
* single-neighbor place and no-possible-neighbor eliminate for ``side_by_side``
* singleton-distance place and no-possible-partner eliminate for ``one_between``
  /``two_between``
* impossible-order eliminate for ``left_of`` / ``right_of``

The proposer does not filter for whether Lean would accept the step. Both
oracles decide the ground truth.

## What is excluded from the differential denominator

* Static / interface rejection codes (``malformed_step``, ``unknown_category``,
  ``unknown_value``, ``house_out_of_range``, ``unknown_clue_ref``,
  ``rule_clue_mismatch``, ``unsupported_rule``).
* Conclusion path (``solved_conclusion`` and ``contradiction_detection``) —
  these delegate to CheckerCore, not to a local place/eliminate rule.

These are deterministic StepKernel validation tests and remain covered by the
existing ``stage3c_step_kernel`` example gate. They are explicitly excluded
from the differential denominator here.

## Why the gate can fail closed

* Every ``ACCEPT_STEP`` is paired with a global entailment query. UNSAT is
  required; SAT triggers ``unsound_accept`` disagreement and freezes the
  counterexample model in ``counterexamples.jsonl``.
* Every supported local rule's verdict is paired with an independent clingo
  query that ignores the rest of the puzzle's clues. A disagreement freezes
  the case in ``disagreements.jsonl``.
* Inconsistent generated states (state_is_sat != sat) are recorded separately
  and discarded from the comparison corpus. They never inflate the
  ``unsound_accept`` count.
