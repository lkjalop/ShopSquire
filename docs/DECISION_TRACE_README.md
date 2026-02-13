Decision Trace Broker — README
=================================

Overview
--------
- The decision trace system streams live decision events to the frontend using an in-process fanout broker by default. For production scale and multi-process deployments a Redis Streams-backed broker is supported.

Modes
-----
- In-process: single-process, low-latency fanout. Works without Redis and is used during local dev and tests. No persistence across restarts.
- Redis Streams: set `TRACE_BROKER_REDIS_STREAM_ENABLED=1` and configure `REDIS_URL` to use Redis. Provides cross-process pub/sub and retention via Redis Streams.

Important env vars
------------------
- `TRACE_BROKER_REDIS_STREAM_ENABLED` — if `1` the broker will use Redis Streams; default is off (in-process). 
- `REDIS_URL` — e.g. `redis://localhost:6379/0` when using Redis Streams.
- `TEST_USE_DEMO_DECISION_TRACE` — when `1` enables dev-only endpoints to seed demo traces.
- `DECISION_DEBUG_ALLOW` — when `1` allows publishing debug events via `/decisions/{id}/events/debug` (dev use only).
- `DECISIONS_WS_MAX_PER_TRACE` and `DECISIONS_WS_MAX_GLOBAL` — connection limits for WS endpoints (optional hard limits).

Local run (dev)
----------------
1. Ensure venv is activated.
2. Start the app with a local SQLite DB and demo traces enabled:

```powershell
$env:DATABASE_URL = "sqlite+pysqlite:///C:/AI/ShopSquire/tmp/e2e.sqlite"
$env:TEST_USE_DEMO_DECISION_TRACE = "1"
$env:API_PORT = "8081"
& ".venv/Scripts/python.exe" -m uvicorn src.app.main:create_app --host 127.0.0.1 --port 8081 --factory
```

3. Seed a demo trace (dev only):

```powershell
Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:8081/api/v1/decisions/demo/seed' -ContentType 'application/json' -Body '{}'
```

4. Open the UI and load the `DecisionTrace` modal for the returned `trace_id`. The frontend will attempt WS -> SSE -> polling fallbacks.

Deployment notes
----------------
- For production multi-instance deployments enable Redis Streams and provide a managed Redis. This enables cross-process fanout and better durability.
- Secure the streaming endpoints: require API auth, RBAC, and per-IP rate limiting.
- Add Prometheus counters for WS connects/disconnects and SSE subscriber counts; these are lightweight and recommended to monitor resource usage.

Security
--------
- Demo and debug endpoints are gated by `TEST_USE_DEMO_DECISION_TRACE` and `DECISION_DEBUG_ALLOW`. Do not enable these in production.

Troubleshooting
---------------
- If streaming doesn't work in multi-process setups, ensure `TRACE_BROKER_REDIS_STREAM_ENABLED=1` and `REDIS_URL` are reachable.
- Use the `GET /api/v1/decisions/{trace_id}` endpoint to verify trace metadata and existence before connecting to WS/SSE.

Contact
-------
For questions about the decision trace subsystem, open an issue or ping the platform team.
