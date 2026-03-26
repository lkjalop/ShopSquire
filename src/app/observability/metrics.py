from typing import Optional
import os
import ipaddress
from fastapi import APIRouter, Request
from fastapi.responses import Response
from prometheus_client import Counter, Histogram, Gauge, generate_latest, REGISTRY
cb_state_gauge = Gauge(
    "shopsquire_circuit_breaker_state",
    "Circuit breaker state (0=closed,1=open)",
    labelnames=["service"],
)

token_budget_used_total = Counter(
    "shopsquire_token_budget_used_total",
    "Total tokens recorded against budget",
    labelnames=["tier", "endpoint"],
)

rate_limit_exceeded_total = Counter(
    "shopsquire_rate_limit_exceeded_total",
    "Rate limit or budget exceeded events",
    labelnames=["endpoint", "reason"],
)

incident_alerts_total = Counter(
    "shopsquire_incident_alerts_total",
    "Incident alerts emitted",
    labelnames=["topic", "severity"],
)

tickets_created_total = Counter(
    "shopsquire_tickets_created_total",
    "Tickets created",
    labelnames=["topic", "priority"],
)

pricing_latency_seconds = Histogram(
    "shopsquire_pricing_latency_seconds",
    "Latency of pricing suggest endpoint",
)

chaos_injected_total = Counter(
    "shopsquire_chaos_injected_total",
    "Chaos latency injections",
    labelnames=["latency_ms"],
)

chaos_errors_total = Counter(
    "shopsquire_chaos_errors_total",
    "Chaos error injections",
    labelnames=["endpoint"],
)

decisions_events_counter = Counter(
    "shopsquire_decision_events_total",
    "Decision lifecycle events emitted",
)

ui_actions_total = Counter(
    "shopsquire_ui_actions_total",
    "UI actions emitted",
    labelnames=["action"],
)

control_failures_total = Counter(
    "shopsquire_control_failures_total",
    "Compliance control failures detected",
    labelnames=["control"],
)

http_requests_total = Counter(
    "shopsquire_http_requests_total",
    "Total HTTP requests",
    labelnames=["method", "path", "status"],
)

http_request_duration_seconds = Histogram(
    "shopsquire_http_request_duration_seconds",
    "HTTP request latency in seconds",
    labelnames=["method", "path"],
)

inflight_requests_gauge = Gauge(
    "shopsquire_inflight_requests",
    "Current in-flight requests",
    labelnames=["service"],
)

db_query_duration_seconds = Histogram(
    "shopsquire_db_query_duration_seconds",
    "Database query latency in seconds",
    labelnames=["op"],
)

security_events_total = Counter(
    "shopsquire_security_events_total",
    "Security events emitted",
    labelnames=["event_type", "severity", "category"],
)

tool_invocations_total = Counter(
    "shopsquire_tool_invocations_total",
    "Tool invocations",
    labelnames=["tool", "status"],
)

tool_invocation_duration_seconds = Histogram(
    "shopsquire_tool_invocation_duration_seconds",
    "Tool invocation latency in seconds",
    labelnames=["tool"],
)

mcp_security_blocks_total = Counter(
    "shopsquire_mcp_security_blocks_total",
    "MCP tool invocations blocked for security",
    labelnames=["tool", "reason"],
)

complaint_triage_total = Counter(
    "shopsquire_complaint_triage_total",
    "Complaint triage events",
    labelnames=["intent", "severity"],
)

webhook_verifications_total = Counter(
    "shopsquire_webhook_verifications_total",
    "Webhook signature verifications",
    labelnames=["vendor", "status"],
)


webhook_deliveries_total = Counter(
    "shopsquire_webhook_deliveries_total",
    "Webhooks enqueued for delivery",
    labelnames=["url"],
)

webhook_delivery_failures_total = Counter(
    "shopsquire_webhook_delivery_failures_total",
    "Webhook delivery failures",
    labelnames=["url"],
)

webhook_delivery_retries_total = Counter(
    "shopsquire_webhook_delivery_retries_total",
    "Webhook delivery retries",
    labelnames=["url"],
)

webhook_delivery_dlq_total = Counter(
    "shopsquire_webhook_delivery_dlq_total",
    "Webhooks moved to DLQ",
    labelnames=["url"],
)

webhook_delivery_success_total = Counter(
    "shopsquire_webhook_delivery_success_total",
    "Successful webhook deliveries",
    labelnames=["url", "tenant"],
)

webhook_delivery_latency_seconds = Histogram(
    "shopsquire_webhook_delivery_latency_seconds",
    "Webhook delivery latency in seconds",
    labelnames=["url", "tenant"],
)

# ---------------------------------------------------------------------------
# IT-MON-02 — Insider threat observability counters
# ---------------------------------------------------------------------------

insider_threat_signals_total = Counter(
    "shopsquire_insider_threat_signals_total",
    "Insider threat signals emitted by the detection engine",
    labelnames=["signal_type", "severity", "actor_hash"],
)

audit_chain_verifications_total = Counter(
    "shopsquire_audit_chain_verifications_total",
    "Audit chain integrity verification results",
    labelnames=["result"],   # valid | tampered | error
)

privileged_actions_total = Counter(
    "shopsquire_privileged_actions_total",
    "Privileged (owner/developer/admin) actions recorded",
    labelnames=["role", "path", "off_hours"],   # off_hours: true | false
)


email_security_verdict_total = Counter(
    "shopsquire_email_security_verdict_total",
    "Email security verdicts by severity",
    labelnames=["tenant_id", "severity"],
)

email_security_ticket_total = Counter(
    "shopsquire_email_security_ticket_total",
    "Email security tickets created",
    labelnames=["tenant_id", "severity"],
)

email_security_ticket_rate_limited_total = Counter(
    "shopsquire_email_security_ticket_rate_limited_total",
    "Email security ticket rate-limits hit",
    labelnames=["tenant_id"],
)

