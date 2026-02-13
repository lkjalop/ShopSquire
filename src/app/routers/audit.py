from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Body

import uuid

from src.app.services.audit_evidence_agent import AuditEvidenceAgent
from src.app.services.decision_log import log_trace_event


router = APIRouter(prefix="/api/v1/audit", tags=["audit"])


@router.get("/evidence")
def audit_evidence_get() -> Dict[str, Any]:
    agent = AuditEvidenceAgent()
    report = agent.run({})
    trace_id = str(uuid.uuid4())
    summary = report.get("summary") or {}
    try:
        log_trace_event(
            trace_id=trace_id,
            event_type="audit_evidence",
            source_type="agent",
            source_id="Audit_Evidence_Agent",
            target_type="system",
            target_id=None,
            payload={
                "summary": summary,
                "short": f"AuditEvidenceAgent: {summary.get('pass', 0)} PASS / {summary.get('warn', 0)} WARN / {summary.get('fail', 0)} FAIL",
                "rules": report.get("rules"),
            },
        )
    except Exception:
        pass
    report["trace_id"] = trace_id
    report["summary_line"] = f"AuditEvidenceAgent: {summary.get('pass', 0)} PASS / {summary.get('warn', 0)} WARN / {summary.get('fail', 0)} FAIL"
    return report


@router.post("/evidence")
def audit_evidence_post(payload: Dict[str, Any] = Body(default_factory=dict)) -> Dict[str, Any]:
    agent = AuditEvidenceAgent()
    report = agent.run(payload or {})
    trace_id = str(uuid.uuid4())
    summary = report.get("summary") or {}
    try:
        log_trace_event(
            trace_id=trace_id,
            event_type="audit_evidence",
            source_type="agent",
            source_id="Audit_Evidence_Agent",
            target_type="system",
            target_id=None,
            payload={
                "summary": summary,
                "short": f"AuditEvidenceAgent: {summary.get('pass', 0)} PASS / {summary.get('warn', 0)} WARN / {summary.get('fail', 0)} FAIL",
                "rules": report.get("rules"),
                "scope": report.get("scope"),
            },
        )
    except Exception:
        pass
    report["trace_id"] = trace_id
    report["summary_line"] = f"AuditEvidenceAgent: {summary.get('pass', 0)} PASS / {summary.get('warn', 0)} WARN / {summary.get('fail', 0)} FAIL"
    return report
