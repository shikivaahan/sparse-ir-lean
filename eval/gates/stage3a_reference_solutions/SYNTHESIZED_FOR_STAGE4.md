# Synthetic Stage 4 reference solutions

These `reference_solutions.jsonl` are **synthesized for the Stage 4 re-freeze
evidence pass**, not gold solutions from clingo / Stage 3A. They are derived
by enumeration from the real ZebraLogic-derived compiled problems in
`eval/gates/stage2_gate_a_compile_all/compiled_problems.jsonl` (one solution
per problem, values enumerated in order, repeating if there are more houses
than category values).

Stage 4 only checks *trace structure* (JSON schema parity, parse-error
taxonomy, public justification contract). A structurally valid full-candidate
trace is sufficient to exercise the parser end-to-end across grid sizes;
semantic correctness is a Stage 5 / replay concern.

If real clingo-derived gold solutions are required for downstream Stage 4
work, regenerate via the Stage 3A reference-solutions gate against the
ZebraLogic dataset (see `scripts/stage3a_reference_solutions.py`).
