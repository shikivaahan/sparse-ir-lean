# Stage 4 provider adversarial examples

## valid_assign_all

```json
{
  "sample_id": "valid_assign_all-000",
  "bucket": "valid_assign_all",
  "adversarial": false,
  "model_complied": true,
  "passed": true,
  "score": {
    "passed": true,
    "model_complied": true,
    "expected_result": "TRACE_PARSED",
    "expected_code": null,
    "expected_path": null,
    "actual_kind": "TRACE_PARSED",
    "actual_code": null,
    "actual_path": null
  },
  "lean_result": {
    "kind": "TRACE_PARSED",
    "op_count": 2,
    "problem_id": "zl_stage4_valid_assign_all_000",
    "trace_style": "full_candidate"
  }
}
```

## valid_place

```json
{
  "sample_id": "valid_place-000",
  "bucket": "valid_place",
  "adversarial": false,
  "model_complied": true,
  "passed": true,
  "score": {
    "passed": true,
    "model_complied": true,
    "expected_result": "TRACE_PARSED",
    "expected_code": null,
    "expected_path": null,
    "actual_kind": "TRACE_PARSED",
    "actual_code": null,
    "actual_path": null
  },
  "lean_result": {
    "kind": "TRACE_PARSED",
    "op_count": 2,
    "problem_id": "zl_stage4_valid_place_000",
    "trace_style": "stepwise"
  }
}
```

## valid_eliminate

```json
{
  "sample_id": "valid_eliminate-000",
  "bucket": "valid_eliminate",
  "adversarial": false,
  "model_complied": true,
  "passed": true,
  "score": {
    "passed": true,
    "model_complied": true,
    "expected_result": "TRACE_PARSED",
    "expected_code": null,
    "expected_path": null,
    "actual_kind": "TRACE_PARSED",
    "actual_code": null,
    "actual_path": null
  },
  "lean_result": {
    "kind": "TRACE_PARSED",
    "op_count": 2,
    "problem_id": "zl_stage4_valid_eliminate_000",
    "trace_style": "stepwise"
  }
}
```

## valid_conclude

```json
{
  "sample_id": "valid_conclude-000",
  "bucket": "valid_conclude",
  "adversarial": false,
  "model_complied": true,
  "passed": true,
  "score": {
    "passed": true,
    "model_complied": true,
    "expected_result": "TRACE_PARSED",
    "expected_code": null,
    "expected_path": null,
    "actual_kind": "TRACE_PARSED",
    "actual_code": null,
    "actual_path": null
  },
  "lean_result": {
    "kind": "TRACE_PARSED",
    "op_count": 1,
    "problem_id": "zl_stage4_valid_conclude_000",
    "trace_style": "stepwise"
  }
}
```

## valid_justify

```json
{
  "sample_id": "valid_justify-000",
  "bucket": "valid_justify",
  "adversarial": false,
  "model_complied": true,
  "passed": true,
  "score": {
    "passed": true,
    "model_complied": true,
    "expected_result": "TRACE_PARSED",
    "expected_code": null,
    "expected_path": null,
    "actual_kind": "TRACE_PARSED",
    "actual_code": null,
    "actual_path": null
  },
  "lean_result": {
    "kind": "TRACE_PARSED",
    "op_count": 2,
    "problem_id": "zl_stage4_valid_justify_000",
    "trace_style": "stepwise"
  }
}
```

## valid_justify_from

```json
{
  "sample_id": "valid_justify_from-000",
  "bucket": "valid_justify_from",
  "adversarial": false,
  "model_complied": true,
  "passed": true,
  "score": {
    "passed": true,
    "model_complied": true,
    "expected_result": "TRACE_PARSED",
    "expected_code": null,
    "expected_path": null,
    "actual_kind": "TRACE_PARSED",
    "actual_code": null,
    "actual_path": null
  },
  "lean_result": {
    "kind": "TRACE_PARSED",
    "op_count": 2,
    "problem_id": "zl_stage4_valid_justify_from_000",
    "trace_style": "stepwise"
  }
}
```

## valid_mixed_trace

```json
{
  "sample_id": "valid_mixed_trace-000",
  "bucket": "valid_mixed_trace",
  "adversarial": false,
  "model_complied": true,
  "passed": true,
  "score": {
    "passed": true,
    "model_complied": true,
    "expected_result": "TRACE_PARSED",
    "expected_code": null,
    "expected_path": null,
    "actual_kind": "TRACE_PARSED",
    "actual_code": null,
    "actual_path": null
  },
  "lean_result": {
    "kind": "TRACE_PARSED",
    "op_count": 3,
    "problem_id": "zl_stage4_valid_mixed_trace_000",
    "trace_style": "stepwise"
  }
}
```

