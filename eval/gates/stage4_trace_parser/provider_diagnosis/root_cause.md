# Stage 4 provider root cause

## Proven cause

- `prompt_contract_mismatch`: the original system prompt named semantic operations but never
  specified the required `ops`, `op`, and operation payload keys and supplied no exemplar.
- `provider_added_extra_fields`: all baseline outputs used `operations` at `$.operations`;
  nested objects also used variants such as `type`, `assignment`, or `assignments`.
- `scorer_bug`: the original reporter labeled 0/3 schema-valid as `complete` instead of `fail`.

The unexpected baseline paths were: ["$.operations", "$.operations[0].assignment", "$.operations[0].assignments", "$.operations[0].solution", "$.operations[0].type", "$.operations[1].status", "$.operations[1].type"]. Removing only those
unexpected fields did not make the output valid; normalized reparses produced
["missing_ops", "missing_ops", "missing_ops"] because the required `ops` field was still absent.

## Ruled out

- The extracted top-level objects were the intended trace objects, not wrappers.
- The original prompt did not contain `operations`, `type`, `assignment`, or `assignments`.
- The protocol schema documents `parse_trace` and `TRACE_PARSED` but contains no conflicting
  trace-input shape, and no repository schema or prompt example uses the old field names.
- The Lean parser matches the Stage 4 trace contract and remained unchanged.
- The corrected prompt exemplar parses through Lean `parse_trace`.
- No reasoning mode or reasoning-trace request was used.

## Fix

The provider prompt now gives exact allowed keys, a Lean-validated exemplar, and explicit
raw-object/no-wrapper requirements. Reporting now uses `fail` for zero schema-valid outputs,
`partial` for mixed results, and `pass` only when every requested sample is schema-valid.