email_security_dedupe_drop_total = Counter(
    "shopsquire_email_security_dedupe_drop_total",
    "Email security ticket dedupe drops",
    labelnames=["tenant_id"],
)

email_security_connector_events_total = Counter(
    "shopsquire_email_security_connector_events_total",
    "Email connector ingested events",
    labelnames=["tenant_id", "provider"],
)

email_security_connector_failures_total = Counter(
    "shopsquire_email_security_connector_failures_total",
    "Email connector failures",
    labelnames=["tenant_id", "provider", "reason"],
)

email_security_routes_total = Counter(
    "shopsquire_email_security_routes_total",
    "Email security routing outcomes",
    labelnames=["tenant_id", "route", "escalation"],
)

email_security_false_positives_total = Counter(
    "shopsquire_email_security_false_positives_total",
    "Posthoc false-positive outcomes for security decisions",
    labelnames=["tenant_id", "outcome"],
)

linked_artifact_fetch_total = Counter(
    "shopsquire_linked_artifact_fetch_total",
    "Linked artifact fetch outcomes for QR and attachment destinations",
    labelnames=["tenant_id", "status", "source"],
)

linked_artifact_verdict_total = Counter(
    "shopsquire_linked_artifact_verdict_total",
    "Linked artifact branded verdict outcomes",
    labelnames=["tenant_id", "verdict"],
)

linked_artifact_unresolved_total = Counter(
    "shopsquire_linked_artifact_unresolved_total",
    "Linked artifact destinations that remained unresolved",
    labelnames=["tenant_id", "reason"],
)

security_handoff_total = Counter(
    "shopsquire_security_handoff_total",
    "Security middleware handoff attempts",
    labelnames=["target", "status"],
)

email_enrichment_latency_seconds = Histogram(
    "shopsquire_email_enrichment_latency_seconds",
    "Email IOC enrichment latency in seconds",
    labelnames=["provider"],
)

email_detonation_latency_seconds = Histogram(
    "shopsquire_email_detonation_latency_seconds",
    "Email URL/attachment detonation latency in seconds",
    labelnames=["provider"],
)

decision_trace_write_failures_total = Counter(
    "shopsquire_decision_trace_write_failures_total",
    "Decision trace write failures",
    labelnames=["stage"],
)

alertmanager_test_last_ts = Gauge(
    "shopsquire_alertmanager_test_last_ts",
    "Unix timestamp of last AlertManager test alert sent",
)


def record_incident_alert(topic: str, severity: str):
    incident_alerts_total.labels(topic=topic, severity=severity).inc()


def record_ticket(topic: str, priority: str):
    tickets_created_total.labels(topic=topic, priority=priority).inc()


def record_pricing_latency(seconds: float):
    pricing_latency_seconds.observe(seconds)


def record_control_failure(control_id: str):
    if control_id:
        control_failures_total.labels(control=control_id).inc()


def record_http_metrics(method: str, path: str, status: int, duration_seconds: float):
    http_requests_total.labels(method=method, path=path, status=str(status)).inc()
    http_request_duration_seconds.labels(method=method, path=path).observe(duration_seconds)


def record_db_query_latency(op: str, duration_seconds: float):
    db_query_duration_seconds.labels(op=op or "unknown").observe(duration_seconds)


def record_security_event(event_type: str, severity: str, category: str):
    security_events_total.labels(
        event_type=event_type or "unknown",
        severity=severity or "info",
        category=category or "none",
    ).inc()


def record_tool_invocation(tool: str, status: str, duration_seconds: float):
    tool_invocations_total.labels(tool=tool or "unknown", status=status or "unknown").inc()
    tool_invocation_duration_seconds.labels(tool=tool or "unknown").observe(duration_seconds)


def record_mcp_security_block(tool: str, reason: str):
    mcp_security_blocks_total.labels(tool=tool or "unknown", reason=reason or "unknown").inc()


def record_webhook_verification(vendor: str, status: str):
    webhook_verifications_total.labels(vendor=vendor or "unknown", status=status or "unknown").inc()


def record_webhook_delivery(url: str):
    try:
        webhook_deliveries_total.labels(url=str(url or "unknown")).inc()
    except Exception:
        pass


def record_webhook_delivery_failure(url: str):
    try:
        webhook_delivery_failures_total.labels(url=str(url or "unknown")).inc()
    except Exception:
        pass


def record_webhook_delivery_retry(url: str):
    try:
        webhook_delivery_retries_total.labels(url=str(url or "unknown")).inc()
    except Exception:
        pass


def record_webhook_delivery_dlq(url: str):
    try:
        webhook_delivery_dlq_total.labels(url=str(url or "unknown")).inc()
    except Exception:
        pass


def record_webhook_delivery_success(url: str, tenant: str | None = None, latency_s: float | None = None):
    try:
        webhook_delivery_success_total.labels(url=str(url or "unknown"), tenant=str(tenant or "global")).inc()
        if latency_s is not None:
            webhook_delivery_latency_seconds.labels(url=str(url or "unknown"), tenant=str(tenant or "global")).observe(float(latency_s))
    except Exception:
        pass


def record_complaint_triage(intent: str, severity: str):
    complaint_triage_total.labels(intent=intent or "unknown", severity=severity or "unknown").inc()


def record_email_security_verdict(tenant_id: str | None, severity: str):
    email_security_verdict_total.labels(tenant_id=str(tenant_id or "global"), severity=str(severity or "info")).inc()


def record_email_security_ticket(tenant_id: str | None, severity: str):
    email_security_ticket_total.labels(tenant_id=str(tenant_id or "global"), severity=str(severity or "info")).inc()


def record_email_security_rate_limited(tenant_id: str | None):
    email_security_ticket_rate_limited_total.labels(tenant_id=str(tenant_id or "global")).inc()


