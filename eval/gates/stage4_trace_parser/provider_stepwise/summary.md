# Stage 4 provider stepwise trace-shape diagnostic

Status: **PARTIAL** (parseability only)

- Model: `deepseek/deepseek-v4-flash`
- Samples attempted: 36
- Provider returned output: 35/36
- Provider errors: 1
- Raw JSON (top-level object) valid: 33/35 (94.3%)
- JSON Schema valid: 20/33 (60.6%)
- Lean TRACE_PARSED: 20/36 (55.6% of attempted; 57.1% of returned)
- Schema<->Lean disagreements (on actual provider outputs): 0
- Private kernel rule name leakage (raw-output substring scan): 0

Each provider output is independently evaluated on four layers:
provider call -> raw JSON -> JSON Schema -> Lean parse_trace.
Trace validity claims are DENOMINATED on the layer above them, not on `samples attempted`. The 122-case `src/sparseir_harness/trace_parity_corpus.py` is separate hand-curated evidence and does not prove provider-output parity; this script's `schema_lean_disagreement_count` is the per-output evidence.
