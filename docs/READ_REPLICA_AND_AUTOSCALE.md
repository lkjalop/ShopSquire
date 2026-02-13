# Read Replicas and Autoscale Notes

## Read routing
- Primary DB handles all writes.
- Read replica is optional via `READ_REPLICA_URL`.
- Enable routing with `READ_REPLICA_ENABLED=1`.
- Lag-aware fallback:
  - `READ_REPLICA_MAX_LAG_SECONDS` (default `2.0`)
  - If replica lag exceeds threshold, reads fail over to primary.

Implementation primitives live in:
- `src/app/services/db_read_routing.py`

Current usage:
- `GET /api/v1/decisions/query` can use replica when enabled.

## Autoscale guidance
- API pods:
  - Scale on CPU + in-flight requests + P95 latency.
- Worker pools:
  - Scale on queue depth and oldest message age.
- GPU CV pools:
  - Isolate heavy CV flows from API pods.
- LLM service:
  - Scale on token throughput + model latency.

## Degradation controls
- Keep non-critical enrichments optional under load.
- Preserve core decision + policy paths first.

## Runbook
- Detailed queue knobs, prod thresholds, and alert policy:
  - `docs/QUEUE_AUTOSCALE_RUNBOOK.md`