def record_email_security_dedupe_drop(tenant_id: str | None):
    email_security_dedupe_drop_total.labels(tenant_id=str(tenant_id or "global")).inc()


def record_email_security_connector_event(tenant_id: str | None, provider: str):
    email_security_connector_events_total.labels(tenant_id=str(tenant_id or "global"), provider=str(provider or "unknown")).inc()


def record_email_security_connector_failure(tenant_id: str | None, provider: str, reason: str):
    email_security_connector_failures_total.labels(
        tenant_id=str(tenant_id or "global"),
        provider=str(provider or "unknown"),
        reason=str(reason or "unknown"),
    ).inc()


def record_email_security_route(tenant_id: str | None, route: str | None, escalation: str | None):
    email_security_routes_total.labels(
        tenant_id=str(tenant_id or "global"),
        route=str(route or "auto_resolve"),
        escalation=str(escalation or "none"),
    ).inc()


def record_email_security_false_positive(tenant_id: str | None, outcome: str | None):
    email_security_false_positives_total.labels(
        tenant_id=str(tenant_id or "global"),
        outcome=str(outcome or "unknown"),
    ).inc()


def record_linked_artifact_fetch(tenant_id: str | None, status: str | None, source: str | None):
    linked_artifact_fetch_total.labels(
        tenant_id=str(tenant_id or "global"),
        status=str(status or "unknown"),
        source=str(source or "unknown"),
    ).inc()


def record_linked_artifact_verdict(tenant_id: str | None, verdict: str | None):
    linked_artifact_verdict_total.labels(
        tenant_id=str(tenant_id or "global"),
        verdict=str(verdict or "Needs Review"),
    ).inc()


def record_linked_artifact_unresolved(tenant_id: str | None, reason: str | None):
    linked_artifact_unresolved_total.labels(
        tenant_id=str(tenant_id or "global"),
        reason=str(reason or "unknown"),
    ).inc()


def record_security_handoff(target: str | None, status: str | None):
    security_handoff_total.labels(
        target=str(target or "unknown"),
        status=str(status or "unknown"),
    ).inc()


def record_email_enrichment_latency(provider: str | None, latency_seconds: float):
    try:
        email_enrichment_latency_seconds.labels(provider=str(provider or "unknown")).observe(float(latency_seconds))
    except Exception:
        pass


def record_email_detonation_latency(provider: str | None, latency_seconds: float):
    try:
        email_detonation_latency_seconds.labels(provider=str(provider or "unknown")).observe(float(latency_seconds))
    except Exception:
        pass


def record_decision_trace_write_failure(stage: str | None):
    decision_trace_write_failures_total.labels(stage=str(stage or "unknown")).inc()


def record_alertmanager_test():
    alertmanager_test_last_ts.set_to_current_time()


ragas_evaluations_total = Counter(
    "shopsquire_ragas_evaluations_total",
    "RAGAS evaluations recorded",
    labelnames=["result"],
)


def record_ragas_eval(result: str = "ok"):
    ragas_evaluations_total.labels(result=result or "ok").inc()

# Baseline and moving-average gauges for RAGAS quality
ragas_baseline_gauge = Gauge(
    "shopsquire_ragas_baseline",
    "RAGAS baseline score (avg of faithfulness+recall)",
)

ragas_quality_avg_gauge = Gauge(
    "shopsquire_ragas_quality_avg",
    "RAGAS moving average score (recent window)",
)


def set_ragas_baseline(score: float):
    try:
        ragas_baseline_gauge.set(float(score))
    except Exception:
        pass


def set_ragas_quality_avg(score: float):
    try:
        ragas_quality_avg_gauge.set(float(score))
    except Exception:
        pass


def record_cb_state(service: str, is_open: bool):
    cb_state_gauge.labels(service=service or "unknown").set(1 if is_open else 0)


def record_token_budget_usage(tier: str, endpoint: str, tokens: int):
    try:
        token_budget_used_total.labels(tier=tier or "unknown", endpoint=endpoint or "unknown").inc(int(tokens or 0))
    except Exception:
        pass


def record_rate_limit_exceeded(endpoint: str, reason: str):
    try:
        rate_limit_exceeded_total.labels(endpoint=endpoint or "unknown", reason=reason or "unknown").inc()
    except Exception:
        pass


def record_chaos_error(endpoint: str):
    try:
        chaos_errors_total.labels(endpoint=endpoint or "unknown").inc()
    except Exception:
        pass


exceptions_total = Counter(
    "shopsquire_exceptions_total",
    "Unhandled exceptions caught by global handler",
    labelnames=["endpoint"],
)


def record_exception(endpoint: str):
    try:
        exceptions_total.labels(endpoint=endpoint or "unknown").inc()
    except Exception:
        pass


def record_inflight(service: str, value: int):
    try:
        inflight_requests_gauge.labels(service=service or "unknown").set(int(value))
    except Exception:
        pass


router = APIRouter(prefix="", tags=["metrics"])


def _is_non_local_env() -> bool:
    env = str(os.getenv("APP_ENV", "local") or "local").strip().lower()
    return env not in ("local", "dev", "development", "test", "testing")


def _client_ip(request: Request) -> str:
    xff = str(request.headers.get("x-forwarded-for") or "").strip()
    if xff:
        return xff.split(",")[0].strip()
    return str(request.client.host if request and request.client else "")


def _ip_allowed(ip_text: str) -> bool:
    if not ip_text:
        return False
    try:
        ip_obj = ipaddress.ip_address(ip_text)
    except Exception:
        return False
    cidrs = str(os.getenv("METRICS_ALLOW_CIDRS", "127.0.0.1/32,::1/128,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16") or "")
    for c in [x.strip() for x in cidrs.split(",") if x.strip()]:
        try:
            if ip_obj in ipaddress.ip_network(c, strict=False):
                return True
        except Exception:
            continue
    return False


