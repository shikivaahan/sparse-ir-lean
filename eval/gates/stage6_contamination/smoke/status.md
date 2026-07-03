# stage6_contamination status

- state: complete (9-row guardrail passed; one unreturned 6x6 request interrupted after 15 minutes)
- model/budget: `deepseek/deepseek-v4-flash`, reasoning 24000, request max 32768
- completed: 9/9 durable rows
- examples/min: 0.81
- elapsed: 11.1 min
- ETA: 0.0 min
- workers: 8
- malformed: 0
- clue violations: 1
- provider/rate-limit errors: 0/0
- truncation/finish_reason issues: 0; {'stop': 9}
- reasoning_tokens health: 9/9 positive; median 2556
- cost estimate: $0.019932
