# Stage 4 provider positive and adversarial parser validation

Status: **PASS**

- Model: `deepseek/deepseek-v4-flash`
- Total samples: 260
- Positive TRACE_PARSED: 140/140
- Adversarial expected rejections: 120/120
- Raw Lean outputs stored: 260/260
- Unexpected accepts: 0
- Unexpected rejections: 0
- Protocol errors: 0

This gate scores only trace syntax and requested parser rejection behavior. It does not
replay traces or evaluate semantic correctness, proof validity, candidates, or solved state.