@router.get("/metrics")
def metrics(request: Request) -> Response:
    # CRIT-09: Enforce auth and IP restriction.
    # Defaults to secure in all non-local environments.
    # Three auth paths (checked in order):
    #   1. IP allowlist — for Prometheus scrapers on trusted internal networks
    #   2. METRICS_BEARER_TOKEN env — for Prometheus scrape jobs that send a
    #      bearer token (set scrape_config.bearer_token in prometheus.yml)
    #   3. ShopSquire API role (owner/developer) via x-api-key or Authorization
    default_secure = "1" if _is_non_local_env() else "0"
    require_auth = str(os.getenv("METRICS_REQUIRE_AUTH", default_secure)).lower() in ("1", "true", "yes")
    restrict_ip  = str(os.getenv("METRICS_INTERNAL_ONLY", default_secure)).lower() in ("1", "true", "yes")
    client_ip = _client_ip(request)

    # Path 1: IP allowlist
    if restrict_ip and _ip_allowed(client_ip):
        # Trusted internal IP — serve full metrics without further checks
        raw = generate_latest(REGISTRY)
        return Response(raw, media_type="text/plain; version=0.0.4; charset=utf-8")

    if restrict_ip and not _ip_allowed(client_ip):
        # IP restriction active, client not on allowlist — check other auth paths
        # Path 2: dedicated bearer token for Prometheus scraper
        metrics_token = str(os.getenv("METRICS_BEARER_TOKEN", "") or "").strip()
        if metrics_token:
            auth_header = str(request.headers.get("Authorization", "") or "").strip()
            import hmac as _hmac
            expected = f"Bearer {metrics_token}"
            if _hmac.compare_digest(auth_header.encode(), expected.encode()):
                raw = generate_latest(REGISTRY)
                return Response(raw, media_type="text/plain; version=0.0.4; charset=utf-8")
        # Fall through to role-based auth below
        if require_auth:
            pass  # role check will handle 401 below
        else:
            return Response(b"forbidden\n", status_code=403, media_type="text/plain")

    raw = generate_latest(REGISTRY).decode("utf-8", errors="ignore")
    # Determine role from API key or Authorization header (best-effort)
    try:
        from src.app.security.auth import get_role_from_key, get_role_from_bearer, ROLE_OWNER, ROLE_DEVELOPER, ROLE_MERCHANT
    except Exception:
        get_role_from_key = None
        get_role_from_bearer = None
        ROLE_OWNER = ROLE_DEVELOPER = ROLE_MERCHANT = None

    role = None
    try:
        if get_role_from_key is not None:
            role = get_role_from_key(request.headers.get("x-api-key"))
    except Exception:
        role = None
    if not role and get_role_from_bearer is not None:
        try:
            role = get_role_from_bearer(request.headers.get("Authorization"))
        except Exception:
            role = None

    if require_auth and role not in (ROLE_OWNER, ROLE_DEVELOPER, ROLE_MERCHANT):
        return Response(b"unauthorized\n", status_code=401, media_type="text/plain")

    # Owner/developer see full metrics
    if role in (ROLE_OWNER, ROLE_DEVELOPER):
        return Response(raw.encode("utf-8"), media_type="text/plain; version=0.0.4; charset=utf-8")

    # Merchant or unauthenticated: apply strict tenant scoping
    tenant_header = request.headers.get("x-tenant-id")
    # Env-driven redaction still honored; when set, tenant metrics are always redacted
    if os.getenv("REDACT_TENANT_METRICS", "0") == "1":
        allow_tenant = None
    else:
        allow_tenant = tenant_header if role == ROLE_MERCHANT and tenant_header else None

    tenant_metrics = {
        "shopsquire_cv_provider_latency_tenant_seconds",
        "shopsquire_fraud_provider_latency_tenant_seconds",
    }

    lines = []
    for ln in raw.splitlines():
        s = ln.strip()
        # Remove HELP/TYPE blocks for tenant-scoped metrics unless explicitly allowed.
        if (s.startswith("# HELP") or s.startswith("# TYPE")) and any(m in s for m in tenant_metrics):
            if not allow_tenant:
                continue
            lines.append(ln)
            continue

        if any(m in s for m in tenant_metrics):
            if allow_tenant:
                if f'tenant="{allow_tenant}"' in s or f"tenant={allow_tenant}" in s:
                    lines.append(ln)
                else:
                    continue
            else:
                continue
        else:
            lines.append(ln)

    if not allow_tenant:
        # Final safeguard: ensure tenant-scoped metric names are absent from the
        # exposition output (including HELP/TYPE blocks).
        lines = [ln for ln in lines if not any(m in ln for m in tenant_metrics)]

    filtered = "\n".join(lines)
    return Response(filtered.encode("utf-8"), media_type="text/plain; version=0.0.4; charset=utf-8")


def record_ui_action(action: str):
    try:
        ui_actions_total.labels(action=action or "unknown").inc()
    except Exception:
        pass

# -------------------- AB Testing Metrics --------------------

ab_assignments_total = Counter(
    "shopsquire_ab_assignments_total",
    "AB test assignments",
    labelnames=["variant"],
)

_ab_variant_counts: dict[str, int] = {"A": 0, "B": 0}

ab_decision_quality_total = Counter(
    "shopsquire_ab_decision_quality_total",
    "AB decision quality outcomes by variant",
    labelnames=["variant", "outcome"],
)

ab_decision_quality_score = Histogram(
    "shopsquire_ab_decision_quality_score",
    "AB decision quality score distribution (0..1)",
    labelnames=["variant"],
)

ab_decision_quality_avg = Gauge(
    "shopsquire_ab_decision_quality_avg",
    "Running average AB decision quality score",
    labelnames=["variant"],
)

agent_feature_toggle_used_total = Counter(
    "shopsquire_agent_feature_toggle_used_total",
    "Feature toggle usage by feature/state",
    labelnames=["feature", "state"],
)

