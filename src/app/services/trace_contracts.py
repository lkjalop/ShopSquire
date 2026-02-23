from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime
from typing import Any, Dict, List

from pydantic import BaseModel, Field
from sqlalchemy import text as sql_text


def _now_iso() -> str:
    return datetime.utcnow().isoformat()


def _short_hash_text(value: str) -> str:
    return hashlib.sha256((value or "").encode("utf-8")).hexdigest()[:16]


def _short_hash_obj(value: Any) -> str:
    try:
        raw = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    except Exception:
        raw = str(value)
    return _short_hash_text(raw)


def _coerce_str_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, list):
        out: List[str] = []
        for item in value:
            if item is None:
                continue
            s = str(item).strip()
            if s:
                out.append(s)
        return out
    return []


def _coerce_bool_map(value: Any) -> Dict[str, bool]:
    out: Dict[str, bool] = {}
    if not isinstance(value, dict):
        return out
    for k, v in value.items():
        if not isinstance(k, str):
            continue
        if isinstance(v, bool):
            out[k] = v
        elif isinstance(v, (int, float)):
            out[k] = bool(v)
        elif isinstance(v, str):
            vv = v.strip().lower()
            if vv in ("1", "true", "yes", "on"):
                out[k] = True
            elif vv in ("0", "false", "no", "off"):
                out[k] = False
    return out


def _default_route_from_severity(severity: str) -> str:
    s = str(severity or "").strip().lower()
    if s in ("critical", "high", "error"):
        return "escalate"
    if s in ("warn", "warning", "medium"):
        return "review"
    if s in ("blocked", "block"):
        return "block"
    return "allow"


def _normalize_severity(value: str | None) -> str:
    s = str(value or "").strip().lower()
    if s == "warning":
        return "warn"
    if not s:
        return "info"
    return s


def _extract_security_candidate(raw_payload: Dict[str, Any]) -> Dict[str, Any]:
    candidates = [
        raw_payload.get("security"),
        raw_payload.get("security_analysis"),
        ((raw_payload.get("details") or {}).get("security") if isinstance(raw_payload.get("details"), dict) else None),
        ((raw_payload.get("details") or {}).get("security_analysis") if isinstance(raw_payload.get("details"), dict) else None),
        raw_payload.get("details"),
        raw_payload,
    ]
    for cand in candidates:
        if isinstance(cand, dict):
            return cand
    return {}


class BitemporalWindow(BaseModel):
    valid_from: str
    valid_to: str | None = "infinity"
    system_from: str
    system_to: str | None = "infinity"


class SecurityScanContract(BaseModel):
    severity: str = "info"
    route: str = "allow"
    threshold_version: str = "security-v1"
    confidence: float | None = None
    signals: Dict[str, bool] = Field(default_factory=dict)
    mitre_atlas: List[str] = Field(default_factory=list)
    mitre_attack: List[str] = Field(default_factory=list)
    owasp_llm_top10: List[str] = Field(default_factory=list)
    owasp_agentic_top10: List[str] = Field(default_factory=list)
    owasp_api_top10: List[str] = Field(default_factory=list)
    stride_categories: List[str] = Field(default_factory=list)
    dread: Dict[str, Any] | None = None
    pasta: Dict[str, Any] | None = None
    evidence: Dict[str, Any] = Field(default_factory=dict)
    containment_actions: List[str] = Field(default_factory=list)
    input_hash: str | None = None
    ocr_text_hash: str | None = None
    entities: Dict[str, Any] = Field(default_factory=dict)
    bitemporal: BitemporalWindow