## missing_ops

```json
{
  "sample_id": "missing_ops-000",
  "bucket": "missing_ops",
  "adversarial": true,
  "model_complied": true,
  "passed": true,
  "score": {
    "passed": true,
    "model_complied": true,
    "expected_result": "parse_rejection",
    "expected_code": "missing_ops",
    "expected_path": "$.ops",
    "actual_kind": "REJECT",
    "actual_code": "missing_ops",
    "actual_path": "$.ops"
  },
  "lean_result": {
    "failure": {
      "failure_code": "missing_ops",
      "message": "missing required field 'ops'",
      "path": "$.ops",
      "status": "malformed_trace"
    },
    "kind": "REJECT"
  }
}
```

## unknown_op

```json
{
  "sample_id": "unknown_op-000",
  "bucket": "unknown_op",
  "adversarial": true,
  "model_complied": true,
  "passed": true,
  "score": {
    "passed": true,
    "model_complied": true,
    "expected_result": "parse_rejection",
    "expected_code": "unknown_op",
    "expected_path": "$.ops[0].op",
    "actual_kind": "REJECT",
    "actual_code": "unknown_op",
    "actual_path": "$.ops[0].op"
  },
  "lean_result": {
    "failure": {
      "failure_code": "unknown_op",
      "message": "unknown operation 'guess'",
      "path": "$.ops[0].op",
      "status": "malformed_trace"
    },
    "kind": "REJECT"
  }
}
```

## unexpected_top_level_field

```json
{
  "sample_id": "unexpected_top_level_field-000",
  "bucket": "unexpected_top_level_field",
  "adversarial": true,
  "model_complied": true,
  "passed": true,
  "score": {
    "passed": true,
    "model_complied": true,
    "expected_result": "parse_rejection",
    "expected_code": "unexpected_field",
    "expected_path": "$.extra",
    "actual_kind": "REJECT",
    "actual_code": "unexpected_field",
    "actual_path": "$.extra"
  },
  "lean_result": {
    "failure": {
      "failure_code": "unexpected_field",
      "message": "unexpected field 'extra'",
      "path": "$.extra",
      "status": "malformed_trace"
    },
    "kind": "REJECT"
  }
}
```

## malformed_assign_all_solution

```json
{
  "sample_id": "malformed_assign_all_solution-000",
  "bucket": "malformed_assign_all_solution",
  "adversarial": true,
  "model_complied": true,
  "passed": true,
  "score": {
    "passed": true,
    "model_complied": true,
    "expected_result": "parse_rejection",
    "expected_code": "assign_all_malformed_solution",
    "expected_path": "$.ops[0].solution",
    "actual_kind": "REJECT",
    "actual_code": "assign_all_malformed_solution",
    "actual_path": "$.ops[0].solution"
  },
  "lean_result": {
    "failure": {
      "failure_code": "assign_all_malformed_solution",
      "message": "expected an object",
      "path": "$.ops[0].solution",
      "status": "malformed_trace"
    },
    "kind": "REJECT"
  }
}
```

## missing_justify

```json
{
  "sample_id": "missing_justify-000",
  "bucket": "missing_justify",
  "adversarial": true,
  "model_complied": true,
  "passed": true,
  "score": {
    "passed": true,
    "model_complied": true,
    "expected_result": "parse_rejection",
    "expected_code": "missing_justify",
    "expected_path": "$.ops[0].justify",
    "actual_kind": "REJECT",
    "actual_code": "missing_justify",
    "actual_path": "$.ops[0].justify"
  },
  "lean_result": {
    "failure": {
      "failure_code": "missing_justify",
      "message": "missing required field 'justify'",
      "path": "$.ops[0].justify",
      "status": "malformed_trace"
    },
    "kind": "REJECT"
  }
}
```

## malformed_justify

```json
{
  "sample_id": "malformed_justify-000",
  "bucket": "malformed_justify",
  "adversarial": true,
  "model_complied": true,
  "passed": true,
  "score": {
    "passed": true,
    "model_complied": true,
    "expected_result": "parse_rejection",
    "expected_code": "malformed_justify",
    "expected_path": "$.ops[0].justify",
    "actual_kind": "REJECT",
    "actual_code": "malformed_justify",
    "actual_path": "$.ops[0].justify"
  },
  "lean_result": {
    "failure": {
      "failure_code": "malformed_justify",
      "message": "expected an object",
      "path": "$.ops[0].justify",
      "status": "malformed_trace"
    },
    "kind": "REJECT"
  }
}
```