_ab_quality_snapshot: dict[str, dict[str, float]] = {
    "A": {"count": 0.0, "score_sum": 0.0},
    "B": {"count": 0.0, "score_sum": 0.0},
}


def record_ab_assignment(variant: str):
    try:
        v = (variant or "A").upper()
        ab_assignments_total.labels(variant=v).inc()
        try:
            _ab_variant_counts[v] = _ab_variant_counts.get(v, 0) + 1
        except Exception:
            pass
    except Exception:
        pass


def record_feature_toggle_used(feature: str, enabled: bool):
    try:
        agent_feature_toggle_used_total.labels(feature=feature or "unknown", state=("enabled" if enabled else "disabled")).inc()
    except Exception:
        pass


def record_ab_decision_quality(variant: str, score: float, outcome: str):
    try:
        v = (variant or "A").upper()
        s = max(0.0, min(1.0, float(score or 0.0)))
        o = str(outcome or "unknown")
        ab_decision_quality_total.labels(variant=v, outcome=o).inc()
        ab_decision_quality_score.labels(variant=v).observe(s)
        snap = _ab_quality_snapshot.setdefault(v, {"count": 0.0, "score_sum": 0.0})
        snap["count"] = float(snap.get("count", 0.0)) + 1.0
        snap["score_sum"] = float(snap.get("score_sum", 0.0)) + s
        avg = snap["score_sum"] / max(1.0, snap["count"])
        ab_decision_quality_avg.labels(variant=v).set(avg)
    except Exception:
        pass


@router.get("/observability/ab_snapshot")
def ab_snapshot():
    try:
        return {"A": _ab_variant_counts.get("A", 0), "B": _ab_variant_counts.get("B", 0)}
    except Exception:
        return {"A": 0, "B": 0}


@router.get("/observability/ab_quality_snapshot")
def ab_quality_snapshot():
    try:
        out: dict[str, dict[str, float]] = {}
        for variant, vals in (_ab_quality_snapshot or {}).items():
            c = float(vals.get("count", 0.0))
            out[variant] = {
                "count": c,
                "score_avg": (float(vals.get("score_sum", 0.0)) / max(1.0, c)) if c > 0 else 0.0,
            }
        a = out.get("A", {}).get("score_avg", 0.0)
        b = out.get("B", {}).get("score_avg", 0.0)
        out["compare"] = {
            "baseline_variant": "A",
            "delta_b_minus_a": float(b) - float(a),
            "ratio_b_over_a": (float(b) / max(1e-9, float(a))) if float(a) > 0 else 0.0,
        }
        return out
    except Exception:
        return {"A": {"count": 0.0, "score_avg": 0.0}, "B": {"count": 0.0, "score_avg": 0.0}, "compare": {"baseline_variant": "A", "delta_b_minus_a": 0.0, "ratio_b_over_a": 0.0}}

# -------------------- Recommendation LTR Metrics --------------------

recommend_rerank_total = Counter(
    "shopsquire_recommend_rerank_total",
    "Recommendation rerank requests by mode",
    labelnames=["mode"],
)

recommend_rerank_latency_seconds = Histogram(
    "shopsquire_recommend_rerank_latency_seconds",
    "Recommendation rerank latency in seconds",
    labelnames=["mode"],
)

recommend_ndcg_proxy = Histogram(
    "shopsquire_recommend_ndcg_proxy",
    "Proxy nDCG quality for recommendation reranking",
    labelnames=["mode"],
)

recommend_recall_proxy = Histogram(
    "shopsquire_recommend_recall_proxy",
    "Proxy recall@k quality for recommendation reranking",
    labelnames=["mode"],
)

_recommend_snapshot: dict[str, dict[str, float]] = {
    "heuristic": {"count": 0.0, "latency_s_sum": 0.0, "ndcg_sum": 0.0, "recall_sum": 0.0},
    "ltr": {"count": 0.0, "latency_s_sum": 0.0, "ndcg_sum": 0.0, "recall_sum": 0.0},
}


def record_recommendation_rerank(mode: str, latency_s: float, ndcg_proxy_val: float, recall_proxy_val: float):
    try:
        m = str(mode or "heuristic").lower()
        recommend_rerank_total.labels(mode=m).inc()
        recommend_rerank_latency_seconds.labels(mode=m).observe(float(latency_s))
        recommend_ndcg_proxy.labels(mode=m).observe(float(ndcg_proxy_val))
        recommend_recall_proxy.labels(mode=m).observe(float(recall_proxy_val))
        row = _recommend_snapshot.setdefault(m, {"count": 0.0, "latency_s_sum": 0.0, "ndcg_sum": 0.0, "recall_sum": 0.0})
        row["count"] = float(row.get("count", 0.0)) + 1.0
        row["latency_s_sum"] = float(row.get("latency_s_sum", 0.0)) + float(latency_s)
        row["ndcg_sum"] = float(row.get("ndcg_sum", 0.0)) + float(ndcg_proxy_val)
        row["recall_sum"] = float(row.get("recall_sum", 0.0)) + float(recall_proxy_val)
    except Exception:
        pass


def get_recommendation_snapshot() -> dict:
    out: dict[str, dict[str, float]] = {}
    try:
        for mode, vals in (_recommend_snapshot or {}).items():
            c = max(1.0, float(vals.get("count", 0.0)))
            out[mode] = {
                "count": float(vals.get("count", 0.0)),
                "latency_s_avg": float(vals.get("latency_s_sum", 0.0)) / c,
                "ndcg_proxy_avg": float(vals.get("ndcg_sum", 0.0)) / c,
                "recall_proxy_avg": float(vals.get("recall_sum", 0.0)) / c,
            }
    except Exception:
        return {}
    return out

# --------- GeoIP / ASN Metrics ---------

geoip_lookups_total = Counter(
    "shopsquire_geoip_lookups_total",
    "Total GeoIP lookups attempted",
)

