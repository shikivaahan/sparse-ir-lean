# Concurrency probe

Per-model worker-count probe, run before the full eval.

## qwen3-8b (`qwen/qwen3-8b`)

| workers | n | coverage | provider_err | rate_limit | truncation | malformed | reason_pos | tput ex/min | avg_lat_s | elapsed_s | timed_out |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 6 | 15 | 0.0% | 15 | 15 | 0 | 15 | 0 | 542.9 | 0.11 | 1.7 | False |

**Chosen workers:** 2 (fallback, all probed unstable)

Rejected:
- workers=6: 15 rate-limit (429) errors; 15 provider errors

## qwen3-32b (`qwen/qwen3-32b`)

| workers | n | coverage | provider_err | rate_limit | truncation | malformed | reason_pos | tput ex/min | avg_lat_s | elapsed_s | timed_out |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 6 | 8 | 100.0% | 0 | 0 | 0 | 0 | 8 | 5.3 | 11.25 | 90.0 | True |
| 12 | 13 | 92.3% | 0 | 0 | 0 | 0 | 13 | 8.7 | 6.92 | 90.0 | True |
| 24 | 11 | 90.9% | 0 | 0 | 0 | 0 | 11 | 7.3 | 8.18 | 90.0 | True |

**Chosen workers:** 12

## v4-flash-baseline (`deepseek/deepseek-v4-flash`)

| workers | n | coverage | provider_err | rate_limit | truncation | malformed | reason_pos | tput ex/min | avg_lat_s | elapsed_s | timed_out |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 6 | 12 | 91.7% | 0 | 0 | 0 | 0 | 11 | 8.0 | 7.50 | 90.0 | True |
| 12 | 12 | 100.0% | 0 | 0 | 0 | 0 | 12 | 8.0 | 7.50 | 90.0 | True |
| 24 | 13 | 92.3% | 0 | 0 | 0 | 0 | 13 | 8.7 | 6.92 | 90.0 | True |

**Chosen workers:** 24