def normalize_security_scan_payload(
    raw_payload: Dict[str, Any],
    now_ts: str | None = None,
    source_id: str | None = None,
) -> Dict[str, Any]:
    now = now_ts or _now_iso()
    payload = raw_payload if isinstance(raw_payload, dict) else {}
    sec = _extract_security_candidate(payload)

    severity = _normalize_severity(payload.get("severity") or sec.get("severity"))
    route = str(payload.get("route") or sec.get("route") or _default_route_from_severity(severity)).strip().lower()
    if route not in ("allow", "review", "escalate", "block"):
        route = _default_route_from_severity(severity)
    threshold_version = str(
        payload.get("threshold_version")
        or sec.get("threshold_version")
        or os.getenv("SECURITY_THRESHOLD_VERSION")
        or "security-v1"
    ).strip()
    if not threshold_version:
        threshold_version = "security-v1"

    signals = _coerce_bool_map(sec.get("signals"))
    if not signals:
        for k, v in sec.items():
            if isinstance(v, bool):
                signals[k] = v
    signals.update(_coerce_bool_map(payload.get("cv_signals")))
    for key in ("qr_code_detected", "qr_prompt_injection", "image_consistency_mismatch", "ocr_prompt_injection"):
        if key in payload and isinstance(payload.get(key), bool):
            signals[key] = bool(payload.get(key))

    dread = sec.get("dread")
    if dread is None and sec.get("dread_avg") is not None:
        dread = {"avg": sec.get("dread_avg")}
    pasta = sec.get("pasta")
    if pasta is None and sec.get("pasta_stage") is not None:
        pasta = {"current_stage": sec.get("pasta_stage")}

    evidence = sec.get("evidence") if isinstance(sec.get("evidence"), dict) else {}
    if not isinstance(evidence, dict):
        evidence = {}
    if "source" not in evidence:
        evidence["source"] = source_id or "unknown"
    if "matched_patterns" not in evidence:
        evidence["matched_patterns"] = _coerce_str_list(sec.get("evidence_tags"))

    raw_ocr = payload.get("ocr_text") or sec.get("ocr_text")
    ocr_text_hash = payload.get("ocr_text_hash")
    if not ocr_text_hash and isinstance(raw_ocr, str) and raw_ocr.strip():
        ocr_text_hash = _short_hash_text(raw_ocr)

    input_hash = payload.get("input_hash")
    if not input_hash:
        input_candidate = payload.get("input") if payload.get("input") is not None else {"signals": signals, "severity": severity, "route": route}
        input_hash = _short_hash_obj(input_candidate)

    entities = payload.get("entities") if isinstance(payload.get("entities"), dict) else {}
    bitemporal = payload.get("bitemporal") if isinstance(payload.get("bitemporal"), dict) else {}
    valid_from = str(bitemporal.get("valid_from") or now)
    system_from = str(bitemporal.get("system_from") or now)
    valid_to = bitemporal.get("valid_to")
    system_to = bitemporal.get("system_to")

    contract = SecurityScanContract(
        severity=severity,
        route=route,
        threshold_version=threshold_version,
        confidence=(
            float(payload.get("confidence"))
            if payload.get("confidence") is not None
            else (float(sec.get("confidence")) if sec.get("confidence") is not None else None)
        ),
        signals=signals,
        mitre_atlas=_coerce_str_list(sec.get("mitre_atlas") or sec.get("mitre")),
        mitre_attack=_coerce_str_list(sec.get("mitre_attack")),
        owasp_llm_top10=_coerce_str_list(sec.get("owasp_llm_top10") or sec.get("owasp_llm")),
        owasp_agentic_top10=_coerce_str_list(sec.get("owasp_agentic_top10") or sec.get("owasp_agentic")),
        owasp_api_top10=_coerce_str_list(sec.get("owasp_api_top10") or sec.get("owasp_api")),
        stride_categories=_coerce_str_list(sec.get("stride_categories") or sec.get("stride")),
        dread=(dread if isinstance(dread, dict) else None),
        pasta=(pasta if isinstance(pasta, dict) else None),
        evidence=evidence,
        containment_actions=_coerce_str_list(sec.get("containment_actions") or sec.get("actions")),
        input_hash=str(input_hash),
        ocr_text_hash=(str(ocr_text_hash) if ocr_text_hash else None),
        entities=entities,
        bitemporal=BitemporalWindow(
            valid_from=valid_from,
            valid_to=(str(valid_to) if valid_to else "infinity"),
            system_from=system_from,
            system_to=(str(system_to) if system_to else "infinity"),
        ),
    )
    return contract.model_dump()


def apply_trace_contract(
    event_type: str,
    payload: Dict[str, Any],
    source_id: str | None = None,
    now_ts: str | None = None,
) -> Dict[str, Any]:
    safe_payload = dict(payload or {}) if isinstance(payload, dict) else {"data": payload}
    now = now_ts or _now_iso()
    event = str(event_type or "").strip().lower()

    if event == "security_scan":
        security_payload = normalize_security_scan_payload(safe_payload, now_ts=now, source_id=source_id)
        matrix = {
            "severity_band": security_payload.get("severity"),
            "mitre": security_payload.get("mitre_atlas", []),
            "owasp_llm": security_payload.get("owasp_llm_top10", []),
            "stride": security_payload.get("stride_categories", []),
            "confidence": security_payload.get("confidence"),
            "evidence_source": (security_payload.get("evidence") or {}).get("source"),
            "containment_actions": security_payload.get("containment_actions", []),
        }
        safe_payload["security"] = security_payload
        safe_payload["security_analysis"] = security_payload
        safe_payload["details"] = security_payload
        safe_payload["security_matrix"] = matrix
        safe_payload["bitemporal"] = security_payload.get("bitemporal")
        safe_payload["_trace_contract"] = {
            "name": "security_scan.v1",
            "matrix_complete": True,
            "required_fields": [
                "severity",
                "route",
                "threshold_version",
                "signals",
                "mitre_atlas",
                "owasp_llm_top10",
                "stride_categories",
                "evidence",
                "bitemporal",
            ],
        }
        return safe_payload

    if event in ("cv_analysis", "cv_upload"):
        bitemporal = safe_payload.get("bitemporal") if isinstance(safe_payload.get("bitemporal"), dict) else {}
        safe_payload["bitemporal"] = {
            "valid_from": str(bitemporal.get("valid_from") or now),
            "valid_to": str(bitemporal.get("valid_to") or "infinity"),
            "system_from": str(bitemporal.get("system_from") or now),
            "system_to": str(bitemporal.get("system_to") or "infinity"),
        }
        if not safe_payload.get("input_hash"):
            safe_payload["input_hash"] = _short_hash_obj(
                {
                    "evidence_id": safe_payload.get("evidence_id"),
                    "processing_ms": safe_payload.get("processing_ms"),
                    "image_consistency": safe_payload.get("image_consistency"),
                }
            )
        if not safe_payload.get("ocr_text_hash"):
            ocr_text = safe_payload.get("ocr_text")
            if isinstance(ocr_text, str) and ocr_text.strip():
                safe_payload["ocr_text_hash"] = _short_hash_text(ocr_text)
        safe_payload["_trace_contract"] = {
            "name": "cv_lane.v1",
            "required_fields": ["bitemporal", "input_hash"],
        }
        return safe_payload

    return safe_payload