geoip_cache_hits_total = Counter(
    "shopsquire_geoip_cache_hits_total",
    "GeoIP cache hits",
)

geo_asn_risk_total = Counter(
    "shopsquire_geo_asn_risk_total",
    "ASN risk observations",
    labelnames=["asn", "org", "country", "band"],
)


def record_geoip_lookup():
    try:
        geoip_lookups_total.inc()
    except Exception:
        pass


def record_geoip_cache_hit():
    try:
        geoip_cache_hits_total.inc()
    except Exception:
        pass


def record_geo_asn_risk(asn: str, org: str, country: str, band: str):
    try:
        geo_asn_risk_total.labels(asn=asn or "0", org=org or "unknown", country=country or "XX", band=band or "low").inc()
    except Exception:
        pass

geo_velocity_anomalies_total = Counter(
    "shopsquire_geo_velocity_anomalies_total",
    "Velocity anomalies observed (distinct users per ASN)",
    labelnames=["asn", "country"],
)


def record_geo_velocity_anomaly(asn: str, country: str):
    try:
        geo_velocity_anomalies_total.labels(asn=asn or "0", country=country or "XX").inc()
    except Exception:
        pass

# --------- Query Clustering Metrics ---------

query_cluster_volume_total = Counter(
    "shopsquire_query_cluster_volume_total",
    "Clustered query volume by label",
    labelnames=["label"],
)


def record_query_cluster_volume(label: str, count: int):
    try:
        query_cluster_volume_total.labels(label=label or "unknown").inc(int(count or 0))
    except Exception:
        pass


@router.post("/observability/ui_action")
def observability_ui_action(action: str | None = None):
    """Increment a Prometheus counter for UI actions.

    Accepts a simple form or query param `action`.
    Returns a small JSON confirmation.
    """
    try:
        record_ui_action(action or "unknown")
        return {"ok": True, "action": action or "unknown"}
    except Exception as e:
        # Still return ok to avoid UI disruption; log in real deployment
        return {"ok": False, "error": str(e)}

# -------------------- AI/ML Missing Metrics (LLM/Agent/CV) --------------------

llm_tokens_total = Counter(
    "shopsquire_llm_tokens_total",
    "Tokens consumed by model/tier",
    labelnames=["model", "tier", "endpoint"],
)

llm_latency_seconds = Histogram(
    "shopsquire_llm_latency_seconds",
    "LLM response time",
    labelnames=["model", "tier", "endpoint"],
)

llm_fallback_total = Counter(
    "shopsquire_llm_fallback_total",
    "Fallbacks to rules or smaller models",
    labelnames=["from", "to", "reason"],
)

agent_invocations_total = Counter(
    "shopsquire_agent_invocations_total",
    "Agent calls by type",
    labelnames=["agent", "result"],
)

agent_confidence = Histogram(
    "shopsquire_agent_confidence",
    "Agent confidence distribution",
    labelnames=["agent"],
)

agent_escalations_total = Counter(
    "shopsquire_agent_escalations_total",
    "Human escalations",
    labelnames=["agent", "reason"],
)

cv_tier_selection_total = Counter(
    "shopsquire_cv_tier_selection_total",
    "CV tier selections",
    labelnames=["tier"],
)

cv_processing_seconds = Histogram(
    "shopsquire_cv_processing_seconds",
    "CV processing time",
    labelnames=["tier"],
)

cv_fraud_detected_total = Counter(
    "shopsquire_cv_fraud_detected_total",
    "CV fraud detections",
    labelnames=["signal"],
)

# Auto-decision and escalation counters for CV forensic pipeline
cv_auto_decisions_total = Counter(
    "shopsquire_cv_auto_decisions_total",
    "CV auto-decisions emitted",
    labelnames=["action", "source"],
)

cv_escalations_total = Counter(
    "shopsquire_cv_escalations_total",
    "CV escalations to human reviewers",
    labelnames=["reason", "tenant"],
)

worker_queue_depth_gauge = Gauge(
    "shopsquire_worker_queue_depth",
    "Current queue depth by worker queue",
    labelnames=["queue"],
)

worker_queue_oldest_age_seconds = Gauge(
    "shopsquire_worker_queue_oldest_age_seconds",
    "Age in seconds of the oldest queued item",
    labelnames=["queue"],
)

pii_detected_total = Counter(
    "shopsquire_pii_detected_total",
    "PII detections by type",
    labelnames=["type"],
)

jailbreak_attempts_total = Counter(
    "shopsquire_jailbreak_attempts_total",
    "Jailbreak attempts detected",
    labelnames=["source"],
)

# WebSocket disconnects (by endpoint)
ws_disconnects_total = Counter(
    "shopsquire_ws_disconnects_total",
    "WebSocket disconnects",
    labelnames=["endpoint"],
)

# Model selection totals (small vs big or specific model)
model_selection_total = Counter(
    "shopsquire_model_selection_total",
    "Model selection decisions",
    labelnames=["tier", "model"],
)

# Human review queue metrics (bridge from agents metrics)
human_review_queued_total = Counter(
    "human_review_queued",
    "Human review items queued",
)

human_review_completed_total = Counter(
    "human_review_completed",
    "Human review items completed",
)

human_review_latency_seconds = Histogram(
    "human_review_latency_s",
    "Latency of human review completion (seconds)",
)

def record_llm_usage(model: str, tier: str, endpoint: str, tokens: int, latency_s: float | None = None):
    try:
        llm_tokens_total.labels(model=model or "unknown", tier=tier or "unknown", endpoint=endpoint or "unknown").inc(tokens or 0)
        if latency_s is not None:
            llm_latency_seconds.labels(model=model or "unknown", tier=tier or "unknown", endpoint=endpoint or "unknown").observe(float(latency_s))
    except Exception:
        pass

