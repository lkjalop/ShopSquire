# Queue and Autoscale Runbook

## Scope
This runbook covers queue-backed CV/LLM workers and autoscale guardrails introduced in runtime.

Primary code paths:
- `src/app/workers/rq_queue.py`
- `src/app/routers/jobs.py` (`GET /api/v1/jobs/health/queues`)
- `src/app/observability/metrics.py`
- `src/app/routers/cv.py`
- `src/app/routers/recommend.py`

## Environment Knobs
### Queue enablement
- `CV_ASYNC_QUEUE_ENABLED`
  - `1` enables async queue mode for CV analyze/upload paths.
  - Recommended prod default: `1`.
- `LLM_ASYNC_QUEUE_ENABLED`
  - `1` enables async queue mode for recommendation LLM summary jobs.
  - Recommended prod default: `1`.

### Redis/RQ
- `REDIS_URL`
  - Redis endpoint for RQ queues.
  - Recommended prod: managed Redis with persistence and HA.
- `RQ_JOB_TIMEOUT`
  - Job timeout in seconds.
  - Recommended prod default: `180`.

### Queue capacities
- `CV_RQ_MAXSIZE`
  - Max CV queue depth before dead-letter overflow.
  - Current default: `200`.
  - Recommended prod: `500` (raise to `1000` for peak-heavy tenants).
- `FRAUD_RQ_MAXSIZE`
  - Max fraud queue depth before dead-letter overflow.
  - Current default: `200`.
  - Recommended prod: `500`.
- `LLM_RQ_MAXSIZE`
  - Max LLM queue depth before dead-letter overflow.
  - Current default: `500`.
  - Recommended prod: `1500`.

### Autoscale hint thresholds
- `QUEUE_SCALE_UP_DEPTH`
  - Depth threshold used by queue health autoscale hints.
  - Current default: `100`.
  - Recommended prod: `200`.
- `QUEUE_SCALE_UP_AGE_SECONDS`
  - Oldest queued item age threshold for scale-up hints.
  - Current default: `30`.
  - Recommended prod: `45`.

### LLM worker job behavior
- `LLM_JOB_TIMEOUT_SECONDS`
  - Timeout for background non-streaming LLM job.
  - Current default: `8`.
  - Recommended prod: `10` to `15` depending on model latency profile.

## Metrics to Wire into HPA/KEDA
Use:
- `shopsquire_worker_queue_depth{queue="cv|llm|fraud"}`
- `shopsquire_worker_queue_oldest_age_seconds{queue="cv|llm|fraud"}`

Recommended scale-up policy:
- Scale up when either:
  - queue depth `>= 200`, or
  - oldest age `>= 45s`.

Recommended scale-down policy:
- Scale down only after:
  - depth `< 40` and
  - oldest age `< 10s`
  - sustained for at least 10 minutes.

## Endpoint for Operational Checks
- `GET /api/v1/jobs/health/queues`
  - Returns queue stats and autoscale hints.
  - Use this for dashboards and operational runbooks.

## Production Starting Point
Suggested initial worker replica counts:
- CV workers: `min=2`, `max=20`
- LLM workers: `min=2`, `max=30`
- Fraud workers: `min=1`, `max=10`

Suggested trigger targets:
- CV: depth per replica `25`, oldest age target `30s`
- LLM: depth per replica `50`, oldest age target `45s`
- Fraud: depth per replica `40`, oldest age target `45s`

## Alerting
Page on:
- oldest age `> 120s` for 10m on `cv` or `llm`
- dead-letter queue depth growing for 5m
- queue depth monotonic increase for 15m with maxed worker replicas

Ticket on:
- oldest age `> 60s` for 15m
- depth above scale threshold for 20m

## Failure and Degradation Policy
- If queue unavailable:
  - CV and LLM paths fall back to synchronous best-effort behavior.
- If LLM queue is saturated:
  - keep core recommendation output and omit summary text.
- If CV queue is saturated:
  - return accepted/queued only when enqueue succeeds; otherwise continue synchronous path or return controlled backpressure.