## malformed_justify_from

```json
{
  "sample_id": "malformed_justify_from-000",
  "bucket": "malformed_justify_from",
  "adversarial": true,
  "model_complied": true,
  "passed": true,
  "score": {
    "passed": true,
    "model_complied": true,
    "expected_result": "parse_rejection",
    "expected_code": "malformed_from_cell",
    "expected_path": "$.ops[0].justify.from",
    "actual_kind": "REJECT",
    "actual_code": "malformed_from_cell",
    "actual_path": "$.ops[0].justify.from"
  },
  "lean_result": {
    "failure": {
      "failure_code": "malformed_from_cell",
      "message": "expected an array",
      "path": "$.ops[0].justify.from",
      "status": "malformed_trace"
    },
    "kind": "REJECT"
  }
}
```

## bad_conclude_status

```json
{
  "sample_id": "bad_conclude_status-000",
  "bucket": "bad_conclude_status",
  "adversarial": true,
  "model_complied": true,
  "passed": true,
  "score": {
    "passed": true,
    "model_complied": true,
    "expected_result": "parse_rejection",
    "expected_code": "conclude_bad_status",
    "expected_path": "$.ops[0].status",
    "actual_kind": "REJECT",
    "actual_code": "conclude_bad_status",
    "actual_path": "$.ops[0].status"
  },
  "lean_result": {
    "failure": {
      "failure_code": "conclude_bad_status",
      "message": "expected status 'solved'",
      "path": "$.ops[0].status",
      "status": "malformed_trace"
    },
    "kind": "REJECT"
  }
}
```

## wrapper_object

```json
{
  "sample_id": "wrapper_object-000",
  "bucket": "wrapper_object",
  "adversarial": true,
  "model_complied": true,
  "passed": true,
  "score": {
    "passed": true,
    "model_complied": true,
    "expected_result": "parse_rejection",
    "expected_code": "unexpected_wrapper_object",
    "expected_path": "$.trace",
    "actual_kind": "REJECT",
    "actual_code": "unexpected_field",
    "actual_path": "$.trace"
  },
  "lean_result": {
    "failure": {
      "failure_code": "unexpected_field",
      "message": "unexpected field 'trace'",
      "path": "$.trace",
      "status": "malformed_trace"
    },
    "kind": "REJECT"
  }
}
```

## missing_schema_version

```json
{
  "sample_id": "missing_schema_version-000",
  "bucket": "missing_schema_version",
  "adversarial": true,
  "model_complied": true,
  "passed": true,
  "score": {
    "passed": true,
    "model_complied": true,
    "expected_result": "parse_rejection",
    "expected_code": "missing_schema_version",
    "expected_path": "$.schema_version",
    "actual_kind": "REJECT",
    "actual_code": "missing_schema_version",
    "actual_path": "$.schema_version"
  },
  "lean_result": {
    "failure": {
      "failure_code": "missing_schema_version",
      "message": "missing required field 'schema_version'",
      "path": "$.schema_version",
      "status": "malformed_trace"
    },
    "kind": "REJECT"
  }
}
```

## unsupported_schema_version

```json
{
  "sample_id": "unsupported_schema_version-000",
  "bucket": "unsupported_schema_version",
  "adversarial": true,
  "model_complied": true,
  "passed": true,
  "score": {
    "passed": true,
    "model_complied": true,
    "expected_result": "parse_rejection",
    "expected_code": "unsupported_schema_version",
    "expected_path": "$.schema_version",
    "actual_kind": "REJECT",
    "actual_code": "unsupported_schema_version",
    "actual_path": "$.schema_version"
  },
  "lean_result": {
    "failure": {
      "failure_code": "unsupported_schema_version",
      "message": "expected trace schema version 0.2",
      "path": "$.schema_version",
      "status": "malformed_trace"
    },
    "kind": "REJECT"
  }
}
```

## missing_problem_id

```json
{
  "sample_id": "missing_problem_id-000",
  "bucket": "missing_problem_id",
  "adversarial": true,
  "model_complied": true,
  "passed": true,
  "score": {
    "passed": true,
    "model_complied": true,
    "expected_result": "parse_rejection",
    "expected_code": "missing_problem_id",
    "expected_path": "$.problem_id",
    "actual_kind": "REJECT",
    "actual_code": "missing_problem_id",
    "actual_path": "$.problem_id"
  },
  "lean_result": {
    "failure": {
      "failure_code": "missing_problem_id",
      "message": "missing required field 'problem_id'",
      "path": "$.problem_id",
      "status": "malformed_trace"
    },
    "kind": "REJECT"
  }
}
```