def record_llm_fallback(src: str, dst: str, reason: str):
    try:
        llm_fallback_total.labels(**{"from": src or "unknown", "to": dst or "unknown", "reason": reason or "unknown"}).inc()
    except Exception:
        pass

def record_agent_invocation(agent: str, result: str, confidence: float | None = None):
    try:
        agent_invocations_total.labels(agent=agent or "unknown", result=result or "unknown").inc()
        if confidence is not None:
            agent_confidence.labels(agent=agent or "unknown").observe(float(confidence))
    except Exception:
        pass

def record_agent_escalation(agent: str, reason: str):
    try:
        agent_escalations_total.labels(agent=agent or "unknown", reason=reason or "unknown").inc()
    except Exception:
        pass

def record_cv_tier(tier: int):
    try:
        cv_tier_selection_total.labels(tier=str(tier)).inc()
    except Exception:
        pass

def record_cv_processing(tier: int, duration_seconds: float):
    try:
        cv_processing_seconds.labels(tier=str(tier)).observe(float(duration_seconds))
    except Exception:
        pass

def record_cv_fraud(signal: str):
    try:
        cv_fraud_detected_total.labels(signal=signal or "unknown").inc()
    except Exception:
        pass


def record_cv_auto_decision(action: str, source: str = "cv"):
    try:
        cv_auto_decisions_total.labels(action=action or "unknown", source=source or "cv").inc()
    except Exception:
        pass


def record_cv_escalation(reason: str, tenant: str | None = None):
    try:
        cv_escalations_total.labels(reason=reason or "unknown", tenant=tenant or "unknown").inc()
    except Exception:
        pass


def record_worker_queue_depth(queue: str, depth: int):
    try:
        worker_queue_depth_gauge.labels(queue=queue or "unknown").set(max(0, int(depth or 0)))
    except Exception:
        pass


def record_worker_queue_oldest_age(queue: str, age_seconds: float):
    try:
        worker_queue_oldest_age_seconds.labels(queue=queue or "unknown").set(max(0.0, float(age_seconds or 0.0)))
    except Exception:
        pass

def record_pii_detected(piitype: str):
    try:
        pii_detected_total.labels(type=piitype or "unknown").inc()
    except Exception:
        pass

def record_jailbreak_attempt(source: str = "input"):
    try:
        jailbreak_attempts_total.labels(source=source or "input").inc()
    except Exception:
        pass

def record_ws_disconnect(endpoint: str):
    try:
        ws_disconnects_total.labels(endpoint=endpoint or "unknown").inc()
    except Exception:
        pass

def record_model_selection(tier: str, model: str | None = None):
    try:
        model_selection_total.labels(tier=tier or "unknown", model=(model or "unknown")).inc()
    except Exception:
        pass

def record_human_review_queued():
    try:
        human_review_queued_total.inc()
    except Exception:
        pass

def record_human_review_completed():
    try:
        human_review_completed_total.inc()
    except Exception:
        pass

def record_human_review_latency(seconds: float):
    try:
        human_review_latency_seconds.observe(float(seconds))
    except Exception:
        pass

# -------------------- PowerBI Export Metrics --------------------

powerbi_export_requests_total = Counter(
    "shopsquire_powerbi_export_requests_total",
    "PowerBI export requests",
    labelnames=["format", "dataset", "status"],
)

powerbi_export_duration_seconds = Histogram(
    "shopsquire_powerbi_export_duration_seconds",
    "PowerBI export request latency in seconds",
    labelnames=["format", "dataset"],
)


def record_powerbi_export(dataset: str, fmt: str, status: int, duration_seconds: float | None = None):
    try:
        powerbi_export_requests_total.labels(format=fmt or "unknown", dataset=dataset or "unknown", status=str(status)).inc()
        if duration_seconds is not None:
            powerbi_export_duration_seconds.labels(format=fmt or "unknown", dataset=dataset or "unknown").observe(float(duration_seconds))
    except Exception:
        pass

# -------------------- Inventory Sync Metrics --------------------

inventory_sync_runs_total = Counter(
    "shopsquire_inventory_sync_runs_total",
    "Inventory sync runs",
    labelnames=["source", "status"],
)

inventory_sync_records_seen_total = Counter(
    "shopsquire_inventory_sync_records_seen_total",
    "Inventory sync records seen",
    labelnames=["source"],
)

inventory_sync_records_applied_total = Counter(
    "shopsquire_inventory_sync_records_applied_total",
    "Inventory sync records applied",
    labelnames=["source"],
)

inventory_reorder_actions_total = Counter(
    "shopsquire_inventory_reorder_actions_total",
    "Inventory reorder lifecycle actions",
    labelnames=["action", "reason"],
)

inventory_po_created_total = Counter(
    "shopsquire_inventory_po_created_total",
    "Purchase orders created by inventory agent",
    labelnames=["urgency"],
)

inventory_forecast_mape = Histogram(
    "shopsquire_inventory_forecast_mape",
    "Forecast error MAPE for inventory demand model",
)

inventory_stockout_duration_hours = Histogram(
    "shopsquire_inventory_stockout_duration_hours",
    "Observed stockout duration in hours",
)

inventory_transfer_suggestions_total = Counter(
    "shopsquire_inventory_transfer_suggestions_total",
    "Warehouse transfer suggestions emitted",
    labelnames=["status"],
)

inventory_transfer_acceptance_total = Counter(
    "shopsquire_inventory_transfer_acceptance_total",
    "Warehouse transfer acceptance outcomes",
    labelnames=["status"],
)

inventory_alerts_total = Counter(
    "shopsquire_inventory_alerts_total",
    "Inventory stock alerts emitted by type",
    labelnames=["alert_type"],
)

inventory_anomaly_severity_total = Counter(
    "shopsquire_inventory_anomaly_severity_total",
    "Inventory anomaly counts by calibrated severity",
    labelnames=["severity"],
)

