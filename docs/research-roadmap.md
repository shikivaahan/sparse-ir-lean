# Research status and roadmap

[Home](../README.md) · [Architecture](architecture.md) · [Experiments](experiments.md) · [Verification](verification.md) · [Reproduction](reproduction.md) · [Roadmap](research-roadmap.md)

## Contributions so far

This repository currently contributes:

1. A Lean-checked complete-candidate verification path for ZebraLogic certificates.
2. A provider-backed Mode-0 evaluation showing that Lean acceptance can be a stronger commit signal than model self-confidence.
3. A capability, difficulty, and reasoning ON/OFF analysis showing that checkable errors appear where models have lower capability, face harder grids, or lack reasoning compute.
4. A label-free evaluation discipline: raw provider outputs are retained before parsing, while Lean verdicts and failure modes are recorded before aggregate scoring.
5. An experiment-hygiene case study: an earlier dramatic result was traced to output truncation and removed as the headline.

## Research map

Mode 0 is not the full SparseIR thesis. It is the first narrow slice: a model emits a complete candidate, and Lean decides whether that candidate can be committed.

The larger project asks whether models can reason in compact, checkable SparseIR operations, whether Lean feedback can repair failures efficiently, and whether typed certificates make the remaining semantic gap easier for humans to audit.

| Area | Question | Current status |
|---|---|---|
| Verification / abstention | Can Lean turn complete-but-wrong answers into abstentions? | Preliminary Mode-0 support |
| Model confidence | Is self-reported confidence a good enough commit signal? | Preliminary evidence says no; stronger uncertainty baselines remain |
| Difficulty scaling | Does checker value appear where models have lower capability, reasoning is OFF, or grids are harder? | Preliminary descriptive support |
| SparseIR-native reasoning | Do models reason better or more cheaply in SparseIR traces than free-text CoT? | Untested |
| Verifier feedback | Do first-failure or stepwise Lean reports repair failures better than best-of-N? | Untested |
| Parser faithfulness | Does natural language to certificate translation preserve the intended task? | Untested; current results use gold certificates |
| Human audit | Do people catch certificate misframings, and does a “verified” label cause over-trust? | Untested |
| Cost efficiency | Does a cheap model plus Lean beat frontier reasoning at fixed precision? | Untested |
| Tactics / recursion | Do high-level tactics or checked subproblem reuse reduce cost? | Untested |
| Swappable verifier backend | Can the checker interface support Lean or another verified or specialized backend without changing the evaluation harness? | Designed in the spec; v0 uses Lean only |
| Model self-check | Can a model's own self-verification approximate the checker closely enough to become useful as a baseline or fallback signal? | Untested; not trusted for commits in v0 |

The larger architecture is checker-interface-first, not necessarily Lean-only forever. v0 uses Lean as the only trusted backend, but the spec defines a backend contract so the harness can eventually route the same abstract operations to another trusted checker. Such a backend would need deterministic verdicts, a clear result vocabulary, and its own validation gate before it could produce committed results. Model self-check is different: it may become a useful comparison, fallback, or calibration signal if models improve, but it is not equivalent to a trusted checker and cannot replace Lean as the commit judge in v0.

This README reports a checked selective-prediction result, not the completed SparseIR architecture.

## What would weaken this direction?

The current thesis would become less interesting if:

- stronger uncertainty baselines matched Lean's risk-coverage operating point;
- Mode-1 or Mode-2 feedback failed to improve coverage over simple best-of-N resampling at matched cost;
- harder frontier-scale instances produced mostly malformed or hedged failures rather than complete, checkable wrong candidates;
- human audit of trusted certificate renderings failed to improve detection of parser misframings.

## Immediate next experiment

The next decisive experiment is **Mode 1 vs best-of-N** on the same model, puzzle split, and total token budget:

- Mode-0 best-of-N samples multiple complete grids and accepts the first one Lean verifies;
- Mode 1 replays a trace, returns Lean's first-failure report, and gives the model one budget-matched repair opportunity.

This tests whether verifier feedback adds useful information beyond rejection sampling. It requires the trace parser/replay seam and first-failure protocol to be completed first.

## Next steps

1. Build trace replay and the first-failure protocol on top of the frozen Stage 4 trace-parser contract (`SparseIRLean/Trace.lean`), then run Mode-1 and Mode-2 repair experiments against blind resampling, with matched budgets.
2. Close the stepwise semantic-validation gap against an independent reference.
3. Build the trusted `Pretty.lean` audit renderer and evaluate human detection of certificate mistranslations and automation complacency.
4. Move beyond ≤6-house ZebraLogic to measure the residual tail on instances that challenge frontier models.
5. Compare against stronger uncertainty baselines with multiple seeds.
6. Only then measure end-to-end cost, including parsing, checking, retries, abstentions, and frontier baselines.
