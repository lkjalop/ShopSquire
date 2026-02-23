**Demo: Decision Trace & NLP→Agent Interaction**

- **Goal:** produce repeatable traces and decision logs showing NLP-driven agent actions, storage in `decision_logs`, and trace links for Jaeger/OTel.
- **Prereqs:** Python venv activated, project installed dependencies, and optionally a Jaeger instance listening on UDP port 6831 (local docker `jaegertracing/all-in-one`).

Quick steps:

1) Activate venv in PowerShell:

```
& .venv/Scripts/Activate.ps1
```

2) Run the setup script to seed DB and start the API on port 8080:

```
.
.\scripts\demo_setup_and_run.ps1
```

3) Wait ~5–10s for startup, then run the demo flows:

```
.\scripts\demo_flows.ps1
```

What this does:
- Seeds demo customers, products, orders, decisions and security events into `tmp/demo.sqlite`.
- Starts `uvicorn` with tracing enabled (environment: `JAEGER_ENABLED=1`, `JAEGER_HOST=localhost`, `JAEGER_PORT=6831`). If Jaeger isn't running, spans fall back to console exporter.
- The demo flows call `recommend/suggest` and `pricing/suggest` which exercise NLP rerank and orchestrator paths that call `log_decision` to persist evidence.

Viewing results:
- Decision rows: admin UI at `/ui/decisions` or API `/api/v1/admin/decisions`.
- Traces: Jaeger UI (http://localhost:16686) when Jaeger is running. The frontend widget links to `http://localhost:16686/trace/<trace_id>` when trace IDs are included in responses.
- Audit/retention: the repo's `config/feature_flags.json` is updated for demo with `DECISION_LOG_WRITES_ENABLED=true`, `LOG_DETAIL_LEVEL=standard` and `SECURITY_EVENT_PERSIST_CONTENT=true`.

Notes & next steps:
- If you want traces to appear in Jaeger, run Jaeger locally:

```
docker run --rm -p 16686:16686 -p 6831:6831/udp jaegertracing/all-in-one:latest
```

- For live LLM behavior, configure `OLLAMA` locally or set `OPENAI_API_KEY` / `OPENAI_API_BASE` per `src/app/services/llm.py`.
- To change retention/detail, edit `config/feature_flags.json` and restart the server.