inventory_reorder_approvals_total = Counter(
    "shopsquire_inventory_reorder_approvals_total",
    "Inventory reorder approval outcomes",
    labelnames=["status"],
)

parallel_cache_events_total = Counter(
    "shopsquire_parallel_cache_events_total",
    "Parallel exploration cache events",
    labelnames=["outcome"],
)


def record_inventory_sync(source: str, status: str, records_seen: int | None = None, records_applied: int | None = None):
    try:
        inventory_sync_runs_total.labels(source=source or "unknown", status=status or "unknown").inc()
        if records_seen is not None:
            inventory_sync_records_seen_total.labels(source=source or "unknown").inc(int(records_seen))
        if records_applied is not None:
            inventory_sync_records_applied_total.labels(source=source or "unknown").inc(int(records_applied))
    except Exception:
        pass


def record_inventory_reorder_action(action: str, reason: str):
    try:
        inventory_reorder_actions_total.labels(action=action or "unknown", reason=reason or "unknown").inc()
    except Exception:
        pass


def record_inventory_po_created(urgency: str):
    try:
        inventory_po_created_total.labels(urgency=urgency or "normal").inc()
    except Exception:
        pass


def record_inventory_forecast_error_mape(mape: float):
    try:
        inventory_forecast_mape.observe(float(mape))
    except Exception:
        pass


def record_inventory_stockout_duration_hours(hours: float):
    try:
        inventory_stockout_duration_hours.observe(float(hours))
    except Exception:
        pass


def record_inventory_transfer_suggestion(status: str):
    try:
        inventory_transfer_suggestions_total.labels(status=status or "unknown").inc()
    except Exception:
        pass


def record_inventory_transfer_acceptance(status: str):
    try:
        inventory_transfer_acceptance_total.labels(status=status or "unknown").inc()
    except Exception:
        pass


def record_inventory_alert(alert_type: str):
    try:
        inventory_alerts_total.labels(alert_type=alert_type or "unknown").inc()
    except Exception:
        pass


def record_inventory_anomaly_severity(severity: str):
    try:
        inventory_anomaly_severity_total.labels(severity=severity or "unknown").inc()
    except Exception:
        pass


def record_inventory_reorder_approval(status: str):
    try:
        inventory_reorder_approvals_total.labels(status=status or "unknown").inc()
    except Exception:
        pass


def record_parallel_cache_event(outcome: str):
    try:
        parallel_cache_events_total.labels(outcome=outcome or "unknown").inc()
    except Exception:
        pass

# -------------------- CV/Fraud Provider Latency --------------------

cv_provider_latency_seconds = Histogram(
    "shopsquire_cv_provider_latency_seconds",
    "Latency for CV providers",
    labelnames=["provider", "tier", "model"],
)

fraud_provider_latency_seconds = Histogram(
    "shopsquire_fraud_provider_latency_seconds",
    "Latency for Fraud providers",
    labelnames=["provider", "model"],
)


def record_cv_provider_latency(provider: str, tier: str | None, model: str | None, latency_s: float):
    try:
        cv_provider_latency_seconds.labels(provider=provider or "unknown", tier=(tier or "unknown"), model=(model or "unknown")).observe(float(latency_s))
    except Exception:
        pass


def record_fraud_provider_latency(provider: str, model: str | None, latency_s: float):
    try:
        fraud_provider_latency_seconds.labels(provider=provider or "unknown", model=(model or "unknown")).observe(float(latency_s))
    except Exception:
        pass

# Optional per-tenant latency histograms (off by default unless used)
cv_provider_latency_tenant_seconds = Histogram(
    "shopsquire_cv_provider_latency_tenant_seconds",
    "Latency for CV providers with tenant label",
    labelnames=["provider", "tier", "model", "tenant"],
)

fraud_provider_latency_tenant_seconds = Histogram(
    "shopsquire_fraud_provider_latency_tenant_seconds",
    "Latency for Fraud providers with tenant label",
    labelnames=["provider", "model", "tenant"],
)


def record_cv_provider_latency_tenant(provider: str, tier: str | None, model: str | None, tenant: str | None, latency_s: float):
    try:
        cv_provider_latency_tenant_seconds.labels(
            provider=provider or "unknown",
            tier=(tier or "unknown"),
            model=(model or "unknown"),
            tenant=(tenant or "unknown"),
        ).observe(float(latency_s))
    except Exception:
        pass


def record_fraud_provider_latency_tenant(provider: str, model: str | None, tenant: str | None, latency_s: float):
    try:
        fraud_provider_latency_tenant_seconds.labels(
            provider=provider or "unknown",
            model=(model or "unknown"),
            tenant=(tenant or "unknown"),
        ).observe(float(latency_s))
    except Exception:
        pass

# -------------------- Cluster Drift Metrics --------------------

query_cluster_drift_total = Counter(
    "shopsquire_query_cluster_drift_total",
    "Total drift observations across query clusters",
    labelnames=["cluster", "model"],
)

query_cluster_drift_window_gauge = Gauge(
    "shopsquire_query_cluster_drift_window",
    "Windowed drift ratio for a cluster",
    labelnames=["cluster", "model", "window"],
)

query_cluster_drift_ratio_histogram = Histogram(
    "shopsquire_query_cluster_drift_ratio",
    "Distribution of drift ratios",
    labelnames=["cluster", "model"],
)


def record_query_cluster_drift(cluster: str, model: str | None, ratio: float, window_label: str | None = None):
    try:
        query_cluster_drift_total.labels(cluster=cluster or "unknown", model=(model or "unknown")).inc()
        query_cluster_drift_ratio_histogram.labels(cluster=cluster or "unknown", model=(model or "unknown")).observe(float(ratio))
        if window_label:
            query_cluster_drift_window_gauge.labels(cluster=cluster or "unknown", model=(model or "unknown"), window=window_label).set(float(ratio))
    except Exception:
        pass
