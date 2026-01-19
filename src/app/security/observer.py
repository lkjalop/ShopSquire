import json
import uuid
from typing import Any, Dict
import os

from src.app.deps import security_sanitize, JAILBREAK_PAT
from src.app.models.db import db_session
from src.app.observability.tracing import init_tracer, get_tracer


def _load_json(path: str) -> Dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def compute_severity(payload: Dict[str, Any]) -> str:
    text = json.dumps(payload, ensure_ascii=False)
    # Base signals
    mitre = _load_json(os.path.join("config", "security", "taxonomy", "mitre_atlas_techniques.json"))
    stride = _load_json(os.path.join("config", "security", "taxonomy", "stride_categories.json"))
    dread = _load_json(os.path.join("config", "security", "taxonomy", "dread_weights.json"))
    cvss = _load_json(os.path.join("config", "security", "taxonomy", "cvss_v3_severity_map.json"))
    policy = _load_json(os.path.join("config", "security", "taxonomy", "risk_correlation_policy.json"))

    w = policy.get("weights", {"mitre": 0.3, "stride": 0.1, "dread": 0.25, "cvss": 0.2, "kev": 0.15})
    bands = policy.get("bands", {"info": 0, "warn": 20, "high": 50, "critical": 80})

    # Simple heuristic mapping
    mitre_sev = 50 if JAILBREAK_PAT.search(text) else 0
    stride_sum = stride.get("information_disclosure", 0)
    dread_avg = sum(dread.values()) / max(len(dread.values()) or 1, 1)
    cvss_score = cvss.get("LOW", 0.2)
    kev_weight = 0  # no KEV integration in MVP

    risk_raw = (
        w.get("mitre", 0.3) * mitre_sev
        + w.get("stride", 0.1) * stride_sum
        + w.get("dread", 0.25) * dread_avg * 10
        + w.get("cvss", 0.2) * cvss_score * 100
        + w.get("kev", 0.15) * kev_weight
    )
    # Context multiplier
    context_mult = policy.get("context_multipliers", {}).get("default", 1.0)
    risk_adj = risk_raw * context_mult

    if risk_adj >= bands.get("critical", 80):
        return "critical"
    if risk_adj >= bands.get("high", 50):
        return "high"
    if risk_adj >= bands.get("warn", 20):
        return "warn"
    return "info"


def emit_security_event(path: str, payload: Dict[str, Any]) -> None:
    init_tracer()
    tracer = get_tracer("security-observer")
    sanitized = security_sanitize(payload)
    severity = compute_severity(sanitized)
    with tracer.start_as_current_span("security_event") as span:
        span.set_attribute("observer.path", path)
        span.set_attribute("observer.severity", severity)
        span.set_attribute("observer.payload.size", len(json.dumps(sanitized)))
        with db_session() as db:
            db.execute(
                """
                INSERT INTO security_events (id, path, severity, verdict_score, details)
                VALUES (:id, :path, :severity, :score, :details)
                """,
                {
                    "id": str(uuid.uuid4()),
                    "path": path,
                    "severity": severity,
                    "score": 80 if severity in ("high", "critical") else 10,
                    "details": json.dumps({"payload": sanitized}, ensure_ascii=False),
                },
            )
            db.commit()