def _required_matrix_missing(payload: Dict[str, Any]) -> List[str]:
    sec = _extract_security_candidate(payload)
    if not isinstance(sec, dict):
        return ["security"]
    missing: List[str] = []
    if not sec.get("severity"):
        missing.append("severity")
    if not sec.get("route"):
        missing.append("route")
    if not sec.get("threshold_version"):
        missing.append("threshold_version")
    if not isinstance(sec.get("signals"), dict):
        missing.append("signals")
    if "mitre_atlas" not in sec:
        missing.append("mitre_atlas")
    if "owasp_llm_top10" not in sec:
        missing.append("owasp_llm_top10")
    if "stride_categories" not in sec:
        missing.append("stride_categories")
    if not isinstance(sec.get("evidence"), dict):
        missing.append("evidence")
    bt = sec.get("bitemporal")
    if not isinstance(bt, dict) or not bt.get("valid_from") or not bt.get("system_from"):
        missing.append("bitemporal")
    return missing


def _safe_json_dict(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


def _collect_trace_ids(obj: Any, out: set[str]) -> None:
    if isinstance(obj, dict):
        for key in ("trace_id", "case_id", "decision_id"):
            val = obj.get(key)
            if isinstance(val, str) and val.strip():
                out.add(val.strip())
        for v in obj.values():
            _collect_trace_ids(v, out)
    elif isinstance(obj, list):
        for item in obj:
            _collect_trace_ids(item, out)


def validate_incident_matrix_gate(db, incident_id: str) -> Dict[str, Any]:
    row = db.execute(
        sql_text("SELECT id, event_id, severity, description, status FROM incidents WHERE id = :id LIMIT 1"),
        {"id": incident_id},
    ).mappings().first()
    if not row:
        return {"ok": False, "reason": "incident_not_found"}

    candidate_trace_ids: set[str] = set()
    event_id = str(row.get("event_id") or "").strip()
    if event_id:
        candidate_trace_ids.add(event_id)

    desc = _safe_json_dict(row.get("description"))
    _collect_trace_ids(desc, candidate_trace_ids)

    if event_id:
        try:
            sec_row = db.execute(
                sql_text("SELECT details FROM security_events WHERE id = :id LIMIT 1"),
                {"id": event_id},
            ).fetchone()
            if sec_row and sec_row[0]:
                sec_details = _safe_json_dict(sec_row[0])
                _collect_trace_ids(sec_details, candidate_trace_ids)
        except Exception:
            pass

    if not candidate_trace_ids:
        return {"ok": False, "reason": "trace_id_missing", "incident_id": incident_id}

    best_failure: Dict[str, Any] | None = None
    for trace_id in list(candidate_trace_ids):
        evt = db.execute(
            sql_text(
                """
                SELECT id, payload, created_at
                FROM decision_trace_events
                WHERE event_type = 'security_scan'
                  AND (trace_id = :tid OR target_id = :tid)
                ORDER BY created_at DESC
                LIMIT 1
                """
            ),
            {"tid": trace_id},
        ).fetchone()
        if not evt:
            best_failure = {
                "ok": False,
                "reason": "security_scan_missing",
                "trace_id": trace_id,
                "incident_id": incident_id,
            }
            continue
        payload = _safe_json_dict(evt[1])
        missing = _required_matrix_missing(payload)
        contract = payload.get("_trace_contract") if isinstance(payload, dict) else None
        if not missing and isinstance(contract, dict) and contract.get("name") == "security_scan.v1":
            return {
                "ok": True,
                "trace_id": trace_id,
                "incident_id": incident_id,
                "event_id": evt[0],
                "event_created_at": str(evt[2]),
            }
        best_failure = {
            "ok": False,
            "reason": "security_matrix_incomplete",
            "trace_id": trace_id,
            "incident_id": incident_id,
            "event_id": evt[0],
            "missing_fields": missing or ["trace_contract"],
        }

    return best_failure or {"ok": False, "reason": "security_scan_missing", "incident_id": incident_id}

