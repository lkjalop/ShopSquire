from __future__ import annotations

from typing import Dict, Optional, List, Any
import os
import re
import json
import ast
import base64
import binascii
import logging
import unicodedata
import asyncio
import hashlib
import time

from fastapi import APIRouter, Depends, UploadFile, File, Request, Form, HTTPException
from pydantic import BaseModel

from src.app.models.db import get_db
from src.app.services.nlp_complaints import ComplaintNLP
from src.app.services.nlp_contract import is_contract_like_text, run_contract_assist, evaluate_quality_gate
from src.app.security.email_validation import validate_email_auth, detect_bec_indicators
from src.app.services.decision_log import log_decision, log_trace_event
from src.app.services.notifications import NotificationService
from src.app.services.cases import create_case, get_case_status as _get_case_status
from src.app.services.trust_routing import compute_trust_score, auto_approve_thresholds, route_from_trust
from src.app.services.fraud_scorer import FraudScorer
from src.app.deps import scrub_pii
from src.app.services.ticketing import TicketingAgent
from src.app.observability.metrics import record_complaint_triage
from src.app.integrations.janusec import JanuSecClient
from src.app.services.reverse_image_search import ReverseImageSearch
from src.app.services.risk_quantification import quantify as quantify_risk
from src.app.services.security_playbooks import select_playbook, build_evidence_snapshot, select_cv_playbook, get_cv_playbook_by_id
from src.app.services.cv_evidence import build_evidence_bundle, persist_evidence_bundle, get_evidence_bundle
from src.app.services.erp_edi import ERPEDIConnector
from src.app.services.intake_gate import strict_image_ingest_gate
from src.app.flows.nqe import NextQuestionEngine, NQEInput
from src.app.flows.catalog import QuestionTemplateCatalog
from src.app.rag.retrieve import Retriever
from src.app.security.observer import analyze_payload, emit_security_event
from src.app.security.tls_fingerprint_middleware import extract_tls_fingerprints_from_request
from src.app.services.geoip import enrich_ip
from src.app.policy.gate import evaluate_policy_gate
from src.app.feature_flags import get_flags
from src.app.security.exif_analyzer import analyze_exif
from src.app.security.file_validator import validate_image_blob
from src.app.security.image_threat_signals import (
    detect_cross_image_split_injection as _detect_cross_image_split_injection_shared,
    detect_ocr_encoded_payload as _detect_ocr_encoded_payload_shared,
    detect_ocr_prompt_injection as _detect_ocr_prompt_injection_shared,
    detect_qr_label_destination_mismatch as _detect_qr_label_destination_mismatch_shared,
    normalize_ocr_and_detect as _normalize_ocr_and_detect_shared,
    sanitize_unicode_injection as _sanitize_unicode_injection_shared,
)


router = APIRouter(prefix="/api/v1/support/complaints", tags=["support"])
_QR_REDIRECT_TASKS: Dict[str, asyncio.Task] = {}


def _build_complaint_security_matrix(
    *,
    security_details: Dict[str, Any] | None = None,
    security_severity: str | None = None,
    rule_eval: Dict[str, Any] | None = None,
    nlp_rules: Dict[str, Any] | None = None,
    image_consistency: Dict[str, Any] | None = None,
    qr_payload_types: Any = None,
    recommended_route: str | None = None,
) -> Dict[str, Any]:
    """Canonical Security Matrix payload for complaint/CV traces."""
    details = security_details if isinstance(security_details, dict) else {}
    cv_signals = dict((rule_eval or {}).get("signals") or {})
    nlp_signals = dict((nlp_rules or {}).get("signals") or {})
    observer_signals = dict(details.get("signals") or {})
    merged_signals = {**observer_signals, **cv_signals, **nlp_signals}
    qr_types = sorted([str(x) for x in (qr_payload_types or []) if str(x).strip()])
    mismatch_count = 0
    try:
        mismatch_count = int((image_consistency or {}).get("mismatch_count") or 0)
    except Exception:
        mismatch_count = 0
    severity = str(security_severity or details.get("severity") or ("high" if recommended_route == "security_review" else "info"))
    mitre = list(details.get("mitre_atlas") or details.get("mitre") or [])
    owasp = list(details.get("owasp_llm_top10") or details.get("owasp_llm") or [])
    stride = list(details.get("stride_categories") or details.get("stride") or [])
    if any(merged_signals.get(k) for k in ("ocr_prompt_injection", "qr_prompt_injection", "cross_image_split_injection")):
        if "LLM01 Prompt Injection" not in owasp:
            owasp.append("LLM01 Prompt Injection")
    if any(merged_signals.get(k) for k in ("qr_external_url_detected", "qr_url_suspicious")):
        if "T1566 Phishing" not in mitre:
            mitre.append("T1566 Phishing")
    if mismatch_count > 0 and "Tampering" not in stride:
        stride.append("Tampering")
    return {
        "verdict": recommended_route or details.get("route") or "review",
        "severity_band": severity,
        "policy_action": recommended_route or "security_review",
        "mitre": mitre,
        "owasp": owasp,
        "owasp_llm": owasp,
        "stride": stride,
        "signals": merged_signals,
        "cv_signals": cv_signals,
        "qr_payload_types": qr_types,
        "image_consistency": {
            "status": (image_consistency or {}).get("status"),
            "mismatch_count": mismatch_count,
            "repeat_mismatch": bool((image_consistency or {}).get("repeat_mismatch")),
        },
        "maestro": [
            {
                "control": "SC-04B",
                "boundary": "Image_Intake_Agent",
                "verdict": "raw_image_payload_quarantined",
                "action": "safe_evidence_features_only",
            },
            {
                "control": "SC-04B",
                "boundary": "Security_Observer_Agent",
                "verdict": "prompt_and_artifact_boundaries_enforced",
                "action": "route_suspicious_content_to_review",
            },
            {
                "control": "SC-07",
                "boundary": "Routing_Agent",
                "verdict": "policy_gated",
                "action": recommended_route or "security_review",
            },
        ],
        "containment_actions": [
            "quarantine_raw_ocr_and_qr_payloads",
            "do_not_execute_image_text",
            "require_order_and_policy_verification",
        ],
        "evidence_source": "support_complaints.submit",
    }


async def _dispatch_case_created_notification(case_id: str | None, customer_email: str | None = None) -> None:
    try:
        ns = NotificationService()
        target_case_id = str(case_id or "unknown")
        await ns.send_notification(
            event="case_created",
            context={
                "case_id": target_case_id,
                "customer_email": customer_email,
                "track_url": f"/cases/{target_case_id}",
            },
            channels=["email"],
        )
    except Exception:
        pass


def _get_support_thresholds() -> Dict[str, Any]:
    try:
        flags = get_flags()
        raw = flags.get("SUPPORT_THRESHOLDS", {}) if isinstance(flags.get("SUPPORT_THRESHOLDS"), dict) else {}
    except Exception:
        raw = {}

    def _f(key: str, default: float) -> float:
        try:
            return float(raw.get(key, default))
        except Exception:
            return default

    def _i(key: str, default: int) -> int:
        try:
            return int(raw.get(key, default))
        except Exception:
            return default

    levels = raw.get("auto_process_fraud_levels", ["minimal", "low"])
    if not isinstance(levels, list):
        levels = ["minimal", "low"]
    return {
        "cv_confidence_low_min": _f("cv_confidence_low_min", 0.5),
        "manipulation_score_high_min": _f("manipulation_score_high_min", 0.6),
        "excessive_returns_last_30_days_min": _i("excessive_returns_last_30_days_min", 3),
        "auto_process_confidence_min_signed_in": _f("auto_process_confidence_min_signed_in", 0.8),
        "auto_process_confidence_min_guest": _f("auto_process_confidence_min_guest", 0.85),
        "auto_process_fraud_levels": [str(x) for x in levels if str(x).strip()],
    }


def _geoip_routing_thresholds() -> Dict[str, float]:
    def _f(name: str, default: float) -> float:
        try:
            return float(os.getenv(name, str(default)) or default)
        except Exception:
            return default

    return {
        "security_review_risk_threshold": _f("GEOIP_SECURITY_REVIEW_RISK_THRESHOLD", 0.75),
        "hard_block_risk_threshold": _f("GEOIP_HARD_BLOCK_RISK_THRESHOLD", 0.9),
    }


def _load_bad_asn_set() -> set[int]:
    try:
        path = os.path.join("config", "security", "bad_asn.json")
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        vals = data.get("bad_asn", []) if isinstance(data, dict) else []
        out: set[int] = set()
        for v in vals:
            try:
                out.add(int(v))
            except Exception:
                continue
        return out
    except Exception:
        return set()


def _build_geoip_trace(source_ip: str | None) -> Dict[str, Any]:
    ip = str(source_ip or "").strip()
    if not ip:
        return {
            "source_ip": None,
            "thresholds": _geoip_routing_thresholds(),
            "route_reason": "no_source_ip",
            "force_security_review": False,
            "hard_block_candidate": False,
        }
    geo = enrich_ip(ip)
    thresholds = _geoip_routing_thresholds()
    risk = float(geo.get("risk") or 0.0)
    asn = geo.get("asn")
    try:
        asn_i = int(asn) if asn is not None else None
    except Exception:
        asn_i = None
    bad_asn_hit = bool(asn_i is not None and asn_i in _load_bad_asn_set())
    force_security = bool(
        bad_asn_hit
        or risk >= float(thresholds.get("security_review_risk_threshold") or 0.75)
        or bool(geo.get("is_vpn"))
        or bool(geo.get("is_hosting"))
    )
    hard_block = bool(risk >= float(thresholds.get("hard_block_risk_threshold") or 0.9) and bad_asn_hit)
    return {
        "source_ip": ip,
        "country": geo.get("country"),
        "asn": asn_i,
        "asn_org": geo.get("asn_org"),
        "is_vpn": bool(geo.get("is_vpn")),
        "is_hosting": bool(geo.get("is_hosting")),
        "risk": round(risk, 4),
        "bad_asn_hit": bad_asn_hit,
        "thresholds": thresholds,
        "route_reason": (
            "hard_block_candidate"
            if hard_block
            else ("geoip_risk_or_asn_threshold" if force_security else "none")
        ),
        "force_security_review": force_security,
        "hard_block_candidate": hard_block,
    }


CV_SECURITY_RULES: List[Dict[str, Any]] = [
    {"id": "CV01", "name": "duplicate_image_detected", "severity": "high"},
    {"id": "CV02", "name": "serial_mismatch", "severity": "high"},
    {"id": "CV03", "name": "missing_serial", "severity": "medium"},
    {"id": "CV04", "name": "damage_not_visible", "severity": "medium"},
    {"id": "CV05", "name": "low_confidence_cv", "severity": "medium"},
    {"id": "CV06", "name": "high_severity_damage", "severity": "high"},
    {"id": "CV07", "name": "image_reuse_across_cases", "severity": "high"},
    {"id": "CV08", "name": "ocr_order_id_missing", "severity": "low"},
    {"id": "CV09", "name": "ocr_order_id_mismatch", "severity": "high"},
    {"id": "CV10", "name": "invoice_missing", "severity": "medium"},
    {"id": "CV11", "name": "packaging_mismatch", "severity": "medium"},
    {"id": "CV12", "name": "warranty_lapsed", "severity": "medium"},
    {"id": "CV13", "name": "return_window_expired", "severity": "high"},
    {"id": "CV14", "name": "high_value_item", "severity": "high"},
    {"id": "CV15", "name": "repeat_offender_pattern", "severity": "high"},
    {"id": "CV16", "name": "suspicious_language", "severity": "medium"},
    {"id": "CV17", "name": "chargeback_threat", "severity": "high"},
    {"id": "CV18", "name": "legal_threat", "severity": "high"},
    {"id": "CV19", "name": "price_match_claim", "severity": "low"},
    {"id": "CV20", "name": "alternate_product_request", "severity": "low"},
    {"id": "CV21", "name": "fraud_score_high", "severity": "high"},
    {"id": "CV22", "name": "fraud_score_medium", "severity": "medium"},
    {"id": "CV23", "name": "supplier_invoice_mismatch", "severity": "high"},
    {"id": "CV24", "name": "supplier_unverified", "severity": "high"},
    {"id": "CV25", "name": "third_party_label_mismatch", "severity": "medium"},
    {"id": "CV26", "name": "counterfeit_indicator", "severity": "high"},
    {"id": "CV27", "name": "tampered_receipt", "severity": "high"},
    {"id": "CV28", "name": "missing_accessories", "severity": "low"},
    {"id": "CV29", "name": "refund_amount_mismatch", "severity": "medium"},
    {"id": "CV30", "name": "return_reason_inconsistent", "severity": "medium"},
    {"id": "CV31", "name": "excessive_returns_rate", "severity": "high"},
    {"id": "CV32", "name": "delivery_proof_missing", "severity": "medium"},
    {"id": "CV33", "name": "device_fingerprint_mismatch", "severity": "medium"},
    {"id": "CV34", "name": "shipping_label_reuse", "severity": "high"},
    {"id": "CV35", "name": "product_not_in_catalog", "severity": "medium"},
    {"id": "CV36", "name": "sku_mismatch", "severity": "medium"},
    {"id": "CV37", "name": "region_voltage_mismatch", "severity": "low"},
    {"id": "CV38", "name": "damaged_packaging_only", "severity": "low"},
    {"id": "CV39", "name": "high_risk_region", "severity": "medium"},
    {"id": "CV40", "name": "manual_review_requested", "severity": "high"},
    {"id": "CV41", "name": "ocr_prompt_injection", "severity": "high"},
    {"id": "CV42", "name": "image_consistency_mismatch", "severity": "medium"},
    {"id": "CV43", "name": "repeat_image_consistency_mismatch", "severity": "high"},
    {"id": "CV44", "name": "order_id_not_found", "severity": "high"},
]

NLP_COMPLIANCE_RULES: List[Dict[str, Any]] = [
    {"id": "NLP01", "name": "pci_card_number", "severity": "high"},
    {"id": "NLP02", "name": "pci_cvv_request", "severity": "high"},
    {"id": "NLP03", "name": "pci_full_pan_request", "severity": "high"},
    {"id": "NLP04", "name": "pii_ssn", "severity": "high"},
    {"id": "NLP05", "name": "pii_driver_license", "severity": "medium"},
    {"id": "NLP06", "name": "pii_passport", "severity": "medium"},
    {"id": "NLP07", "name": "password_reset_social_engineering", "severity": "high"},
    {"id": "NLP08", "name": "account_takeover_request", "severity": "high"},
    {"id": "NLP09", "name": "refund_to_new_account", "severity": "high"},
    {"id": "NLP10", "name": "wire_transfer_request", "severity": "high"},
    {"id": "NLP11", "name": "gift_card_request", "severity": "high"},
    {"id": "NLP12", "name": "supplier_contact_leak", "severity": "medium"},
    {"id": "NLP13", "name": "access_internal_policy", "severity": "medium"},
    {"id": "NLP14", "name": "bypass_verification", "severity": "high"},
    {"id": "NLP15", "name": "excessive_privacy_request", "severity": "medium"},
    {"id": "NLP16", "name": "system_prompt_probe", "severity": "medium"},
    {"id": "NLP17", "name": "jailbreak_attempt", "severity": "high"},
    {"id": "NLP18", "name": "data_exfiltration_request", "severity": "high"},
    {"id": "NLP19", "name": "confidential_data_request", "severity": "high"},
    {"id": "NLP20", "name": "financial_pressure_language", "severity": "medium"},
    {"id": "NLP21", "name": "human_override_request", "severity": "high"},
    {"id": "NLP22", "name": "regulatory_complaint_threat", "severity": "medium"},
    {"id": "NLP23", "name": "iso27001_control_inquiry", "severity": "low"},
    {"id": "NLP24", "name": "iso42001_model_governance", "severity": "low"},
    {"id": "NLP25", "name": "soc2_incident_request", "severity": "medium"},
    {"id": "NLP26", "name": "gdpr_delete_request", "severity": "medium"},
    {"id": "NLP27", "name": "hipaa_data_request", "severity": "high"},
    {"id": "NLP28", "name": "consent_withdrawal", "severity": "low"},
    {"id": "NLP29", "name": "export_customer_data", "severity": "high"},
    {"id": "NLP30", "name": "access_logs_request", "severity": "medium"},
    {"id": "NLP31", "name": "insider_threat_language", "severity": "high"},
    {"id": "NLP32", "name": "api_key_request", "severity": "high"},
    {"id": "NLP33", "name": "config_dump_request", "severity": "high"},
    {"id": "NLP34", "name": "payment_token_request", "severity": "high"},
    {"id": "NLP35", "name": "supplier_bank_change", "severity": "high"},
    {"id": "NLP36", "name": "invoice_redirect", "severity": "high"},
    {"id": "NLP37", "name": "threaten_chargeback", "severity": "high"},
    {"id": "NLP38", "name": "legal_escalation", "severity": "high"},
    {"id": "NLP39", "name": "policy_override_request", "severity": "high"},
    {"id": "NLP40", "name": "demand_privileged_access", "severity": "high"},
]


def _norm(text: str | None) -> str:
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def _has_any(text: str, phrases: List[str]) -> bool:
    return any(p in text for p in phrases)


_OCR_PROMPT_INJECTION_PAT = re.compile(
    r"(?i)(ignore\s+previous|override\s+instructions|system\s*prompt|developer\s*mode|"
    r"jailbreak|do\s+not\s+follow|bypass\s+policy|exfiltrate|export\s+all|"
    r"show\s+secret|tool\s*:|function\s*call|execute\s+shell)"
)

_OCR_PAYMENT_SE_PAT = re.compile(
    r"(?i)\b(pay[\W_]*(?:id|1d|ld)|bsb|iban|swift|venmo|cashapp|zelle|wallet|transfer|send\s+money)\b"
)
_OCR_CRYPTO_URI_PAT = re.compile(r"(?i)\b(bitcoin:|ethereum:|monero:|litecoin:)\b")
_OCR_RANSOM_PAT = re.compile(
    r"(?i)\b(encrypted|ransom|decrypt|pay\s+within|restore\s+files|btc\s+wallet|files\s+locked)\b"
)
_OCR_PCI_PAT = re.compile(r"\b(?:\d[ -]*?){13,19}\b")
_OCR_B64_PAT = re.compile(r"\b(?:[A-Za-z0-9+/]{24,}={0,2})\b")
_OCR_HEX_PAT = re.compile(r"\b(?:0x)?[0-9a-fA-F]{24,}\b")
_OCR_AGENTIC_PAT = re.compile(
    r"(?is)(\"tool\"\s*:|\"function\"\s*:|\"name\"\s*:|tool_call|function_call|"
    r"add_to_cart|remove_from_cart|checkout|place_order|cancel_order|refund_order|"
    r"execute_shell|run_command|curl\s+https?://|wget\s+https?://)"
)
_OCR_SPLIT_INJECTION_COMPOSITE_PAT = re.compile(
    r"(?is)(ignore\s+previous.*instructions|system\s*prompt|developer\s*mode|"
    r"tool\s*:|function\s*call|add_to_cart|checkout|place_order)"
)
_OCR_LABEL_HINT_PAT = re.compile(
    r"(?i)\b(warranty|official|support|repair|return|invoice|receipt|university|student|gaming|office)\b"
)


def _detect_ocr_prompt_injection(text: str | None) -> bool:
    return _detect_ocr_prompt_injection_shared(text)


def _luhn_ok(num: str) -> bool:
    digits = [int(c) for c in re.sub(r"\D", "", num)]
    if len(digits) < 13 or len(digits) > 19:
        return False
    checksum = 0
    parity = len(digits) % 2
    for i, d in enumerate(digits):
        if i % 2 == parity:
            d *= 2
            if d > 9:
                d -= 9
        checksum += d
    return checksum % 10 == 0


def _sanitize_unicode_injection(text: str | None) -> str:
    """Normalize OCR text and strip invisible/control characters."""
    return _sanitize_unicode_injection_shared(text)


def _detect_ocr_encoded_payload(text: str | None) -> Dict[str, Any]:
    return _detect_ocr_encoded_payload_shared(text)


def _normalize_ocr_and_detect(text: str | None) -> Dict[str, Any]:
    return _normalize_ocr_and_detect_shared(text)


def _detect_cross_image_split_injection(texts: List[str]) -> bool:
    return _detect_cross_image_split_injection_shared(texts)


def _detect_qr_label_destination_mismatch(
    qr_codes: List[Dict[str, Any]] | None,
    *,
    image_consistency: Dict[str, Any] | None = None,
) -> bool:
    return _detect_qr_label_destination_mismatch_shared(qr_codes, image_consistency=image_consistency)


def _qr_redirect_probe_cache_ttl_sec() -> int:
    try:
        return max(60, int(os.getenv("QR_REDIRECT_CACHE_TTL_SEC", "1800") or 1800))
    except Exception:
        return 1800


def _qr_redirect_cache_get(url: str) -> Dict[str, Any] | None:
    u = str(url or "").strip()
    if not u:
        return None
    key = hashlib.sha256(u.encode("utf-8")).hexdigest()
    now = int(time.time())
    try:
        from sqlalchemy import text as _text
        from src.app.models.db import db_session

        with db_session() as _db:
            _db.execute(
                _text(
                    """
                    CREATE TABLE IF NOT EXISTS qr_redirect_cache (
                      url_hash TEXT PRIMARY KEY,
                      url_prefix TEXT,
                      result_json TEXT NOT NULL,
                      updated_at INTEGER NOT NULL,
                      expires_at INTEGER NOT NULL
                    )
                    """
                )
            )
            row = _db.execute(
                _text("SELECT result_json FROM qr_redirect_cache WHERE url_hash = :h AND expires_at > :now"),
                {"h": key, "now": now},
            ).fetchone()
        if row and row[0]:
            return json.loads(row[0])
    except Exception:
        return None
    return None


def _qr_redirect_cache_set(url: str, result: Dict[str, Any]) -> None:
    u = str(url or "").strip()
    if not u:
        return
    key = hashlib.sha256(u.encode("utf-8")).hexdigest()
    now = int(time.time())
    ttl = _qr_redirect_probe_cache_ttl_sec()
    try:
        from sqlalchemy import text as _text
        from src.app.models.db import db_session

        with db_session() as _db:
            _db.execute(
                _text(
                    """
                    CREATE TABLE IF NOT EXISTS qr_redirect_cache (
                      url_hash TEXT PRIMARY KEY,
                      url_prefix TEXT,
                      result_json TEXT NOT NULL,
                      updated_at INTEGER NOT NULL,
                      expires_at INTEGER NOT NULL
                    )
                    """
                )
            )
            _db.execute(
                _text(
                    """
                    INSERT INTO qr_redirect_cache
                    (url_hash, url_prefix, result_json, updated_at, expires_at)
                    VALUES (:h, :p, :r, :u, :e)
                    ON CONFLICT (url_hash) DO UPDATE SET url_prefix = EXCLUDED.url_prefix, result_json = EXCLUDED.result_json, updated_at = EXCLUDED.updated_at, expires_at = EXCLUDED.expires_at
                    """
                ),
                {
                    "h": key,
                    "p": u[:180],
                    "r": json.dumps(result),
                    "u": now,
                    "e": now + ttl,
                },
            )
            _db.commit()
    except Exception:
        pass


async def _probe_redirect_chain_now(url: str, *, timeout_s: float = 1.5, max_hops: int = 3) -> Dict[str, Any]:
    try:
        import httpx  # type: ignore
    except Exception:
        return {"enabled": True, "checked": False, "error": "httpx_unavailable", "chain": []}

    chain: List[str] = []
    current = str(url or "").strip()
    if not current:
        return {"enabled": True, "checked": False, "chain": []}
    try:
        async with httpx.AsyncClient(follow_redirects=False, timeout=timeout_s) as client:
            for _ in range(max(1, int(max_hops))):
                chain.append(current)
                try:
                    resp = await asyncio.wait_for(client.head(current), timeout=timeout_s)
                except Exception:
                    break
                loc = str(resp.headers.get("location") or "").strip()
                if not loc or not (300 <= int(resp.status_code) < 400):
                    break
                current = loc
        out = {
            "enabled": True,
            "checked": True,
            "chain": chain[: max(1, int(max_hops) + 1)],
            "final_url": chain[-1] if chain else current,
            "hops": max(0, len(chain) - 1),
        }
        _qr_redirect_cache_set(url, out)
        return out
    except Exception:
        return {"enabled": True, "checked": False, "chain": chain, "error": "redirect_probe_failed"}


async def _probe_redirect_chain(url: str, *, timeout_s: float = 1.5, max_hops: int = 3) -> Dict[str, Any]:
    """Sandboxed redirect probe with cache + async queue for low request latency."""
    enabled = str(os.getenv("QR_REDIRECT_PROBE_ENABLED", "0")).strip().lower() in {"1", "true", "yes", "on"}
    mode = str(os.getenv("QR_REDIRECT_PROBE_MODE", "async")).strip().lower()
    if not enabled:
        return {"enabled": False, "checked": False, "chain": []}
    u = str(url or "").strip()
    if not u:
        return {"enabled": True, "checked": False, "chain": []}
    cached = _qr_redirect_cache_get(u)
    if isinstance(cached, dict):
        out = dict(cached)
        out["cache_hit"] = True
        return out
    if mode in {"off", "disabled", "none"}:
        return {"enabled": True, "checked": False, "chain": [], "pending": False, "cache_hit": False}
    if mode in {"sync", "blocking"}:
        out = await _probe_redirect_chain_now(u, timeout_s=timeout_s, max_hops=max_hops)
        out["cache_hit"] = False
        return out

    # Async mode: queue background probe and return immediately.
    task_key = hashlib.sha256(u.encode("utf-8")).hexdigest()
    t = _QR_REDIRECT_TASKS.get(task_key)
    if not t or t.done():
        _QR_REDIRECT_TASKS[task_key] = asyncio.create_task(
            _probe_redirect_chain_now(u, timeout_s=timeout_s, max_hops=max_hops)
        )
    return {
        "enabled": True,
        "checked": False,
        "pending": True,
        "chain": [u][:1],
        "cache_hit": False,
    }


def _minimize_ocr_text_for_logs(text: str | None, *, max_chars: int = 180) -> str:
    cleaned = scrub_pii((text or "").strip())
    if len(cleaned) <= max_chars:
        return cleaned
    return f"{cleaned[:max_chars]}..."


def _sanitize_image_consistency_for_logs(payload: Dict[str, Any] | None) -> Dict[str, Any]:
    p = payload or {}
    out_images: List[Dict[str, Any]] = []
    for item in (p.get("images") or [])[:8]:
        try:
            out_images.append(
                {
                    "index": int(item.get("index", 0)),
                    "filename": _safe_filename(item.get("filename"), int(item.get("index", 0))),
                    "status": str(item.get("status") or ""),
                    "reasons": [str(x) for x in (item.get("reasons") or [])][:3],
                    "detected": [str(x) for x in (item.get("detected") or [])][:3],
                }
            )
        except Exception:
            continue
    return {
        "status": str(p.get("status") or ""),
        "expected_family": p.get("expected_family"),
        "mismatch_count": int(p.get("mismatch_count") or 0),
        "suspicious_count": int(p.get("suspicious_count") or 0),
        "needs_better_count": int(p.get("needs_better_count") or 0),
        "soft_verify_required": bool(p.get("soft_verify_required")),
        "repeat_mismatch": bool(p.get("repeat_mismatch")),
        "prior_mismatch_count": int(p.get("prior_mismatch_count") or 0),
        "images": out_images,
    }


def _retention_windows() -> Dict[str, str]:
    return {
        "raw_images": "30d",
        "ocr_text_redacted": "14d",
        "decision_trace": "180d",
        "ticket_notes": "365d",
    }


def _safe_filename(name: str | None, idx: int) -> str:
    raw = (name or "").strip()
    if not raw:
        raw = f"upload_{idx + 1}.jpg"
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", raw)
    return safe[:120] or f"upload_{idx + 1}.jpg"


def _expected_product_family(description: str | None, issue_type: str | None) -> str | None:
    text = _norm(f"{description or ''} {issue_type or ''}")
    if any(k in text for k in ("macbook", "laptop", "notebook", "ultrabook", "xps", "thinkpad")):
        return "laptop"
    if any(k in text for k in ("phone", "iphone", "pixel", "galaxy")):
        return "phone"
    if any(k in text for k in ("tablet", "ipad", "surface")):
        return "tablet"
    if any(k in text for k in ("monitor", "display", "screen")):
        return "monitor"
    return None


def _order_exists(db, order_id: str | None) -> bool | None:
    if not order_id:
        return None
    try:
        from sqlalchemy import text as _text

        row = db.execute(_text("SELECT 1 FROM orders WHERE id = :id LIMIT 1"), {"id": order_id}).fetchone()
        return bool(row)
    except Exception:
        return None


def _check_warranty_eligibility(db, order_id: str | None, issue_type: str | None) -> dict:
    _ = issue_type
    if not order_id:
        return {"eligible": None, "reason": "no_order_id"}
    try:
        from sqlalchemy import text as _text
        from datetime import date, timedelta

        row = db.execute(
            _text("SELECT purchase_date, warranty_months FROM orders WHERE id = :id LIMIT 1"),
            {"id": order_id},
        ).fetchone()
        if not row:
            return {"eligible": None, "reason": "order_not_found"}
        purchase = date.fromisoformat(str(row[0])) if row[0] else None
        months = int(row[1] or 12)
        if not purchase:
            return {"eligible": None, "reason": "no_purchase_date"}
        expiry = purchase + timedelta(days=months * 30)
        today = date.today()
        gap = int((expiry - today).days)
        return {
            "eligible": gap >= 0,
            "expires": expiry.isoformat(),
            "gap_days": gap,
            "advice": (
                f"Warranty valid until {expiry.isoformat()} ({gap} days remaining)."
                if gap >= 0
                else f"Warranty expired {abs(gap)} days ago ({expiry.isoformat()})."
            ),
        }
    except Exception:
        return {"eligible": None, "reason": "lookup_error"}


def _count_prior_consistency_mismatches(db, order_id: str | None, *, limit: int = 300) -> int:
    if not order_id:
        return 0
    order_norm = str(order_id)
    order_norm_scrubbed = str(scrub_pii(order_norm))
    try:
        from sqlalchemy import text as _text

        rows = db.execute(
            _text(
                "SELECT input_data, proposed_action FROM decision_logs "
                "WHERE agent_name = 'cv_triage_agent' ORDER BY system_from DESC LIMIT :lim"
            ),
            {"lim": int(max(50, min(2000, limit)))},
        ).fetchall()
    except Exception:
        return 0

    count = 0
    for row in rows or []:
        def _parse_maybe_dict(raw: Any) -> Dict[str, Any]:
            val: Any = raw
            for _ in range(3):
                if isinstance(val, dict):
                    return val
                if isinstance(val, str):
                    s = val.strip()
                    if not s:
                        return {}
                    try:
                        val = json.loads(s)
                        continue
                    except Exception:
                        try:
                            val = ast.literal_eval(s)
                            continue
                        except Exception:
                            return {}
                return {}
            return val if isinstance(val, dict) else {}

        inp = _parse_maybe_dict(row[0])
        act = _parse_maybe_dict(row[1])
        if not isinstance(inp, dict):
            inp = {}
        if not isinstance(act, dict):
            act = {}
        inp_order = str(inp.get("order_id") or "")
        if inp_order not in (order_norm, order_norm_scrubbed):
            continue
        try:
            ic = act.get("image_consistency") if isinstance(act, dict) else {}
            status = str((ic or {}).get("status") or "").lower()
            mismatch_ct = int((ic or {}).get("mismatch_count") or 0)
        except Exception:
            status, mismatch_ct = "", 0
        # Primary signal when detailed image_consistency is available.
        is_mismatch = status in ("mismatch", "suspicious", "soft_verify_required") or mismatch_ct > 0
        # Fallback when redaction strips detailed blobs in decision logs.
        if not is_mismatch:
            try:
                route = str(act.get("suggested_routing") or "").lower()
                has_prompt = bool(str(act.get("user_prompt") or "").strip())
                if route in ("soft_verify", "security_review") and has_prompt:
                    is_mismatch = True
            except Exception:
                pass
        if is_mismatch:
            count += 1
    return count


async def _evaluate_uploaded_images_consistency(
    *,
    sanitized_images: List[Dict[str, Any]],
    description: str | None,
    issue_type: str | None,
    order_id: str | None,
) -> Dict[str, Any]:
    def _detect_unrelated_overlay_text(text: str) -> bool:
        """Heuristic: flag obvious stock/sticker/overlay text that isn't evidence.

        This is not "prompt injection" detection; it helps catch demos/tests where
        images contain arbitrary overlay text (e.g., "Hello World" + emojis) that
        should not be treated as a valid product/damage photo.
        """
        t = (text or "").strip()
        if not t:
            return False
        tl = t.lower()
        if "hello world" in tl or "lorem ipsum" in tl:
            return True
        # Emoji/unicode-heavy overlays (common in stock photos or adversarial stickers).
        try:
            non_ascii = sum(1 for c in t if ord(c) > 127)
            if non_ascii >= 2:
                return True
        except Exception:
            pass
        # If it's mostly symbols/punctuation, it's likely an overlay rather than an order id or serial.
        try:
            alnum = sum(1 for c in t if c.isalnum())
            if len(t) >= 12 and (alnum / max(1, len(t))) < 0.35:
                return True
        except Exception:
            pass
        return False

    expected_family = _expected_product_family(description, issue_type)
    images_out: List[Dict[str, Any]] = []
    mismatch_count = 0
    needs_better_count = 0
    suspicious_count = 0
    ocr_prompt_injection = False

    # Keep detector/model usage best-effort so uploads never fail due to CV deps.
    # If both model env-vars are explicitly set to empty string, skip detector entirely
    # (prevents test hangs from YOLO loads when models are intentionally disabled).
    detector = None
    _detector_model_env = (
        (os.getenv("CV_DETECTOR_MODEL") or "").strip()
        or (os.getenv("CV_DAMAGE_YOLO_MODEL") or "").strip()
    )
    if _detector_model_env:  # Only load detector when a model is explicitly configured
        try:
            from src.app.services.cv_object_detector import CVObjectDetector

            detector = CVObjectDetector(model_path=_detector_model_env)
        except Exception:
            detector = None

    provider = None
    try:
        from src.app.services.cv_provider import ManagedCVProvider

        provider = ManagedCVProvider()
    except Exception:
        provider = None

    for idx, s in enumerate((sanitized_images or [])[:8]):
        filename = _safe_filename(s.get("filename"), idx)
        status = "match"
        reasons: List[str] = []
        labels: List[str] = []
        mapped: List[str] = []
        ocr_text = ""

        if str(s.get("status") or "") != "sanitized":
            status = "suspicious"
            reasons.append("invalid_or_unsupported_image")
        else:
            b = s.get("bytes") or b""
            if provider is not None:
                try:
                    labels, ocr_text, *_ = await provider.get_labels_and_text(b)
                    labels = [str(x).lower() for x in (labels or [])][:10]
                except Exception:
                    labels, ocr_text = [], ""
            if detector is not None:
                try:
                    from src.app.services.cv_object_detector import CVObjectDetector

                    det = detector.detect(b)
                    sm = CVObjectDetector.summarize(det)
                    mapped = [str(x) for x in (sm.get("unique") or []) if x][:5]
                except Exception:
                    mapped = []

            joined_labels = " ".join(labels).lower()
            product_like = ("device" in mapped) or any(
                k in joined_labels for k in ("laptop", "notebook", "macbook", "computer", "keyboard", "screen", "display")
            )
            unrelated_food = any(x in ("apple", "banana", "orange", "pizza", "donut", "cake", "broccoli", "carrot") for x in mapped)

            if expected_family == "laptop":
                if unrelated_food:
                    status = "mismatch"
                    reasons.append("unrelated_object_detected")
                elif not product_like:
                    status = "mismatch"
                    reasons.append("no_laptop_signal_detected")
            elif expected_family == "phone":
                if product_like and any(k in joined_labels for k in ("laptop", "macbook", "notebook")):
                    status = "mismatch"
                    reasons.append("product_family_mismatch")

            if not (ocr_text or "").strip() and not mapped:
                if status == "match":
                    status = "needs_better_image"
                reasons.append("low_visual_evidence")

            if _detect_ocr_prompt_injection(ocr_text):
                ocr_prompt_injection = True
                if status == "match":
                    status = "suspicious"
                reasons.append("ocr_prompt_pattern_detected")
            elif _detect_unrelated_overlay_text(ocr_text):
                if status == "match":
                    status = "suspicious"
                reasons.append("ocr_unrelated_overlay_detected")

            if order_id and ocr_text:
                lt = ocr_text.lower()
                if ("order" in lt or "invoice" in lt) and str(order_id) not in ocr_text:
                    reasons.append("order_id_not_visible_or_mismatch")

        if status in ("mismatch", "suspicious"):
            mismatch_count += 1
        if status == "needs_better_image":
            needs_better_count += 1
        if status == "suspicious":
            suspicious_count += 1

        images_out.append(
            {
                "index": idx,
                "filename": filename,
                "status": status,
                "reasons": list(dict.fromkeys(reasons))[:4],
                "detected": mapped,
                "ocr_text": _minimize_ocr_text_for_logs(ocr_text, max_chars=240),
            }
        )

    summary_status = "match"
    if mismatch_count > 0:
        summary_status = "mismatch"
    elif needs_better_count > 0:
        summary_status = "needs_better_image"

    # User-facing prompt (non-technical, polite) derived from the actual reasons.
    prompt = None
    try:
        all_reasons: set[str] = set()
        for im in images_out:
            rs = im.get("reasons") if isinstance(im, dict) else None
            if isinstance(rs, list):
                for r in rs:
                    if r:
                        all_reasons.add(str(r))
    except Exception:
        all_reasons = set()
    if any(r in all_reasons for r in ("qr_external_url_detected",)):
        prompt = (
            "For your security, we can't accept photos that include QR codes or external links. "
            "Please upload a new, unedited photo of the item and the damaged area (no stickers, text overlays, or QR codes)."
        )
    elif any(r in all_reasons for r in ("qr_code_detected",)):
        prompt = (
            "For your security, we can't accept photos that include QR codes. "
            "Please upload a new, unedited photo of the item and the damaged area (no text overlays or QR codes)."
        )
    elif any(r in all_reasons for r in ("ocr_prompt_pattern_detected",)):
        prompt = (
            "We couldn't verify one or more photos because they appear to include hidden instructions or unrelated text. "
            "Please upload a new, unedited photo of the item and the damaged area (no stickers or text overlays)."
        )
    elif any(r in all_reasons for r in ("ocr_unrelated_overlay_detected",)):
        prompt = (
            "We couldn't verify one or more photos because they appear to include text overlays or stickers. "
            "Please upload a new, unedited photo of the item and the damaged area (no overlays)."
        )
    elif summary_status == "mismatch":
        prompt = "Some uploaded photos do not appear to match your return request. Please verify or replace mismatched images."
    elif summary_status == "needs_better_image":
        prompt = "Some photos are unclear. Please upload sharper images before proceeding."

    return {
        "status": summary_status,
        "expected_family": expected_family,
        "mismatch_count": mismatch_count,
        "suspicious_count": suspicious_count,
        "needs_better_count": needs_better_count,
        "soft_verify_required": bool(summary_status in ("mismatch", "needs_better_image")),
        "ocr_prompt_injection": bool(ocr_prompt_injection),
        "images": images_out,
        "prompt": prompt,
    }


def _evaluate_cv_rules(
    *,
    description: str,
    issue_type: str,
    analysis: Dict[str, Any],
    extracted_text: str,
    labels: List[str],
    reverse_hits: List[Dict[str, Any]],
    fraud_score: float | None,
    fraud_level: str | None,
    trust: Dict[str, Any] | None,
    order_id: str | None,
    qr_codes: List[Dict[str, Any]] | None = None,
    exif_flags: Dict[str, Any] | None = None,
    file_validation: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    support_thr = _get_support_thresholds()
    # Prefer calibrated confidence when available for gating
    try:
        conf_raw = analysis.get("confidence_calibrated") if isinstance(analysis, dict) else None
        conf_val = float(conf_raw) if conf_raw is not None else (float(analysis.get("confidence")) if analysis.get("confidence") is not None else None)
    except Exception:
        conf_val = None
    text = _norm(description)
    rules_triggered: List[Dict[str, Any]] = []
    signals: Dict[str, Any] = {}
    ocr_det = _normalize_ocr_and_detect(extracted_text)

    def add(rule_id: str, reason: str):
        rule = next((r for r in CV_SECURITY_RULES if r["id"] == rule_id), None)
        if not rule:
            return
        rules_triggered.append({**rule, "reason": reason})

    if reverse_hits:
        add("CV01", "reverse_image_hits")
        signals["duplicate_image_detected"] = True
    if conf_val is not None and float(conf_val) < float(support_thr["cv_confidence_low_min"]):
        add("CV05", "low_cv_confidence")
    if analysis.get("severity") in ("major", "high", "critical"):
        add("CV06", "high_severity_damage")
    if not labels:
        add("CV04", "no_labels")
    if fraud_level == "high":
        add("CV21", "fraud_score_high")
        signals["fraud_score_high"] = True
    elif fraud_level == "medium":
        add("CV22", "fraud_score_medium")
        signals["fraud_score_medium"] = True
    if _has_any(text, ["chargeback", "dispute", "bank dispute"]):
        add("CV17", "chargeback_threat")
    if _has_any(text, ["lawyer", "legal action", "sue", "court"]):
        add("CV18", "legal_threat")
    if _has_any(text, ["price match", "found cheaper", "cheaper elsewhere"]):
        add("CV19", "price_match_claim")
    if _has_any(text, ["replacement", "exchange", "swap for"]):
        add("CV20", "alternate_product_request")
    if _has_any(text, ["counterfeit", "fake", "not genuine"]):
        add("CV26", "counterfeit_indicator")
    if _has_any(text, ["damaged box only", "box damage"]):
        add("CV38", "damaged_packaging_only")
    if _has_any(text, ["manual review", "human review", "supervisor"]):
        add("CV40", "manual_review_requested")
    if issue_type and issue_type.lower() in ("refund", "return") and _has_any(text, ["late", "past return window", "expired"]):
        add("CV13", "return_window_expired")
    if extracted_text and "invoice" not in extracted_text.lower():
        add("CV10", "invoice_missing")
    if order_id and extracted_text and order_id not in extracted_text:
        add("CV09", "ocr_order_id_mismatch")
    if _detect_ocr_prompt_injection(extracted_text):
        add("CV41", "ocr_prompt_injection")
        signals["ocr_prompt_injection"] = True
    if bool(ocr_det.get("payment_social_engineering")):
        add("CV16", "payment_social_engineering")
        signals["payment_social_engineering"] = True
    if bool(ocr_det.get("pci_card_exposed")):
        add("CV10", "pci_card_exposed")
        signals["pci_card_exposed"] = True
    if bool(ocr_det.get("crypto_payment_uri")):
        add("CV17", "crypto_payment_uri")
        signals["crypto_payment_uri"] = True
    if bool(ocr_det.get("ransomware_indicator")):
        add("CV18", "ransomware_indicator")
        signals["ransomware_indicator"] = True
    if bool(ocr_det.get("encoded_payload_detected")):
        add("CV41", "encoded_payload_detected")
        signals["encoded_payload_detected"] = True
    if bool(ocr_det.get("agentic_tool_injection")):
        add("CV41", "agentic_tool_injection")
        signals["agentic_tool_injection"] = True
        signals["agentic_tool_abuse"] = True
    if bool(ocr_det.get("homoglyph_injection")):
        signals["homoglyph_injection"] = True
        signals["unicode_obfuscation"] = True
    if qr_codes:
        payload_types = {str(c.get("payload_type") or "") for c in (qr_codes or [])}
        if "vcard" in payload_types:
            signals["qr_payload_vcard"] = True
        if "wifi_credentials" in payload_types:
            signals["qr_payload_wifi"] = True
        if len(payload_types - {""}) > 1:
            signals["qr_multi_mismatch"] = True
    if bool(exif_flags and exif_flags.get("exif_text_injection")):
        signals["exif_text_injection"] = True
    if bool(file_validation and file_validation.get("polyglot_suspected")):
        signals["polyglot_suspected"] = True
    if bool(file_validation and file_validation.get("invisible_text_suspected")):
        signals["steg_suspicious"] = True
    if trust and trust.get("returns_last_30_days", 0) >= int(support_thr["excessive_returns_last_30_days_min"]):
        add("CV31", "excessive_returns_rate")
    return {
        "rules": rules_triggered,
        "signals": signals,
        "ocr_normalized": {
            "text": str(ocr_det.get("normalized_text") or "")[:1200],
            "encoded_payload_kind": ocr_det.get("encoded_payload_kind"),
            "pci_match_count": int(ocr_det.get("pci_match_count") or 0),
        },
    }


def _build_evidence_tags(
    *,
    rule_signals: Dict[str, Any],
    forensics: Dict[str, Any],
    fraud_level: str | None,
    supplier_signals: Dict[str, Any],
    tier2: Dict[str, Any] | None = None,
    expected_serial: str | None,
    observed_serial: str | None,
) -> List[str]:
    support_thr = _get_support_thresholds()
    tags: List[str] = []
    if rule_signals.get("duplicate_image_detected"):
        tags.append("duplicate_image_detected")
    try:
        if float(forensics.get("manipulation_score") or 0.0) >= float(support_thr["manipulation_score_high_min"]):
            tags.append("manipulation_detected")
    except Exception:
        pass
    if expected_serial and observed_serial and expected_serial.strip() and observed_serial.strip():
        if expected_serial.strip() != observed_serial.strip():
            tags.append("serial_mismatch")
    if rule_signals.get("ocr_prompt_injection"):
        tags.append("ocr_prompt_injection")
    if rule_signals.get("payment_social_engineering"):
        tags.append("payment_social_engineering")
    if rule_signals.get("pci_card_exposed"):
        tags.append("pci_card_exposed")
    if rule_signals.get("crypto_payment_uri"):
        tags.append("crypto_payment_uri")
    if rule_signals.get("ransomware_indicator"):
        tags.append("ransomware_indicator")
    if rule_signals.get("qr_payload_vcard"):
        tags.append("qr_payload_vcard")
    if rule_signals.get("qr_payload_wifi"):
        tags.append("qr_payload_wifi")
    if rule_signals.get("qr_multi_mismatch"):
        tags.append("qr_multi_mismatch")
    if rule_signals.get("qr_label_destination_mismatch"):
        tags.append("qr_label_destination_mismatch")
    if rule_signals.get("cross_image_split_injection"):
        tags.append("cross_image_split_injection")
    if rule_signals.get("agentic_tool_injection") or rule_signals.get("agentic_tool_abuse"):
        tags.append("agentic_tool_abuse")
    if rule_signals.get("image_consistency_mismatch"):
        tags.append("image_consistency_mismatch")
    if rule_signals.get("repeat_image_consistency_mismatch"):
        tags.append("repeat_image_consistency_mismatch")
    if rule_signals.get("order_id_not_found"):
        tags.append("order_id_not_found")
    if fraud_level == "high":
        tags.append("fraud_score_high")
    if supplier_signals.get("supplier_verified") is False:
        tags.append("supplier_unverified")
    if supplier_signals.get("invoice_mismatch") is True or supplier_signals.get("edi_status") in ("mismatch", "error", "failed"):
        tags.append("invoice_mismatch")
    try:
        tier2_tags = (tier2 or {}).get("evidence_tags") or []
        for t in tier2_tags:
            if t not in tags:
                tags.append(t)
    except Exception:
        pass
    return tags


def _evaluate_nlp_rules(message: str) -> Dict[str, Any]:
    text = _norm(message)
    rules_triggered: List[Dict[str, Any]] = []
    signals: Dict[str, Any] = {}

    def add(rule_id: str, reason: str):
        rule = next((r for r in NLP_COMPLIANCE_RULES if r["id"] == rule_id), None)
        if not rule:
            return
        rules_triggered.append({**rule, "reason": reason})

    if re.search(r"\b(?:\d[ -]*?){13,16}\b", text):
        add("NLP01", "card_number_pattern")
        signals["pci_card_number"] = True
    if "cvv" in text or "cvc" in text:
        add("NLP02", "cvv_request")
    if "full card" in text or "full pan" in text:
        add("NLP03", "full_pan_request")
    if re.search(r"\b\d{3}-\d{2}-\d{4}\b", text):
        add("NLP04", "ssn_pattern")
    if "driver license" in text:
        add("NLP05", "driver_license")
    if "passport" in text:
        add("NLP06", "passport")
    if "reset password" in text and "without" in text:
        add("NLP07", "password_reset_social_engineering")
    if "takeover" in text or "access account" in text:
        add("NLP08", "account_takeover")
    if ("refund" in text and "new account" in text) or ("refund" in text and "bank account" in text):
        add("NLP09", "refund_to_new_account")
    if "wire transfer" in text:
        add("NLP10", "wire_transfer")
    if "gift card" in text:
        add("NLP11", "gift_card")
    if "supplier email" in text or "supplier contact" in text:
        add("NLP12", "supplier_contact_leak")
    if "internal policy" in text or "system prompt" in text:
        add("NLP13", "internal_policy")
    if "bypass" in text or "skip verification" in text:
        add("NLP14", "bypass_verification")
    if "delete everything" in text or "erase all data" in text:
        add("NLP15", "excessive_privacy_request")
    if "show system prompt" in text:
        add("NLP16", "system_prompt_probe")
    if "jailbreak" in text or "ignore policy" in text:
        add("NLP17", "jailbreak")
    if "export all data" in text or "dump database" in text:
        add("NLP18", "data_exfiltration_request")
    if "confidential" in text or "private data" in text:
        add("NLP19", "confidential_data_request")
    if "urgent" in text and "refund" in text:
        add("NLP20", "financial_pressure")
    if "override" in text and "policy" in text:
        add("NLP21", "human_override")
    if "regulator" in text or "complaint to" in text:
        add("NLP22", "regulatory_threat")
    if "iso27001" in text:
        add("NLP23", "iso27001")
    if "iso42001" in text:
        add("NLP24", "iso42001")
    if "soc 2" in text or "soc2" in text:
        add("NLP25", "soc2")
    if "delete my data" in text or "gdpr" in text:
        add("NLP26", "gdpr_delete")
    if "hipaa" in text:
        add("NLP27", "hipaa")
    if "withdraw consent" in text:
        add("NLP28", "consent_withdrawal")
    if "export customer data" in text:
        add("NLP29", "export_customer_data")
    if "access logs" in text:
        add("NLP30", "access_logs_request")
    if "insider" in text or "internal" in text and "leak" in text:
        add("NLP31", "insider_threat")
    if "api key" in text:
        add("NLP32", "api_key_request")
    if "config dump" in text:
        add("NLP33", "config_dump")
    if "payment token" in text:
        add("NLP34", "payment_token")
    if "bank change" in text and "supplier" in text:
        add("NLP35", "supplier_bank_change")
    if "invoice" in text and "redirect" in text:
        add("NLP36", "invoice_redirect")
    if "chargeback" in text:
        add("NLP37", "threaten_chargeback")
    if "legal action" in text or "sue" in text:
        add("NLP38", "legal_escalation")
    if "override policy" in text:
        add("NLP39", "policy_override")
    if "admin access" in text or "root access" in text:
        add("NLP40", "demand_privileged_access")

    return {"rules": rules_triggered, "signals": signals}


def _fetch_supplier_signals(order_id: str | None) -> Dict[str, Any]:
    if not order_id:
        return {}
    try:
        return ERPEDIConnector().get_supplier_signals(order_id)
    except Exception:
        return {}


class ComplaintTriageRequest(BaseModel):
    message: str
    email_headers: Optional[Dict[str, str]] = None
    from_domain: Optional[str] = None
    order_id: Optional[str] = None


@router.post("/triage")
def triage(req: ComplaintTriageRequest, db=Depends(get_db), request: Request = None) -> Dict:
    nlp = ComplaintNLP()
    parsed = nlp.classify(req.message)

    # Email auth + BEC heuristics
    auth = validate_email_auth(req.email_headers or {})
    bec = detect_bec_indicators(req.message, req.from_domain)

    nlp_rules = _evaluate_nlp_rules(req.message)
    contract_nlp = None
    contract_quality = None
    try:
        flags = get_flags() or {}
    except Exception:
        flags = {}
    try:
        contract_enabled = bool(flags.get("CONTRACT_NLP_ASSIST_ENABLED", True))
        contract_llm = bool(flags.get("CONTRACT_NLP_LLM_ASSIST_ENABLED", False))
    except Exception:
        contract_enabled = True
        contract_llm = False
    if contract_enabled and is_contract_like_text(req.message):
        try:
            contract_nlp = run_contract_assist(req.message, enable_llm=contract_llm)
            try:
                contract_quality = evaluate_quality_gate(req.message, contract_nlp or {})
            except Exception:
                contract_quality = None
        except Exception:
            contract_nlp = None
    # Build evidence context (order/payment lookup could be extended)
    evidence = {
        "nlp": parsed,
        "email_auth": auth,
        "bec_indicators": bec,
        "nlp_rules": nlp_rules.get("rules"),
        "contract_nlp": contract_nlp,
        "contract_quality": contract_quality,
    }

    # If an order_id is present in the message or request, fetch order status
    order_id = req.order_id or parsed.get("entities", {}).get("order_id")
    if order_id:
        try:
            from sqlalchemy import text as _text
            row = db.execute(_text("SELECT id, status, total_cents, created_at FROM orders WHERE id = :id"), {"id": order_id}).fetchone()
            if row:
                evidence["order"] = {
                    "order_id": row[0],
                    "status": row[1],
                    "total_cents": row[2],
                    "created_at": str(row[3]),
                }
        except Exception:
            pass

    # Severity & action recommendation
    severity = "medium"
    recommended_action = "investigate"
    if parsed["intent"] in ("refund_request", "payment_failure"):
        recommended_action = "create_ticket_support"
        severity = "high" if auth.get("dmarc_pass") is False else "medium"
    if parsed["intent"] in ("fraud_alert", "shipment_verification"):
        recommended_action = "security_review"
        severity = "high" if any(bec.values()) else "medium"
    if parsed["intent"] == "recall_notice":
        recommended_action = "compliance_review"
        severity = "high"

    # Auto-quarantine if DMARC fails and BEC indicators present
    if auth.get("dmarc_pass") is False and any(bec.values()):
        severity = "critical"
        recommended_action = "quarantine"

    # Escalate on compliance-critical NLP signals
    if any(r.get("severity") == "high" for r in (nlp_rules.get("rules") or [])):
        severity = "high"
        recommended_action = "security_review"
    # Apply contract NLP quality gate influence
    try:
        if isinstance(contract_quality, dict):
            if contract_quality.get("decision") in ("review", "abstain"):
                recommended_action = "security_review"
                if contract_quality.get("decision") == "abstain":
                    severity = "high"
    except Exception:
        pass

    # Persist decision
    tenant_id = None
    customer_tier = None
    try:
        if request is not None and hasattr(request, "headers"):
            tenant_id = request.headers.get("X-Tenant-Id") or request.headers.get("x-tenant-id")
            customer_tier = request.headers.get("X-User-Tier") or request.headers.get("x-user-tier")
    except Exception:
        tenant_id = None
        customer_tier = None

    decision_id = log_decision(
        agent_name="complaint_triage_agent",
        input_data={"message": req.message},
        retrieved_context=evidence,
        proposed_action={"action": recommended_action, "severity": severity},
        agent_reasoning=f"intent={parsed['intent']}; auth={auth}; bec={bec}",
        policy_version="v1",
        approval_required=(severity == "high"),
        execution_status="queued",
        tenant_id=tenant_id,
    )
    try:
        log_trace_event(
            trace_id=decision_id,
            event_type="policy_gate",
            source_type="agent",
            source_id="NLP_Compliance_Agent",
            target_type="system",
            target_id=None,
            payload={"rules": nlp_rules.get("rules"), "signals": nlp_rules.get("signals")},
        )
    except Exception:
        pass
    try:
        log_trace_event(
            trace_id=decision_id,
            event_type="agent_handoff",
            source_type="agent",
            source_id="complaint_triage_agent",
            target_type="agent",
            target_id=recommended_action,
            payload={"severity": severity, "intent": parsed.get("intent"), "order_id": order_id},
        )
    except Exception:
        pass
    if contract_nlp:
        try:
            log_trace_event(
                trace_id=decision_id,
                event_type="contract_nlp_analysis",
                source_type="agent",
                source_id="Contract_NLP_Agent",
                target_type="system",
                target_id=None,
                payload={
                    "mode": contract_nlp.get("mode"),
                    "score": contract_nlp.get("score"),
                    "risks": contract_nlp.get("risks"),
                },
            )
        except Exception:
            pass
        try:
            if contract_quality:
                log_trace_event(
                    trace_id=decision_id,
                    event_type="nlp_quality_gate",
                    source_type="agent",
                    source_id="Contract_NLP_Agent",
                    target_type="system",
                    target_id=None,
                    payload=contract_quality,
                )
        except Exception:
            pass

    # Record Prometheus metric
    try:
        record_complaint_triage(parsed["intent"], severity)
    except Exception:
        pass

    # Forward triage context to JanuSec for correlation if enabled
    try:
        js = JanuSecClient()
        if js.enabled():
            js.send_triage({
                "intent": parsed["intent"],
                "severity": severity,
                "evidence": evidence,
                "decision_id": decision_id,
            })
    except Exception:
        pass

    ticket_id = None
    tenant_id_for_nqe = tenant_id
    if recommended_action in ("create_ticket_support", "security_review", "compliance_review"):
        tenant_id = None
        try:
            if request is not None and hasattr(request, "headers"):
                tenant_id = request.headers.get("X-Tenant-Id") or request.headers.get("x-tenant-id")
        except Exception:
            tenant_id = None
        signals = {}
        try:
            signals = {"cv_fraud_high": severity in ("high", "critical"), "nlp_compliance": bool(nlp_rules.get("rules"))}
        except Exception:
            signals = {}
        playbook = select_playbook(signals, severity=severity)
        evidence_snapshot = build_evidence_snapshot({
            "security": {"signals": signals},
            "trace_id": decision_id,
        })
        t = TicketingAgent().create_ticket(
            title=f"{parsed['intent']} triage",
            description=f"Decision {decision_id} evidence: {evidence}",
            severity=severity,
            tenant_id=tenant_id,
            reason_code=recommended_action,
            trace_id=decision_id,
            policy_version="v1",
            customer_tier=customer_tier,
            playbook=playbook,
            evidence_snapshot=evidence_snapshot,
        )
        ticket_id = t.id
        try:
            log_trace_event(
                trace_id=decision_id,
                event_type="human_escalation",
                source_type="agent",
                source_id="TicketingAgent",
                target_type="human",
                target_id="Support",
                payload={"ticket_id": ticket_id, "reason": recommended_action, "severity": severity},
            )
        except Exception:
            pass

    # Next-Question Engine (NQE): guided evidence capture for support flows
    nqe_questions: List[Dict[str, Any]] = []
    try:
        missing_fields = []
        if not order_id:
            missing_fields.append("order_id")
        if parsed.get("intent") in ("refund_request", "payment_failure") and not parsed.get("entities", {}).get("amount"):
            missing_fields.append("amount")
        message_lower = (req.message or "").lower()
        category = "laptop" if "laptop" in message_lower else "general"
        nqe_input = NQEInput(
            intent=parsed.get("intent") or "refund_request",
            product_category=category,
            symptom=None,
            timeline_days=None,
            risk_score=0.0,
            missing_fields=missing_fields,
            tenant_id=tenant_id_for_nqe,
            trace_id=decision_id,
        )
        engine = NextQuestionEngine(Retriever(), QuestionTemplateCatalog())
        nqe_questions = [q.model_dump() for q in engine.propose(nqe_input)]
        try:
            log_trace_event(
                trace_id=decision_id,
                event_type="next_questions",
                source_type="agent",
                source_id="NQE_Agent",
                target_type="user",
                target_id=None,
                payload={
                    "intent": nqe_input.intent,
                    "category": nqe_input.product_category,
                    "questions": nqe_questions,
                },
            )
        except Exception:
            pass
    except Exception:
        nqe_questions = []

    # Create a lightweight case for triage so UI can reference a case_id
    case_id = None
    try:
        case_id = create_case(
            order_id=order_id,
            issue_type=parsed.get("intent") or "triage",
            description=scrub_pii(req.message),
            tenant_id=tenant_id,
        )
    except Exception:
        case_id = None

    security_matrix = _build_complaint_security_matrix(
        security_details={
            "severity": severity,
            "signals": (nlp_rules.get("signals") if isinstance(nlp_rules, dict) else {}) or {},
            "mitre_atlas": (nlp_rules.get("mitre_atlas") if isinstance(nlp_rules, dict) else []) or [],
            "owasp_llm_top10": (nlp_rules.get("owasp_llm_top10") if isinstance(nlp_rules, dict) else []) or [],
        },
        security_severity=severity,
        nlp_rules=nlp_rules,
        recommended_route=recommended_action,
    )
    try:
        log_trace_event(
            trace_id=decision_id,
            event_type="security_scan",
            source_type="agent",
            source_id="Security_Observer_Agent",
            target_type="system",
            target_id=None,
            payload={"severity": severity, "security_matrix": security_matrix, "maestro": security_matrix.get("maestro", [])},
        )
    except Exception:
        pass

    return {
        "intent": parsed["intent"],
        "confidence": parsed["confidence"],
        "entities": parsed["entities"],
        "email_auth": auth,
        "bec_indicators": bec,
        "severity": severity,
        "recommended_action": recommended_action,
        "decision_id": decision_id,
        "ticket_id": ticket_id,
        "security_matrix": security_matrix,
        "human_review": {"status": "pending" if ticket_id else "not_required", "ticket_id": ticket_id},
        "next_questions": nqe_questions,
        # Frontend-friendly aliases
        "case_id": case_id,
        "analysis": {
            "intent": parsed["intent"],
            "confidence": parsed["confidence"],
            "entities": parsed["entities"],
            "severity": severity,
        },
        "contract_nlp": contract_nlp,
        "suggested_routing": recommended_action,
        "verdict": recommended_action,
    }


@router.post("/submit")
async def submit_complaint(
    order_id: str = Form(...),
    issue_type: str = Form(...),
    description: str = Form(...),
    playbook_override: Optional[str] = Form(None),
    force_tier2: Optional[bool] = Form(None),
    images: list[UploadFile] = File(default=[]),
    db=Depends(get_db),
    request: Request = None,
) -> Dict:
    """Submit a complaint with images; returns case id + preliminary CV analysis.

    Sanitizes uploads, runs CV/OCR triage, persists case state, and returns a
    preliminary routing decision with evidence metadata.
    """
    from src.app.services.image_intake import sanitize_image
    from src.app.services.cv_triage_basic import BasicCVTriage
    from src.app.services.cv_provider import ManagedCVProvider

    # Sanitize uploads before CV/OCR processing and case persistence.
    sanitize_t0 = None
    try:
        import time as _t
        sanitize_t0 = _t.perf_counter()
    except Exception:
        sanitize_t0 = None
    sanitized = []
    blocked_uploads: List[Dict[str, Any]] = []
    for idx, img in enumerate(images or []):
        content = await img.read()
        gate = strict_image_ingest_gate(
            filename=_safe_filename(getattr(img, "filename", None), idx),
            content_type=getattr(img, "content_type", None),
            blob=content,
            size_bytes=len(content),
        )
        if bool(gate.get("blocked")):
            blocked_uploads.append(
                {
                    "index": idx,
                    "filename": _safe_filename(getattr(img, "filename", None), idx),
                    "reasons": list(gate.get("block_reasons") or []),
                    "ingest_gate": gate.get("ingest_gate"),
                }
            )
            continue
        s = sanitize_image(content)
        try:
            s["filename"] = _safe_filename(getattr(img, "filename", None), idx)
        except Exception:
            s["filename"] = _safe_filename(None, idx)
        sanitized.append(s)
    if blocked_uploads:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "ingest_gate_blocked",
                "message": "One or more uploaded images failed strict ingest checks.",
                "blocked_uploads": blocked_uploads[:8],
            },
        )
    sanitize_ms = None
    try:
        if sanitize_t0 is not None:
            sanitize_ms = int((_t.perf_counter() - sanitize_t0) * 1000)
    except Exception:
        sanitize_ms = None

    # Stage-1 (fast path): file structure and EXIF text checks.
    file_validation_flags: Dict[str, Any] = {"polyglot_suspected": False, "results": []}
    exif_flags: Dict[str, Any] = {"exif_text_injection": False, "results": []}
    try:
        for s in (sanitized or [])[:8]:
            blob = s.get("bytes") or b""
            fv = validate_image_blob(blob)
            file_validation_flags["results"].append(
                {
                    "filename": s.get("filename"),
                    "ok": bool(fv.ok),
                    "file_type": fv.file_type,
                    "suspicious": list(fv.suspicious or []),
                }
            )
            if "polyglot_signature_detected" in (fv.suspicious or []) or "trailing_payload_after_eof" in (fv.suspicious or []):
                file_validation_flags["polyglot_suspected"] = True
            ex = analyze_exif(blob)
            exif_flags["results"].append(
                {
                    "filename": s.get("filename"),
                    "suspicious_flags": list(ex.suspicious_flags or []),
                    "exif_text_signals": list(ex.exif_text_signals or []),
                }
            )
            if "exif_text_injection" in (ex.suspicious_flags or []):
                exif_flags["exif_text_injection"] = True
    except Exception:
        pass

    # Managed CV analysis (first image) if configured
    labels: list[str] = []
    extracted_text = ""
    cv_dt_ms = 0
    try:
        if sanitized:
            import time as _t
            _t0 = _t.perf_counter()
            labels, extracted_text, *_ = await ManagedCVProvider().get_labels_and_text(sanitized[0].get("bytes") or b"")
            cv_dt_ms = int((_t.perf_counter() - _t0) * 1000)
    except Exception:
        pass

    # Stage-2 (deep path): only run heavier multi-contrast OCR when Stage-1 hints risk.
    try:
        stage1_ocr = _normalize_ocr_and_detect(extracted_text)
        # Stage-B OCR should also run when Stage-A text is empty/very weak.
        _stage1_txt = str(extracted_text or "").strip()
        deep_trigger = bool(
            (not _stage1_txt)
            or (len(_stage1_txt) < 12)
            or stage1_ocr.get("encoded_payload_detected")
            or stage1_ocr.get("homoglyph_injection")
            or stage1_ocr.get("payment_social_engineering")
            or exif_flags.get("exif_text_injection")
            or file_validation_flags.get("polyglot_suspected")
        )
        if deep_trigger and sanitized:
            from src.app.cv.cv_pipeline import run_risk_triggered_multicontrast_ocr

            deep = run_risk_triggered_multicontrast_ocr(
                sanitized[0].get("bytes") or b"",
                ocr_provider=os.getenv("CV_OCR_PROVIDER"),
                enabled=True,
            )
            deep_text = str(deep.get("best_text") or "").strip()
            if len(deep_text) > len(str(extracted_text or "").strip()):
                extracted_text = deep_text
            if bool(deep.get("invisible_text_suspected")):
                stage1_ocr["invisible_text_suspected"] = True
        if bool(stage1_ocr.get("invisible_text_suspected")):
            file_validation_flags["invisible_text_suspected"] = True
    except Exception:
        pass

    # Analyze all uploaded images for product consistency; this powers soft verification UX.
    image_consistency = await _evaluate_uploaded_images_consistency(
        sanitized_images=sanitized,
        description=description,
        issue_type=issue_type,
        order_id=order_id,
    )

    # Barcode/QR payload scan (best-effort) to catch encoded prompt-injection text.
    qr_decode_hits: List[Dict[str, Any]] = []
    qr_prompt_injection = False
    qr_external_url = False
    qr_payload_types: set[str] = set()
    qr_multi_mismatch = False
    qr_review_required = False
    qr_benign_detected = False
    qr_redirect_probe: Dict[str, Any] = {"enabled": False, "checked": False, "chain": []}
    try:
        from src.app.rules.barcode_decode import decode_barcodes

        qr = decode_barcodes(
            [
                (str(s.get("filename") or f"img_{i + 1}.jpg"), s.get("bytes") or b"")
                for i, s in enumerate(sanitized or [])
                if str(s.get("status") or "") == "sanitized"
            ]
        )
        # Attach QR decoder diagnostics to the security payload so traces and decision logs show reasons
        try:
            qr_reasons = getattr(qr, "reasons", []) or []
            if qr_reasons:
                # Ensure image_consistency carries per-upload reasons already; surface at security_payload level
                security_payload = locals().get("security_payload") or {}
                diagnostics = security_payload.get("diagnostics", {}) if isinstance(security_payload, dict) else {}
                diagnostics.setdefault("qr_decoder", []).extend(qr_reasons)
                security_payload["diagnostics"] = diagnostics
                # write back into local scope for subsequent observer use
                locals()["security_payload"] = security_payload
        except Exception:
            logger = logging.getLogger("shopsquire.support_complaints")
            logger.exception("Failed to attach qr decoder diagnostics")
        qr_decode_hits = qr.codes or []
        for c in qr_decode_hits:
            if _detect_ocr_prompt_injection(str(c.get("data") or "")):
                qr_prompt_injection = True
                break
        try:
            qr_payload_types = {str(c.get("payload_type") or "").strip() for c in qr_decode_hits if c}
            qr_payload_types.discard("")
            qr_risk_levels = {str(c.get("risk_level") or "benign").strip().lower() for c in qr_decode_hits if c}
            qr_benign_detected = bool(qr_decode_hits) and qr_risk_levels == {"benign"}
            qr_review_required = any(level in {"review", "malicious"} for level in qr_risk_levels)
            if len(qr_payload_types) > 1:
                qr_multi_mismatch = True
        except Exception:
            qr_payload_types = set()
            qr_multi_mismatch = False
            qr_review_required = False
            qr_benign_detected = False
        # External URL indirection (common for indirect prompt injection / phishing).
        try:
            from urllib.parse import urlparse
            allow_hosts = {"127.0.0.1", "localhost"}
            for c in qr_decode_hits:
                data = str(c.get("data") or "").strip()
                if data.lower().startswith(("http://", "https://")):
                    host = (urlparse(data).hostname or "").lower()
                    if host and host not in allow_hosts:
                        qr_external_url = True
                        try:
                            qr_redirect_probe = await _probe_redirect_chain(data, timeout_s=1.25, max_hops=3)
                        except Exception:
                            qr_redirect_probe = {"enabled": True, "checked": False, "chain": [], "error": "probe_exception"}
                        break
        except Exception:
            qr_external_url = False
    except Exception:
        qr_decode_hits = []
        qr_prompt_injection = False
        qr_external_url = False
        qr_payload_types = set()
        qr_multi_mismatch = False
        qr_review_required = False
        qr_benign_detected = False
        qr_redirect_probe = {"enabled": False, "checked": False, "chain": []}

    # Fold QR findings into image-consistency UX (soft verification) so the user is prompted
    # to reupload unedited images without codes/overlays.
    try:
        if isinstance(image_consistency, dict) and isinstance(image_consistency.get("images"), list) and qr_decode_hits:
            images_out = image_consistency.get("images") or []
            qr_files = set()
            try:
                for c in qr_decode_hits:
                    fn = str(c.get("filename") or "").strip()
                    if fn:
                        qr_files.add(fn)
            except Exception:
                qr_files = set()
            tagged_any = False
            for im in images_out:
                try:
                    fn = str(im.get("filename") or "").strip()
                except Exception:
                    fn = ""
                match = False
                if qr_files and fn and fn in qr_files:
                    match = True
                if not qr_files:
                    try:
                        match = int(im.get("index", -1)) == 0
                    except Exception:
                        match = False
                if not match:
                    continue
                reasons = im.get("reasons")
                if not isinstance(reasons, list):
                    reasons = []
                if "qr_code_detected" not in reasons:
                    reasons.append("qr_code_detected")
                if qr_external_url and "qr_external_url_detected" not in reasons:
                    reasons.append("qr_external_url_detected")
                if qr_prompt_injection and "qr_prompt_injection" not in reasons:
                    reasons.append("qr_prompt_injection")
                im["reasons"] = reasons[:6]
                # Only elevate the evidence when the QR actually requires review.
                if qr_review_required and str(im.get("status") or "match") == "match":
                    im["status"] = "suspicious"
                tagged_any = True
            if not tagged_any and images_out:
                try:
                    im = images_out[0]
                    reasons = im.get("reasons")
                    if not isinstance(reasons, list):
                        reasons = []
                    if "qr_code_detected" not in reasons:
                        reasons.append("qr_code_detected")
                    if qr_external_url and "qr_external_url_detected" not in reasons:
                        reasons.append("qr_external_url_detected")
                    if qr_prompt_injection and "qr_prompt_injection" not in reasons:
                        reasons.append("qr_prompt_injection")
                    im["reasons"] = reasons[:6]
                    if qr_review_required and str(im.get("status") or "match") == "match":
                        im["status"] = "suspicious"
                except Exception:
                    pass
            # Recompute counts from per-image statuses
            mismatch_count = 0
            needs_better_count = 0
            suspicious_count = 0
            for im in images_out:
                st = str(im.get("status") or "").lower()
                if st in ("mismatch", "suspicious"):
                    mismatch_count += 1
                if st == "needs_better_image":
                    needs_better_count += 1
                if st == "suspicious":
                    suspicious_count += 1
            image_consistency["mismatch_count"] = mismatch_count
            image_consistency["needs_better_count"] = needs_better_count
            image_consistency["suspicious_count"] = suspicious_count
            image_consistency["status"] = "mismatch" if mismatch_count > 0 else ("needs_better_image" if needs_better_count > 0 else "match")
            image_consistency["soft_verify_required"] = bool(image_consistency["status"] in ("mismatch", "needs_better_image"))
            # Stronger (but still polite) user prompt when codes are present.
            if qr_external_url or qr_prompt_injection:
                image_consistency["prompt"] = (
                    "For your security, we can't accept photos that include QR codes or external links. "
                    "Please upload a new, unedited photo of the item and the damaged area (no stickers, text overlays, or QR codes)."
                )
            elif qr_benign_detected:
                image_consistency["prompt"] = (
                    "I detected a QR code in one of the photos. You can continue, but a clean photo without the QR will verify faster. "
                    "If you have proof of purchase, upload the receipt, order confirmation, or serial label with your next message."
                )
            else:
                image_consistency["prompt"] = (
                    "I detected a QR code in one of the photos. If you can, upload a cleaner photo of the item and damaged area. "
                    "You can also upload a receipt, order confirmation, or serial label to continue."
                )
    except Exception:
        pass

    # Determine tenant from request header if present
    tenant_id = None
    customer_tier = None
    try:
        if request is not None and hasattr(request, "headers"):
            tenant_id = request.headers.get("X-Tenant-Id") or request.headers.get("x-tenant-id")
            customer_tier = request.headers.get("X-User-Tier") or request.headers.get("x-user-tier")
    except Exception:
        tenant_id = None
        customer_tier = None

    order_exists = _order_exists(db, order_id)
    warranty_eligibility = _check_warranty_eligibility(db, order_id, issue_type)
    prior_mismatch_count = _count_prior_consistency_mismatches(db, order_id)
    repeat_mismatch = bool(image_consistency.get("mismatch_count", 0) > 0 and prior_mismatch_count >= 1)
    image_consistency["prior_mismatch_count"] = int(prior_mismatch_count)
    image_consistency["repeat_mismatch"] = repeat_mismatch
    image_consistency_log = _sanitize_image_consistency_for_logs(image_consistency)
    minimized_ocr_text = _minimize_ocr_text_for_logs(extracted_text)

    supplier_signals = _fetch_supplier_signals(order_id)
    # Reverse image search on first image to flag duplicates
    reverse_hits: list[Dict] = []
    try:
        if sanitized and sanitized[0].get("phash"):
            reverse_hits = ReverseImageSearch().find_similar(sanitized[0]["phash"], max_distance=8, limit=5)
    except Exception:
        reverse_hits = []

    triage = BasicCVTriage()
    triage_t0 = None
    try:
        import time as _t2
        triage_t0 = _t2.perf_counter()
    except Exception:
        triage_t0 = None
    res = triage.analyze(labels=labels, extracted_text=extracted_text)
    try:
        import inspect as _inspect
        analysis = await res if _inspect.isawaitable(res) else res
    except Exception:
        analysis = res
    triage_ms = None
    try:
        if triage_t0 is not None:
            triage_ms = int((_t2.perf_counter() - triage_t0) * 1000)
    except Exception:
        triage_ms = None
    # Prefer calibrated confidence for gating when available (add-images flow)
    try:
        conf_raw = analysis.get("confidence_calibrated") if isinstance(analysis, dict) else None
        conf_val = float(conf_raw) if conf_raw is not None else (float(analysis.get("confidence")) if analysis.get("confidence") is not None else None)
    except Exception:
        conf_val = None
    # Prefer calibrated confidence for gating when available (guest flow)
    try:
        conf_raw = analysis.get("confidence_calibrated") if isinstance(analysis, dict) else None
        conf_val = float(conf_raw) if conf_raw is not None else (float(analysis.get("confidence")) if analysis.get("confidence") is not None else None)
    except Exception:
        conf_val = None
    # Prefer calibrated confidence for gating when available
    try:
        conf_raw = analysis.get("confidence_calibrated") if isinstance(analysis, dict) else None
        conf_val = float(conf_raw) if conf_raw is not None else (float(analysis.get("confidence")) if analysis.get("confidence") is not None else None)
    except Exception:
        conf_val = None
    forensics = {}
    serial_ocr = {}
    supply_chain = {}
    try:
        if sanitized:
            from src.app.services.image_forensics import ImageForensicsService
            forensics = ImageForensicsService().analyze_image(sanitized[0].get("bytes") or b"")
    except Exception:
        forensics = {}
    try:
        if sanitized:
            from src.app.services.serial_extractor import SerialExtractor
            serial_ocr = SerialExtractor().extract_serial(sanitized[0].get("bytes") or b"")
    except Exception:
        serial_ocr = {}
    try:
        if sanitized:
            from src.app.services.supply_chain_cv import CVSupplyChainMonitor
            supply_chain = CVSupplyChainMonitor().analyze_upload(sanitized[0].get("bytes") or b"", {})
    except Exception:
        supply_chain = {}
    # Tiered CV analysis (Tier0-3) - emits trace events if trace_id provided later
    cv_tiered_analysis = {}
    try:
        if sanitized:
            from src.app.services.cv_tiered import TieredCV

            cvt = TieredCV()
            # run tiered pipeline (no trace_id yet)
            try:
                cv_tiered_analysis = await cvt.process(
                    sanitized[0].get("bytes") or b"",
                    meta={"phash": sanitized[0].get("phash"), "force_tier2": bool(force_tier2)},
                )
            except Exception:
                cv_tiered_analysis = {}
    except Exception:
        cv_tiered_analysis = {}
    # Extract tier2 summary for decision trace visibility
    tier2_summary = None
    try:
        if isinstance(cv_tiered_analysis, dict):
            tier2_summary = (
                (cv_tiered_analysis.get("tier1") or {}).get("tier2_summary")
                or (cv_tiered_analysis.get("tier2") or {}).get("tier2_summary")
                or cv_tiered_analysis.get("tier2_summary")
            )
    except Exception:
        tier2_summary = None
    # Compute trust + fraud signals for routing and escalation.
    history = {"account_age_days": 0, "loyalty_tier": None, "total_orders": 0, "email_verified": False, "phone_verified": False, "return_rate": 0.0, "fraud_flags": 0, "returns_last_30_days": 0}
    try:
        tls_fp = extract_tls_fingerprints_from_request(request) if request is not None else {}
        source_ip = str((tls_fp or {}).get("source_ip") or getattr(getattr(request, "client", None), "host", "") or "").strip()
        if source_ip:
            history["source_ip"] = source_ip
            history["ip"] = source_ip
        if request is not None and getattr(request, "headers", None):
            headers = request.headers
            device_fp = str(headers.get("x-device-fingerprint") or headers.get("x-device-id") or "").strip()
            if device_fp:
                history["device_fingerprint"] = device_fp[:128]
        ja3_hash = str((tls_fp or {}).get("ja3_hash") or "").strip()
        ja4_hash = str((tls_fp or {}).get("ja4_hash") or "").strip()
        if ja3_hash:
            history["ja3_hash"] = ja3_hash[:128]
        if ja4_hash:
            history["ja4_hash"] = ja4_hash[:128]
        known_ja3 = [h.strip() for h in str(os.getenv("FRAUD_KNOWN_JA3_HASHES", "")).split(",") if h.strip()]
        known_ja4 = [h.strip() for h in str(os.getenv("FRAUD_KNOWN_JA4_HASHES", "")).split(",") if h.strip()]
        if known_ja3:
            history["known_fraud_ja3_hashes"] = known_ja3
        if known_ja4:
            history["known_fraud_ja4_hashes"] = known_ja4
    except Exception:
        pass
    geoip_trace = _build_geoip_trace(history.get("source_ip"))
    try:
        if geoip_trace.get("asn") is not None:
            history["asn"] = geoip_trace.get("asn")
        if geoip_trace.get("country"):
            history["country"] = geoip_trace.get("country")
        history["geo_risk"] = float(geoip_trace.get("risk") or 0.0)
    except Exception:
        pass
    trust = compute_trust_score(history)
    thresholds = auto_approve_thresholds(trust)
    from src.app.services.cv_evidence import _extract_serial
    observed_serial = _extract_serial(extracted_text or "")
    forensics = {}
    serial_ocr = {}
    supply_chain = {}
    try:
        if sanitized:
            from src.app.services.image_forensics import ImageForensicsService
            forensics = ImageForensicsService().analyze_image(sanitized[0].get("bytes") or b"")
    except Exception:
        forensics = {}
    try:
        if sanitized:
            from src.app.services.serial_extractor import SerialExtractor
            serial_ocr = SerialExtractor().extract_serial(sanitized[0].get("bytes") or b"")
    except Exception:
        serial_ocr = {}
    try:
        if sanitized:
            from src.app.services.supply_chain_cv import CVSupplyChainMonitor
            supply_chain = CVSupplyChainMonitor().analyze_upload(sanitized[0].get("bytes") or b"", {})
    except Exception:
        supply_chain = {}
    signals = {
        "damage_not_visible": not bool(labels),
    }
    if reverse_hits:
        signals["duplicate_image_detected"] = True
    if forensics.get("manipulation_score", 0.0) > float(_get_support_thresholds()["manipulation_score_high_min"]):
        signals["manipulation_detected"] = True
    fraud = FraudScorer()
    # Attempt to fetch expected serial from order data if present
    try:
        from src.app.services.order_serials import get_expected_serial
        expected_serial = get_expected_serial(order_id)
    except Exception:
        expected_serial = None
    fraud_t0 = None
    try:
        import time as _t3
        fraud_t0 = _t3.perf_counter()
    except Exception:
        fraud_t0 = None
    # Create case early so downstream scoring and evidence can reference it
    case_id = create_case(order_id=order_id, issue_type=issue_type, description=scrub_pii(description), tenant_id=tenant_id)

    fraud_score, fraud_level, signals = fraud.score_with_enrichment(
        base_signals=signals,
        expected_serial=expected_serial,
        observed_serial=observed_serial,
        image_phash=(sanitized[0].get("phash") if sanitized else None),
        session_data=history,
        case_id=case_id,
    )
    fraud_ms = None
    try:
        if fraud_t0 is not None:
            fraud_ms = int((_t3.perf_counter() - fraud_t0) * 1000)
    except Exception:
        fraud_ms = None
    nlp_rules = _evaluate_nlp_rules(description)
    nlp_rules = _evaluate_nlp_rules(description)
    rule_eval = _evaluate_cv_rules(
        description=description,
        issue_type=issue_type,
        analysis=analysis or {},
        extracted_text=extracted_text or "",
        labels=labels,
        reverse_hits=reverse_hits,
        fraud_score=fraud_score,
        fraud_level=fraud_level,
        trust=trust if isinstance(trust, dict) else {},
        order_id=order_id,
        qr_codes=qr_decode_hits,
        exif_flags=exif_flags,
        file_validation=file_validation_flags,
    )
    if warranty_eligibility.get("eligible") is False:
        if not any(r.get("id") == "CV12" for r in (rule_eval.get("rules") or [])):
            rule_eval["rules"].append({"id": "CV12", "name": "warranty_lapsed", "severity": "medium", "reason": "warranty_lapsed"})
        rule_eval["signals"]["warranty_lapsed"] = True
        rule_eval["signals"]["warranty_expiry"] = warranty_eligibility.get("expires")
    if image_consistency.get("mismatch_count", 0) > 0:
        sev = "high" if repeat_mismatch else "medium"
        rid = "CV43" if repeat_mismatch else "CV42"
        name = "repeat_image_consistency_mismatch" if repeat_mismatch else "image_consistency_mismatch"
        rule_eval["rules"].append({"id": rid, "name": name, "severity": sev, "reason": "image_consistency_mismatch"})
        rule_eval["signals"]["image_consistency_mismatch"] = True
        if repeat_mismatch:
            rule_eval["signals"]["repeat_image_consistency_mismatch"] = True
    if bool(image_consistency.get("ocr_prompt_injection")) or bool(qr_prompt_injection):
        rule_eval["rules"].append({"id": "CV41", "name": "ocr_prompt_injection", "severity": "high", "reason": "encoded_prompt_injection"})
        rule_eval["signals"]["ocr_prompt_injection"] = True
    if qr_decode_hits:
        rule_eval["signals"]["qr_code_detected"] = True
        rule_eval["signals"]["qr_benign_detected"] = qr_benign_detected
    if qr_external_url:
        rule_eval["signals"]["qr_external_url_detected"] = True
    if qr_prompt_injection:
        rule_eval["signals"]["qr_prompt_injection"] = True
    if "vcard" in qr_payload_types:
        rule_eval["signals"]["qr_payload_vcard"] = True
    if "wifi_credentials" in qr_payload_types:
        rule_eval["signals"]["qr_payload_wifi"] = True
    if qr_multi_mismatch:
        rule_eval["signals"]["qr_multi_mismatch"] = True
    if _detect_qr_label_destination_mismatch(qr_decode_hits, image_consistency=image_consistency):
        rule_eval["signals"]["qr_label_destination_mismatch"] = True
    try:
        split_texts = [
            str(im.get("ocr_text") or "")
            for im in (image_consistency.get("images") or [])
            if isinstance(im, dict)
        ]
        if _detect_cross_image_split_injection(split_texts):
            rule_eval["signals"]["cross_image_split_injection"] = True
            rule_eval["signals"]["agentic_tool_abuse"] = True
            rule_eval["rules"].append(
                {
                    "id": "CV41",
                    "name": "cross_image_split_injection",
                    "severity": "high",
                    "reason": "split_prompt_across_images",
                }
            )
    except Exception:
        pass
    if order_id and order_exists is False:
        # Severity is finalized after risk quantification thresholding.
        rule_eval["signals"]["order_id_not_found"] = True
    if supplier_signals.get("supplier_verified") is False:
        rule_eval["rules"].append({"id": "CV24", "name": "supplier_unverified", "severity": "high", "reason": "supplier_unverified"})
    if supplier_signals.get("edi_status") not in (None, "ok"):
        rule_eval["rules"].append({"id": "CV23", "name": "supplier_invoice_mismatch", "severity": "high", "reason": "edi_status_failed"})

    # Security observer scan for CV/NLP evidence (includes OCR prompt injection detection)
    security_details = {}
    security_sev = None
    security_matrix: Dict[str, Any] = {}
    try:
        security_payload = {
            "description": description,
            "issue_type": issue_type,
            "ocr_text": extracted_text,
            "labels": labels,
            "reverse_hits": reverse_hits,
            "image_consistency": image_consistency,
            "order_exists": order_exists,
            "qr_codes": qr_decode_hits,
            "qr_payload_types": sorted(list(qr_payload_types)),
            "qr_redirect_probe": qr_redirect_probe,
            "supplier_signals": supplier_signals,
            "exif_flags": exif_flags,
            "file_validation": file_validation_flags,
            "cv_rules": rule_eval.get("rules"),
            # Merge CV rule signals with fraud/forensics signals so the observer can map them
            # into MITRE/OWASP and raise severity when appropriate.
            "cv_signals": {**(rule_eval.get("signals") or {}), **(signals or {})},
            "geoip_trace": geoip_trace,
        }
        security_analysis = analyze_payload(security_payload)
        security_details = security_analysis.get("details") or {}
        security_sev = security_analysis.get("severity")
        security_matrix = _build_complaint_security_matrix(
            security_details=security_details,
            security_severity=security_sev,
            rule_eval=rule_eval,
            nlp_rules=nlp_rules,
            image_consistency=image_consistency,
            qr_payload_types=qr_payload_types,
            recommended_route=None,
        )
        try:
            emit_security_event("/api/v1/support/complaints/submit", {"payload": security_payload, "analysis": security_details}, request=request)
        except Exception:
            pass
        try:
            log_trace_event(
                trace_id=case_id,
                event_type="security_scan",
                source_type="agent",
                source_id="Security_Observer_Agent",
                target_type="system",
                target_id=None,
                payload={
                    "details": security_details,
                    "severity": security_sev,
                    "security_matrix": security_matrix,
                    "maestro": security_matrix.get("maestro") if isinstance(security_matrix, dict) else [],
                },
            )
        except Exception:
            pass
    except Exception:
        security_details = {}
        security_sev = None
        security_matrix = {}

    # Policy gate decision (CV flow)
    gate_force_review = False
    try:
        risk_score = float(security_details.get("risk_adj") or 0.0)
        if risk_score > 1.0 and risk_score <= 100.0:
            risk_score = risk_score / 100.0
        gate = evaluate_policy_gate(
            {
                "tool": "support.complaints.submit",
                "params": {"order_id": order_id, "issue_type": issue_type},
                "risk_score": risk_score,
                "policy_version": "v1",
                "request_type": "cv",
                "signals": security_details.get("signals") or {},
                "severity": security_sev or "info",
                "pii_types": (security_details.get("evidence") or {}).get("pii_types") or [],
                "ai_assisted": True,
                "buyer_type": None,
                "compliance_provided": None,
            }
        )
        log_trace_event(
            trace_id=case_id,
            event_type="policy_gate",
            source_type="agent",
            source_id="CV_Policy_Gate_Agent",
            target_type="system",
            target_id=None,
            payload={
                "decision": gate.decision,
                "reasons": gate.reasons,
                "rule_hits": gate.rule_hits,
                "policy_version": gate.policy_version,
                "compliance_tags": gate.compliance_tags,
                "action": gate.action,
            },
        )
        if gate.decision in ("review", "deny"):
            gate_force_review = True
    except Exception:
        pass

    recommended_route = "standard_queue"
    support_thr = _get_support_thresholds()
    auto_conf = float(support_thr.get("auto_process_confidence_min_signed_in", 0.8))
    allowed_fraud = tuple(support_thr.get("auto_process_fraud_levels", ["minimal", "low"]) or ["minimal", "low"])
    if (conf_val or 0.0) > auto_conf and analysis.get("severity") in ("minor",) and thresholds.get("max_amount_usd", 0.0) >= 50.0 and fraud_level in allowed_fraud:
        recommended_route = "auto_process"
    elif fraud_level == "high":
        recommended_route = "fraud_review_team"
    elif fraud_level == "medium":
        recommended_route = "supervisor_review"
    if any(r.get("severity") == "high" for r in (rule_eval.get("rules") or [])):
        recommended_route = "security_review"
    if any(r.get("severity") == "high" for r in (nlp_rules.get("rules") or [])):
        recommended_route = "security_review"
    if gate_force_review:
        recommended_route = "security_review"
    if bool(geoip_trace.get("force_security_review")):
        recommended_route = "security_review"
    risk_quant = {}
    try:
        risk_quant = quantify_risk(
            security=None,
            cv_analysis=analysis or {},
            fraud={"score": fraud_score, "level": fraud_level},
            policy_gates=None,
            monetary_exposure=None,
            history_score=trust.get("score") if isinstance(trust, dict) else None,
        )
        # Enrich with tiered CV exposure estimate when available
        try:
            from src.app.services.risk import quantify_exposure

            price = None
            if supplier_signals and isinstance(supplier_signals, dict):
                price = supplier_signals.get("price_cents")
            if not price and isinstance(risk_quant.get("inputs", {}).get("monetary_exposure"), (int, float)):
                price = risk_quant.get("inputs", {}).get("monetary_exposure")
            # fallback: try fetched order total
            if not price and evidence.get("order"):
                price = evidence.get("order").get("total_cents")
            likelihood_est = max((fraud_score or 0) / 100.0, float(conf_val or 0.0) * 0.8)
            exposure = quantify_exposure(price_cents=price or 0.0, likelihood=likelihood_est, dread_modifier=0.0, stride_modifier=0.0, control_maturity=(trust.get("score") if isinstance(trust, dict) else 0.0))
            risk_quant["exposure"] = exposure
            try:
                log_trace_event(
                    trace_id=decision_id if 'decision_id' in locals() else None,
                    event_type="risk_summary",
                    source_type="agent",
                    source_id="RiskEngine",
                    target_type="system",
                    target_id=None,
                    payload={"exposure_cents": exposure.get("exposure_cents"), "risk_band": exposure.get("risk_band"), "components": exposure.get("components")},
                )
            except Exception:
                pass
        except Exception:
            pass
    except Exception:
        risk_quant = {}

    # Post-risk routing adjustments:
    # 1) Soft verification for first mismatch/low-evidence uploads.
    # 2) Escalation on repeated mismatch and high-risk missing order IDs.
    order_validation = {
        "provided": bool(order_id),
        "exists": bool(order_exists) if order_exists is not None else None,
        "security_threshold": None,
        "risk_score": float(risk_quant.get("risk_score") or 0.0) if isinstance(risk_quant, dict) else 0.0,
        "triggered_security": False,
    }
    try:
        order_security_threshold = float(os.getenv("ORDER_VALIDATION_SECURITY_RISK_THRESHOLD", "4.0") or 4.0)
    except Exception:
        order_security_threshold = 4.0
    order_validation["security_threshold"] = order_security_threshold

    if bool(image_consistency.get("soft_verify_required")) and recommended_route != "security_review":
        recommended_route = "soft_verify"
    if repeat_mismatch:
        recommended_route = "security_review"
    if qr_prompt_injection:
        recommended_route = "security_review"
    if order_id and order_exists is False and float(order_validation.get("risk_score") or 0.0) >= float(order_security_threshold):
        recommended_route = "security_review"
        order_validation["triggered_security"] = True
        if not any(r.get("id") == "CV44" for r in (rule_eval.get("rules") or [])):
            rule_eval["rules"].append(
                {"id": "CV44", "name": "order_id_not_found", "severity": "high", "reason": "order_not_found_risk_threshold"}
            )
        rule_eval["signals"]["order_id_not_found"] = True
    if bool(geoip_trace.get("force_security_review")):
        recommended_route = "security_review"
        rule_eval["signals"]["high_risk_region"] = True

    security_matrix = _build_complaint_security_matrix(
        security_details=security_details,
        security_severity=security_sev,
        rule_eval=rule_eval,
        nlp_rules=nlp_rules,
        image_consistency=image_consistency,
        qr_payload_types=qr_payload_types,
        recommended_route=recommended_route,
    )

    # Trust routing override based on trust tier + risk band + exposure.
    # Security and soft-verify routes are sticky and cannot be downgraded by trust.
    try:
        trust_dec = route_from_trust(
            trust_score=trust.get("score") if isinstance(trust, dict) else float(trust),
            risk_band=risk_quant.get("risk_band"),
            amount_usd=(risk_quant.get("exposure", {}) or {}).get("exposure_cents", 0) / 100.0 if isinstance(risk_quant, dict) else None,
        )
        route_lock = recommended_route in ("security_review", "soft_verify")
        if trust_dec.route and (not route_lock or trust_dec.route == "security_review"):
            recommended_route = trust_dec.route
        try:
            log_trace_event(
                trace_id=case_id,
                event_type="trust_routing",
                source_type="agent",
                source_id="Trust_Routing_Agent",
                target_type="system",
                target_id=None,
                payload={
                    "trust_score": trust_dec.trust_score,
                    "tier": trust_dec.tier,
                    "route": trust_dec.route,
                    "reasons": trust_dec.reasons,
                },
            )
        except Exception:
            pass
    except Exception:
        pass

    needs_human = False
    try:
        if analysis.get("needs_human_review", False):
            needs_human = True
        if conf_val is not None and float(conf_val) < float(_get_support_thresholds()["cv_confidence_low_min"]):
            needs_human = True
        if analysis.get("severity") in ("major", "high", "critical"):
            needs_human = True
        if fraud_level in ("high",):
            needs_human = True
        if risk_quant.get("risk_band") == "high":
            needs_human = True
        if gate_force_review:
            needs_human = True
        if recommended_route == "security_review" and (
            bool(order_validation.get("triggered_security"))
            or repeat_mismatch
            or risk_quant.get("risk_band") == "high"
        ):
            needs_human = True
        # First-pass mismatch should remain autonomous: ask user to verify/re-upload,
        # then escalate on repeat mismatch.
        if recommended_route == "soft_verify" and not repeat_mismatch and not gate_force_review:
            needs_human = False
    except Exception:
        pass

    # Create case and persist preliminary decision
    # case_id already created above

    agent_chain = [
        {"agent": "Image_Intake_Agent", "confidence": 1.0, "duration_ms": sanitize_ms},
        {"agent": "CV_Label_Agent", "confidence": analysis.get("confidence"), "duration_ms": cv_dt_ms},
        {"agent": "Fraud_Scoring_Agent", "confidence": fraud_score, "duration_ms": fraud_ms},
        {"agent": "Routing_Agent", "confidence": None, "duration_ms": triage_ms},
    ]

    evidence_bundle = build_evidence_bundle(
        case_id=case_id,
        sanitized_images=sanitized,
        labels=labels,
        extracted_text=minimized_ocr_text,
        analysis=analysis or {},
        reverse_hits=reverse_hits,
        forensics=forensics,
        ocr=serial_ocr,
        supply_chain=supply_chain,
        provider="ollama" if labels or extracted_text else "none",
        model=os.getenv("CV_MODEL", "llava"),
        processing_time_ms=cv_dt_ms,
        sanitize_time_ms=sanitize_ms,
        fraud={"score": fraud_score, "level": fraud_level, "signals": signals},
        trust=trust if isinstance(trust, dict) else {},
        issue_type=issue_type,
        description=description,
    )
    evidence_tags = _build_evidence_tags(
        rule_signals=rule_eval.get("signals") or {},
        forensics=forensics or {},
        fraud_level=fraud_level,
        supplier_signals=supplier_signals or {},
        tier2=cv_tiered_analysis if isinstance(cv_tiered_analysis, dict) else {},
        expected_serial=expected_serial,
        observed_serial=observed_serial,
    )
    playbook_preview = select_cv_playbook(evidence_tags, risk_quant.get("risk_band"))
    override_playbook = get_cv_playbook_by_id(playbook_override)
    if override_playbook:
        playbook_preview = {
            "playbook": override_playbook,
            "triggered_by": ["manual_override"],
            "risk_band": risk_quant.get("risk_band"),
            "override": True,
        }
    # attach cv_tiered_analysis into evidence bundle for visibility
    try:
        if cv_tiered_analysis:
            evidence_bundle["cv_tiered_analysis"] = cv_tiered_analysis
    except Exception:
        pass
    evidence_bundle["image_consistency"] = image_consistency
    evidence_bundle["order_validation"] = order_validation
    evidence_bundle["qr_codes"] = qr_decode_hits[:10]
    evidence_bundle["supplier_signals"] = supplier_signals
    evidence_bundle["nlp_rules"] = nlp_rules.get("rules")
    evidence_bundle["evidence_tags"] = evidence_tags
    evidence_bundle["retention_policy"] = _retention_windows()
    if playbook_preview:
        evidence_bundle["playbook_preview"] = playbook_preview
    evidence_id = None

    # Persist preliminary decision log (propose-only)
    decision_id = log_decision(
        agent_name="cv_triage_agent",
        input_data={"case_id": case_id, "order_id": order_id, "issue_type": issue_type, "description": scrub_pii(description)},
        retrieved_context={
            "labels": labels,
            "images": [{"sha256": s.get("sha256"), "phash": s.get("phash")} for s in sanitized],
            "trust_score": trust,
            "fraud": {"score": fraud_score, "level": fraud_level},
            "fraud_signals": signals,
            "reverse_image_hits": reverse_hits,
            "image_consistency": image_consistency_log,
            "order_validation": order_validation,
            "qr_codes": qr_decode_hits[:10],
            "supplier_signals": supplier_signals,
            "geoip_trace": geoip_trace,
            "agent_chain": agent_chain,
            "risk_quantification": risk_quant,
            "customer_tier": customer_tier,
            "evidence_bundle": evidence_bundle,
            "cv_rules": rule_eval.get("rules"),
            "nlp_rules": nlp_rules.get("rules"),
            "security_analysis": {
                "severity": security_sev,
                "risk_adj": security_details.get("risk_adj") if isinstance(security_details, dict) else None,
                "signals": (security_details.get("signals") if isinstance(security_details, dict) else None),
            },
            "security_matrix": security_matrix,
        },
        proposed_action={
            "analysis": analysis,
            "suggested_routing": recommended_route,
            "image_consistency": image_consistency,
            "order_validation": order_validation,
            "geoip_trace": geoip_trace,
            "user_prompt": image_consistency.get("prompt"),
            "ui_actions": {"chat_with_admin": bool(recommended_route == "security_review")},
            "security_matrix": security_matrix,
        },
        agent_reasoning=f"rule_based_labels={labels}",
        policy_version="v1",
        approval_required=needs_human,
        execution_status="queued",
    )
    try:
        log_trace_event(
            trace_id=decision_id,
            event_type="security_scan",
            source_type="agent",
            source_id="Security_Observer_Agent",
            target_type="system",
            target_id=None,
            payload={
                "details": security_details,
                "severity": security_sev,
                "security_matrix": security_matrix,
                "maestro": security_matrix.get("maestro") if isinstance(security_matrix, dict) else [],
                "policy_action": security_matrix.get("policy_action") if isinstance(security_matrix, dict) else None,
            },
        )
    except Exception:
        pass
    try:
        log_trace_event(
            trace_id=decision_id,
            event_type="evidence_bundle",
            source_type="agent",
            source_id="CV_Evidence_Agent",
            target_type="system",
            target_id=None,
            payload={"case_id": case_id, "bundle": evidence_bundle},
        )
    except Exception:
        pass
    try:
        evidence_id = persist_evidence_bundle(case_id, evidence_bundle)
        if evidence_id is None:
            evidence_id = f"evidence-{case_id}"
        log_trace_event(
            trace_id=decision_id,
            event_type="evidence_persisted",
            source_type="agent",
            source_id="Evidence_Store",
            target_type="system",
            target_id=None,
            payload={"case_id": case_id, "evidence_id": evidence_id},
        )
    except Exception:
        pass
    try:
        log_trace_event(
            trace_id=decision_id,
            event_type="policy_gate",
            source_type="agent",
            source_id="CV_Rule_Agent",
            target_type="system",
            target_id=None,
            payload={"rules": rule_eval.get("rules"), "signals": rule_eval.get("signals")},
        )
    except Exception:
        pass
    try:
        log_trace_event(
            trace_id=decision_id,
            event_type="cv_pipeline",
            source_type="agent",
            source_id="CV_Triage_Agent",
            target_type="agent",
            target_id="Complaint_Case",
            payload={
                "labels": labels,
                "confidence": analysis.get("confidence"),
                "severity": analysis.get("severity"),
                "tier2_summary": tier2_summary,
            },
        )
    except Exception:
        pass
    try:
        log_trace_event(
            trace_id=decision_id,
            event_type="image_consistency_check",
            source_type="agent",
            source_id="CV_Consistency_Agent",
            target_type="system",
            target_id=None,
            payload={
                "status": image_consistency.get("status"),
                "mismatch_count": image_consistency.get("mismatch_count"),
                "repeat_mismatch": image_consistency.get("repeat_mismatch"),
                "images": image_consistency.get("images"),
            },
        )
    except Exception:
        pass
    try:
        if image_consistency.get("soft_verify_required"):
            log_trace_event(
                trace_id=decision_id,
                event_type="soft_user_prompted",
                source_type="agent",
                source_id="CV_Consistency_Agent",
                target_type="user",
                target_id=None,
                payload={
                    "prompt": image_consistency.get("prompt"),
                    "status": image_consistency.get("status"),
                    "mismatch_count": image_consistency.get("mismatch_count"),
                },
            )
    except Exception:
        pass
    try:
        if repeat_mismatch:
            log_trace_event(
                trace_id=decision_id,
                event_type="repeat_mismatch_escalated",
                source_type="agent",
                source_id="CV_Consistency_Agent",
                target_type="security",
                target_id=None,
                payload={"order_id": order_id, "prior_mismatch_count": prior_mismatch_count},
            )
    except Exception:
        pass
    try:
        if order_id and order_exists is False:
            log_trace_event(
                trace_id=decision_id,
                event_type="order_validation_failed",
                source_type="agent",
                source_id="Order_Validation_Agent",
                target_type="security" if order_validation.get("triggered_security") else "system",
                target_id=None,
                payload=order_validation,
            )
    except Exception:
        pass
    try:
        if recommended_route == "security_review":
            log_trace_event(
                trace_id=decision_id,
                event_type="security_review_started",
                source_type="agent",
                source_id="Routing_Agent",
                target_type="security",
                target_id=None,
                payload={"reason": "cv_risk_threshold", "order_validation": order_validation},
            )
    except Exception:
        pass

    # Persist CV analysis evidence history (first image)
    try:
        if sanitized:
            from src.app.services.cv_evidence import persist_cv_analysis
            persist_cv_analysis(
                case_id=case_id,
                image_sha256=sanitized[0].get("sha256"),
                image_phash=sanitized[0].get("phash"),
                analysis=analysis,
                labels=labels,
                extracted_text=minimized_ocr_text,
                provider="ollama" if labels or extracted_text else "none",
                model=os.getenv("CV_MODEL", "llava"),
                processing_time_ms=cv_dt_ms,
            )
    except Exception:
        pass

    ticket_id = None
    if needs_human:
        try:
            signals = {"cv_fraud_high": fraud_level in ("high",), "cv_rules_high": any(r.get("severity") == "high" for r in (rule_eval.get("rules") or []))}
            playbook = select_playbook(signals, severity="high" if risk_quant.get("risk_band") == "high" else "medium")
            evidence_snapshot = build_evidence_snapshot({
                "security": {"signals": signals, "rules": rule_eval.get("rules")},
                "risk_quantification": risk_quant,
                "trace_id": decision_id,
            })
            t = TicketingAgent().create_ticket(
                title="CV complaint review",
                description=f"Case {case_id} requires review",
                severity="high" if risk_quant.get("risk_band") == "high" else "medium",
                tenant_id=tenant_id,
                reason_code="cv_risk_threshold",
                trace_id=decision_id,
                policy_version="v1",
                cv_summary={
                    "severity": analysis.get("severity"),
                    "confidence": analysis.get("confidence"),
                    "fraud_level": fraud_level,
                },
                customer_tier=customer_tier,
                playbook=playbook,
                evidence_snapshot=evidence_snapshot,
            )
            ticket_id = t.id
        except Exception:
            pass
    # If a ticket was created, include human actor in agent_chain for traceability
    try:
        if ticket_id:
            agent_chain.append({"agent": "Human_Reviewer", "actor_type": "human", "ticket_id": ticket_id, "duration_ms": None})
            try:
                log_trace_event(
                    trace_id=decision_id,
                    event_type="human_escalation",
                    source_type="agent",
                    source_id="TicketingAgent",
                    target_type="human",
                    target_id="Support",
                    payload={"ticket_id": ticket_id, "reason": "cv_risk_threshold", "severity": analysis.get("severity")},
                )
            except Exception:
                pass
            try:
                log_trace_event(
                    trace_id=decision_id,
                    event_type="human_override_requested",
                    source_type="agent",
                    source_id="TicketingAgent",
                    target_type="human",
                    target_id="Support",
                    payload={"ticket_id": ticket_id, "route": recommended_route},
                )
            except Exception:
                pass
    except Exception:
        pass

    return {
        "status": "submitted",
        "case_id": case_id,
        "decision_id": decision_id,
        "analysis": analysis,
        "cv_analysis": analysis,
        "cv_tiered_analysis": cv_tiered_analysis,
        "decision": recommended_route,
        "verdict": recommended_route,
        "disclaimer": analysis.get("ai_disclaimer"),
        "trust_score": trust,
        "fraud": {"score": fraud_score, "level": fraud_level},
        "evidence_tags": evidence_tags,
        "playbook_preview": playbook_preview,
        "suggested_routing": recommended_route,
        "geoip_trace": geoip_trace,
        "image_consistency": image_consistency,
        "order_validation": order_validation,
        "warranty_eligibility": warranty_eligibility,
        "ocr_normalized": rule_eval.get("ocr_normalized"),
        "file_validation": file_validation_flags,
        "exif_flags": exif_flags,
        "qr_payload_types": sorted(list(qr_payload_types)),
        "qr_redirect_probe": qr_redirect_probe,
        "user_prompt": image_consistency.get("prompt"),
        "ui_actions": {"chat_with_admin": bool(recommended_route == "security_review" or needs_human)},
        "agent_chain": agent_chain,
        "security_matrix": security_matrix,
        "risk_quantification": risk_quant,
        "human_review": {"status": "pending" if needs_human else "not_required", "ticket_id": ticket_id},
        "ticket_id": ticket_id,
        "evidence_id": evidence_id,
    }


@router.post("/submit-guest")
async def submit_complaint_guest(
    receipt_image: UploadFile = File(...),
    issue_type: str = "",
    description: str = "",
    playbook_override: Optional[str] = Form(None),
    damage_images: list[UploadFile] = File(default=[]),
    db=Depends(get_db),
    request: Request = None,
) -> Dict:
    """Guest submission using receipt OCR and optional damage photos."""
    from src.app.services.image_intake import sanitize_image
    from src.app.services.cv_triage_basic import BasicCVTriage
    from src.app.services.cv_provider import ManagedCVProvider

    # Sanitize receipt and damage images
    sanitize_t0 = None
    try:
        import time as _t
        sanitize_t0 = _t.perf_counter()
    except Exception:
        sanitize_t0 = None
    rec_bytes = await receipt_image.read()
    rec_gate = strict_image_ingest_gate(
        filename=_safe_filename(getattr(receipt_image, "filename", None), 0),
        content_type=getattr(receipt_image, "content_type", None),
        blob=rec_bytes,
        size_bytes=len(rec_bytes),
    )
    if bool(rec_gate.get("blocked")):
        raise HTTPException(
            status_code=400,
            detail={
                "error": "ingest_gate_blocked",
                "message": "Receipt image failed strict ingest checks.",
                "blocked_uploads": [
                    {
                        "index": 0,
                        "filename": _safe_filename(getattr(receipt_image, "filename", None), 0),
                        "reasons": list(rec_gate.get("block_reasons") or []),
                        "ingest_gate": rec_gate.get("ingest_gate"),
                    }
                ],
            },
        )
    rec = sanitize_image(rec_bytes)
    dmg_sanitized = []
    blocked_uploads: List[Dict[str, Any]] = []
    for idx, img in enumerate(damage_images or []):
        raw = await img.read()
        gate = strict_image_ingest_gate(
            filename=_safe_filename(getattr(img, "filename", None), idx),
            content_type=getattr(img, "content_type", None),
            blob=raw,
            size_bytes=len(raw),
        )
        if bool(gate.get("blocked")):
            blocked_uploads.append(
                {
                    "index": idx,
                    "filename": _safe_filename(getattr(img, "filename", None), idx),
                    "reasons": list(gate.get("block_reasons") or []),
                    "ingest_gate": gate.get("ingest_gate"),
                }
            )
            continue
        dmg_sanitized.append(sanitize_image(raw))
    if blocked_uploads:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "ingest_gate_blocked",
                "message": "One or more damage images failed strict ingest checks.",
                "blocked_uploads": blocked_uploads[:8],
            },
        )
    sanitize_ms = None
    try:
        if sanitize_t0 is not None:
            sanitize_ms = int((_t.perf_counter() - sanitize_t0) * 1000)
    except Exception:
        sanitize_ms = None

    # Receipt OCR via managed provider if enabled
    labels: list[str] = []
    extracted_text = ""
    try:
        if rec.get("bytes"):
            _labels_rec, extracted_text, *_ = await ManagedCVProvider().get_labels_and_text(rec["bytes"])
    except Exception:
        pass
    # Damage image labels (first)
    try:
        if dmg_sanitized:
            labels, _, *_extra = await ManagedCVProvider().get_labels_and_text(dmg_sanitized[0].get("bytes") or b"")
    except Exception:
        pass
    # Tiered CV analysis (Tier0-3) on first damage image (best-effort)
    cv_tiered_analysis = {}
    try:
        if dmg_sanitized:
            from src.app.services.cv_tiered import TieredCV

            cvt = TieredCV()
            try:
                cv_tiered_analysis = await cvt.process(
                    dmg_sanitized[0].get("bytes") or b"",
                    meta={"phash": dmg_sanitized[0].get("phash")},
                )
            except Exception:
                cv_tiered_analysis = {}
    except Exception:
        cv_tiered_analysis = {}
    # Reverse image search on damage image
    reverse_hits: list[Dict] = []
    try:
        if dmg_sanitized and dmg_sanitized[0].get("phash"):
            reverse_hits = ReverseImageSearch().find_similar(dmg_sanitized[0]["phash"], max_distance=8, limit=5)
    except Exception:
        reverse_hits = []
    triage = BasicCVTriage()
    triage_t0 = None
    try:
        import time as _t2
        triage_t0 = _t2.perf_counter()
    except Exception:
        triage_t0 = None
    res = triage.analyze(labels=labels, extracted_text=extracted_text)
    try:
        import inspect as _inspect
        analysis = await res if _inspect.isawaitable(res) else res
    except Exception:
        analysis = res
    triage_ms = None
    try:
        if triage_t0 is not None:
            triage_ms = int((_t2.perf_counter() - triage_t0) * 1000)
    except Exception:
        triage_ms = None
    history = {"account_age_days": 0, "loyalty_tier": None, "total_orders": 0, "email_verified": False, "phone_verified": False, "return_rate": 0.0, "fraud_flags": 0, "returns_last_30_days": 0}
    try:
        tls_fp = extract_tls_fingerprints_from_request(request) if request is not None else {}
        source_ip = str((tls_fp or {}).get("source_ip") or getattr(getattr(request, "client", None), "host", "") or "").strip()
        if source_ip:
            history["source_ip"] = source_ip
            history["ip"] = source_ip
        if request is not None and getattr(request, "headers", None):
            headers = request.headers
            device_fp = str(headers.get("x-device-fingerprint") or headers.get("x-device-id") or "").strip()
            if device_fp:
                history["device_fingerprint"] = device_fp[:128]
        ja3_hash = str((tls_fp or {}).get("ja3_hash") or "").strip()
        ja4_hash = str((tls_fp or {}).get("ja4_hash") or "").strip()
        if ja3_hash:
            history["ja3_hash"] = ja3_hash[:128]
        if ja4_hash:
            history["ja4_hash"] = ja4_hash[:128]
        known_ja3 = [h.strip() for h in str(os.getenv("FRAUD_KNOWN_JA3_HASHES", "")).split(",") if h.strip()]
        known_ja4 = [h.strip() for h in str(os.getenv("FRAUD_KNOWN_JA4_HASHES", "")).split(",") if h.strip()]
        if known_ja3:
            history["known_fraud_ja3_hashes"] = known_ja3
        if known_ja4:
            history["known_fraud_ja4_hashes"] = known_ja4
    except Exception:
        pass
    trust = compute_trust_score(history)
    thresholds = auto_approve_thresholds(trust)
    from src.app.services.cv_evidence import _extract_serial
    observed_serial = _extract_serial(extracted_text or "")
    forensics = {}
    serial_ocr = {}
    supply_chain = {}
    try:
        if dmg_sanitized:
            from src.app.services.image_forensics import ImageForensicsService
            forensics = ImageForensicsService().analyze_image(dmg_sanitized[0].get("bytes") or b"")
    except Exception:
        forensics = {}
    try:
        if dmg_sanitized:
            from src.app.services.serial_extractor import SerialExtractor
            serial_ocr = SerialExtractor().extract_serial(dmg_sanitized[0].get("bytes") or b"")
    except Exception:
        serial_ocr = {}
    try:
        if dmg_sanitized:
            from src.app.services.supply_chain_cv import CVSupplyChainMonitor
            supply_chain = CVSupplyChainMonitor().analyze_upload(dmg_sanitized[0].get("bytes") or b"", {})
    except Exception:
        supply_chain = {}
    signals = {
        "damage_not_visible": not bool(labels),
    }
    if reverse_hits:
        signals["duplicate_image_detected"] = True
    if forensics.get("manipulation_score", 0.0) > float(_get_support_thresholds()["manipulation_score_high_min"]):
        signals["manipulation_detected"] = True
    fraud = FraudScorer()
    fraud_t0 = None
    try:
        import time as _t3
        fraud_t0 = _t3.perf_counter()
    except Exception:
        fraud_t0 = None
    # Create case early (guest flow) to allow scoring/evidence linkage
    tenant_id = None
    try:
        if request is not None and hasattr(request, "headers"):
            tenant_id = request.headers.get("X-Tenant-Id") or request.headers.get("x-tenant-id")
    except Exception:
        tenant_id = None
    case_id = create_case(order_id=None, issue_type=issue_type, description=scrub_pii(description), customer_id=None, guest_email=None, tenant_id=tenant_id)

    fraud_score, fraud_level, signals = fraud.score_with_enrichment(
        base_signals=signals,
        expected_serial=None,
        observed_serial=observed_serial,
        image_phash=(dmg_sanitized[0].get("phash") if dmg_sanitized else None),
        session_data=history,
        case_id=case_id,
    )
    fraud_ms = None
    try:
        if fraud_t0 is not None:
            fraud_ms = int((_t3.perf_counter() - fraud_t0) * 1000)
    except Exception:
        fraud_ms = None
    rule_eval = _evaluate_cv_rules(
        description=description,
        issue_type=issue_type,
        analysis=analysis or {},
        extracted_text=extracted_text or "",
        labels=labels,
        reverse_hits=reverse_hits,
        fraud_score=fraud_score,
        fraud_level=fraud_level,
        trust=trust if isinstance(trust, dict) else {},
        order_id=None,
    )

    # Security observer scan for CV/NLP evidence (guest flow)
    security_details = {}
    security_sev = None
    gate_force_review = False
    try:
        security_payload = {
            "description": description,
            "issue_type": issue_type,
            "ocr_text": extracted_text,
            "labels": labels,
            "reverse_hits": reverse_hits,
            "cv_rules": rule_eval.get("rules"),
            "cv_signals": rule_eval.get("signals"),
            "geoip_trace": geoip_trace,
        }
        security_analysis = analyze_payload(security_payload)
        security_details = security_analysis.get("details") or {}
        security_sev = security_analysis.get("severity")
        try:
            emit_security_event("/api/v1/support/complaints/submit-guest", {"payload": security_payload, "analysis": security_details}, request=request)
        except Exception:
            pass
    except Exception:
        security_details = {}
        security_sev = None
    try:
        log_trace_event(
            trace_id=case_id,
            event_type="security_scan",
            source_type="agent",
            source_id="Security_Observer_Agent",
            target_type="system",
            target_id=None,
            payload={"details": security_details, "severity": security_sev},
        )
    except Exception:
        pass
    try:
        if playbook_preview:
            log_trace_event(
                trace_id=case_id,
                event_type="cv_playbook",
                source_type="agent",
                source_id="CV_Playbook_Agent",
                target_type="system",
                target_id=playbook_preview.get("playbook", {}).get("id"),
                payload={"evidence_tags": evidence_tags, "playbook": playbook_preview},
            )
    except Exception:
        pass
        risk_score = float(security_details.get("risk_adj") or 0.0)
        if risk_score > 1.0 and risk_score <= 100.0:
            risk_score = risk_score / 100.0
        gate = evaluate_policy_gate(
            {
                "tool": "support.complaints.submit-guest",
                "params": {"issue_type": issue_type},
                "risk_score": risk_score,
                "policy_version": "v1",
                "request_type": "cv",
                "signals": security_details.get("signals") or {},
                "severity": security_sev or "info",
                "pii_types": (security_details.get("evidence") or {}).get("pii_types") or [],
                "ai_assisted": True,
                "buyer_type": None,
                "compliance_provided": None,
            }
        )
        log_trace_event(
            trace_id=case_id,
            event_type="policy_gate",
            source_type="agent",
            source_id="CV_Policy_Gate_Agent",
            target_type="system",
            target_id=None,
            payload={
                "decision": gate.decision,
                "reasons": gate.reasons,
                "rule_hits": gate.rule_hits,
                "policy_version": gate.policy_version,
                "compliance_tags": gate.compliance_tags,
                "action": gate.action,
            },
        )
        if gate.decision in ("review", "deny"):
            gate_force_review = True
    except Exception:
        security_details = {}
        security_sev = None

    geoip_trace = _build_geoip_trace(history.get("source_ip"))
    try:
        if geoip_trace.get("asn") is not None:
            history["asn"] = geoip_trace.get("asn")
        if geoip_trace.get("country"):
            history["country"] = geoip_trace.get("country")
        history["geo_risk"] = float(geoip_trace.get("risk") or 0.0)
    except Exception:
        pass

    recommended_route = "standard_queue"
    # Evaluate NLP compliance rules for guest flow (ensure variable defined)
    nlp_rules = _evaluate_nlp_rules(description)
    support_thr = _get_support_thresholds()
    auto_conf = float(support_thr.get("auto_process_confidence_min_guest", 0.85))
    allowed_fraud = tuple(support_thr.get("auto_process_fraud_levels", ["minimal", "low"]) or ["minimal", "low"])
    try:
        conf_raw = analysis.get("confidence") if isinstance(analysis, dict) else None
        conf_val = float(conf_raw) if conf_raw is not None else None
    except Exception:
        conf_val = None
    if (conf_val or 0.0) > auto_conf and analysis.get("severity") in ("minor",) and thresholds.get("max_amount_usd", 0.0) >= 50.0 and fraud_level in allowed_fraud:
        recommended_route = "auto_process"
    if any(r.get("severity") == "high" for r in (nlp_rules.get("rules") or [])):
        recommended_route = "security_review"
    if any(r.get("severity") == "high" for r in (rule_eval.get("rules") or [])):
        recommended_route = "security_review"
    if gate_force_review:
        recommended_route = "security_review"
    if bool(geoip_trace.get("force_security_review")):
        recommended_route = "security_review"
    try:
        trust_dec = route_from_trust(
            trust_score=trust.get("score") if isinstance(trust, dict) else float(trust),
            risk_band=risk_quant.get("risk_band"),
            amount_usd=(risk_quant.get("exposure", {}) or {}).get("exposure_cents", 0) / 100.0 if isinstance(risk_quant, dict) else None,
        )
        recommended_route = trust_dec.route if trust_dec.route else recommended_route
        try:
            log_trace_event(
                trace_id=case_id,
                event_type="trust_routing",
                source_type="agent",
                source_id="Trust_Routing_Agent",
                target_type="system",
                target_id=None,
                payload={
                    "trust_score": trust_dec.trust_score,
                    "tier": trust_dec.tier,
                    "route": trust_dec.route,
                    "reasons": trust_dec.reasons,
                },
            )
        except Exception:
            pass
    except Exception:
        pass

    # Determine tenant from request header if present
    tenant_id = None
    customer_tier = None
    try:
        if request is not None and hasattr(request, "headers"):
            tenant_id = request.headers.get("X-Tenant-Id") or request.headers.get("x-tenant-id")
            customer_tier = request.headers.get("X-User-Tier") or request.headers.get("x-user-tier")
    except Exception:
        tenant_id = None
        customer_tier = None

    # case_id already created above

    agent_chain = [
        {"agent": "Image_Intake_Agent", "confidence": 1.0, "duration_ms": sanitize_ms},
        {"agent": "CV_Label_Agent", "confidence": analysis.get("confidence"), "duration_ms": None},
        {"agent": "Fraud_Scoring_Agent", "confidence": fraud_score, "duration_ms": fraud_ms},
        {"agent": "Routing_Agent", "confidence": None, "duration_ms": triage_ms},
    ]

    risk_quant = {}
    try:
        risk_quant = quantify_risk(
            security=None,
            cv_analysis=analysis or {},
            fraud={"score": fraud_score, "level": fraud_level},
            policy_gates=None,
            monetary_exposure=None,
            history_score=trust.get("score") if isinstance(trust, dict) else None,
        )
    except Exception:
        risk_quant = {}

    needs_human = False
    try:
        if analysis.get("needs_human_review", False):
            needs_human = True
        if conf_val is not None and float(conf_val) < float(_get_support_thresholds()["cv_confidence_low_min"]):
            needs_human = True
        if analysis.get("severity") in ("major", "high", "critical"):
            needs_human = True
        if fraud_level in ("high",):
            needs_human = True
        if risk_quant.get("risk_band") == "high":
            needs_human = True
        if gate_force_review:
            needs_human = True
    except Exception:
        pass

    # Guest flow has no order lookup, so supplier signals are unavailable.
    supplier_signals = {}
    evidence_bundle = build_evidence_bundle(
        case_id=case_id,
        sanitized_images=dmg_sanitized,
        labels=labels,
        extracted_text=extracted_text,
        analysis=analysis or {},
        reverse_hits=reverse_hits,
        forensics=forensics,
        ocr=serial_ocr,
        supply_chain=supply_chain,
        provider="ollama" if labels or extracted_text else "none",
        model=os.getenv("CV_MODEL", "llava"),
        processing_time_ms=triage_ms,
        sanitize_time_ms=sanitize_ms,
        fraud={"score": fraud_score, "level": fraud_level, "signals": signals},
        trust=trust if isinstance(trust, dict) else {},
        issue_type=issue_type,
        description=description,
    )
    evidence_tags = _build_evidence_tags(
        rule_signals=rule_eval.get("signals") or {},
        forensics=forensics or {},
        fraud_level=fraud_level,
        supplier_signals=supplier_signals or {},
        tier2=cv_tiered_analysis if isinstance(cv_tiered_analysis, dict) else {},
        expected_serial=expected_serial if "expected_serial" in locals() else None,
        observed_serial=observed_serial if "observed_serial" in locals() else None,
    )
    playbook_preview = select_cv_playbook(evidence_tags, risk_quant.get("risk_band"))
    override_playbook = get_cv_playbook_by_id(playbook_override)
    if override_playbook:
        playbook_preview = {
            "playbook": override_playbook,
            "triggered_by": ["manual_override"],
            "risk_band": risk_quant.get("risk_band"),
            "override": True,
        }
    evidence_bundle["evidence_tags"] = evidence_tags
    if playbook_preview:
        evidence_bundle["playbook_preview"] = playbook_preview
    evidence_id = None
    try:
        evidence_id = persist_evidence_bundle(case_id, evidence_bundle)
        if evidence_id is None:
            evidence_id = f"evidence-{case_id}"
    except Exception:
        evidence_id = f"evidence-{case_id}"

    decision_id = log_decision(
        agent_name="cv_triage_guest_agent",
        input_data={"case_id": case_id, "issue_type": issue_type, "description": scrub_pii(description)},
        retrieved_context={
            "receipt": {"sha256": rec.get("sha256")},
            "images": [{"sha256": s.get("sha256"), "phash": s.get("phash")} for s in dmg_sanitized],
            "trust_score": trust,
            "fraud": {"score": fraud_score, "level": fraud_level},
            "fraud_signals": signals,
            "reverse_image_hits": reverse_hits,
            "agent_chain": agent_chain,
            "risk_quantification": risk_quant,
            "customer_tier": customer_tier,
            "evidence_bundle": evidence_bundle,
            "cv_rules": rule_eval.get("rules"),
            "nlp_rules": nlp_rules.get("rules"),
            "security_analysis": security_details,
            "geoip_trace": geoip_trace,
        },
        proposed_action={"analysis": analysis, "suggested_routing": recommended_route},
        agent_reasoning="guest_complaint_triage",
        policy_version="v1",
        approval_required=needs_human,
        execution_status="queued",
    )
    try:
        log_trace_event(
            trace_id=decision_id,
            event_type="security_scan",
            source_type="agent",
            source_id="Security_Observer_Agent",
            target_type="system",
            target_id=None,
            payload={"details": security_details, "severity": security_sev},
        )
    except Exception:
        pass
    try:
        if playbook_preview:
            log_trace_event(
                trace_id=decision_id,
                event_type="cv_playbook",
                source_type="agent",
                source_id="CV_Playbook_Agent",
                target_type="system",
                target_id=playbook_preview.get("playbook", {}).get("id"),
                payload={"evidence_tags": evidence_tags, "playbook": playbook_preview},
            )
    except Exception:
        pass
    try:
        log_trace_event(
            trace_id=decision_id,
            event_type="evidence_bundle",
            source_type="agent",
            source_id="CV_Evidence_Agent",
            target_type="system",
            target_id=None,
            payload={"case_id": case_id, "bundle": evidence_bundle},
        )
    except Exception:
        pass
    try:
        log_trace_event(
            trace_id=decision_id,
            event_type="policy_gate",
            source_type="agent",
            source_id="CV_Rule_Agent",
            target_type="system",
            target_id=None,
            payload={"rules": rule_eval.get("rules"), "signals": rule_eval.get("signals")},
        )
    except Exception:
        pass
    try:
        log_trace_event(
            trace_id=decision_id,
            event_type="cv_pipeline",
            source_type="agent",
            source_id="CV_Triage_Guest_Agent",
            target_type="agent",
            target_id="Complaint_Case",
            payload={
                "labels": labels,
                "confidence": analysis.get("confidence"),
                "severity": analysis.get("severity"),
                "tier2_summary": (
                    (cv_tiered_analysis.get("tier1") or {}).get("tier2_summary")
                    if isinstance(cv_tiered_analysis, dict)
                    else None
                ),
            },
        )
    except Exception:
        pass

    await _dispatch_case_created_notification(case_id)

    ticket_id = None
    if needs_human:
        try:
            signals = {"cv_fraud_high": fraud_level in ("high",), "cv_rules_high": any(r.get("severity") == "high" for r in (rule_eval.get("rules") or []))}
            playbook = select_playbook(signals, severity="high" if risk_quant.get("risk_band") == "high" else "medium")
            evidence_snapshot = build_evidence_snapshot({
                "security": {"signals": signals, "rules": rule_eval.get("rules")},
                "risk_quantification": risk_quant,
                "trace_id": decision_id,
            })
            t = TicketingAgent().create_ticket(
                title="CV guest complaint review",
                description=f"Case {case_id} requires review",
                severity="high" if risk_quant.get("risk_band") == "high" else "medium",
                tenant_id=tenant_id,
                reason_code="cv_risk_threshold",
                trace_id=decision_id,
                policy_version="v1",
                cv_summary={
                    "severity": analysis.get("severity"),
                    "confidence": analysis.get("confidence"),
                    "fraud_level": fraud_level,
                },
                customer_tier=customer_tier,
                playbook=playbook,
                evidence_snapshot=evidence_snapshot,
            )
            ticket_id = t.id
            try:
                log_trace_event(
                    trace_id=decision_id,
                    event_type="human_escalation",
                    source_type="agent",
                    source_id="TicketingAgent",
                    target_type="human",
                    target_id="Support",
                    payload={"ticket_id": ticket_id, "reason": "cv_risk_threshold", "severity": analysis.get("severity")},
                )
            except Exception:
                pass
        except Exception:
            pass

    return {
        "status": "submitted",
        "case_id": case_id,
        "decision_id": decision_id,
        "analysis": analysis,
        "cv_analysis": analysis,
        "cv_tiered_analysis": cv_tiered_analysis,
        "decision": recommended_route,
        "verdict": recommended_route,
        "disclaimer": analysis.get("ai_disclaimer"),
        "trust_score": trust,
        "fraud": {"score": fraud_score, "level": fraud_level},
        "evidence_tags": evidence_tags,
        "playbook_preview": playbook_preview,
        "suggested_routing": recommended_route,
        "geoip_trace": geoip_trace,
        "agent_chain": agent_chain,
        "risk_quantification": risk_quant,
        "human_review": {"status": "pending" if needs_human else "not_required", "ticket_id": ticket_id},
        "ticket_id": ticket_id,
        "evidence_id": evidence_id,
    }


@router.get("/{case_id}/status")
def get_case_status(case_id: str, db=Depends(get_db)) -> Dict:
    """Return latest decision context and case details for a given case id."""
    import json as _json
    from sqlalchemy import text as _text
    # Fetch latest decision linked via input_data case_id
    row = db.execute(_text("SELECT proposed_action, retrieved_context, execution_status, policy_version FROM decision_logs WHERE json_extract(input_data, '$.case_id') = :id ORDER BY system_from DESC LIMIT 1"), {"id": case_id}).fetchone()
    case_info = _get_case_status(case_id)
    # Ensure returned case_info includes an `id` field for API consumers/tests
    try:
        if isinstance(case_info, dict) and "id" not in case_info:
            case_info["id"] = case_id
    except Exception:
        case_info = {"id": case_id}
    if not row:
        return {"status": "not_found", "case_id": case_id, "case": case_info}
    try:
        action = _json.loads(row[0] or "{}")
    except Exception:
        action = {}
    try:
        ctx = _json.loads(row[1] or "{}")
    except Exception:
        ctx = {}
    analysis_out = action.get("analysis") if isinstance(action, dict) else action
    decision_out = None
    if isinstance(action, dict):
        decision_out = action.get("suggested_routing") or action.get("decision") or action.get("status")
    if not decision_out:
        decision_out = row[2]
    return {
        "status": "ok",
        "case_id": case_id,
        "execution_status": row[2],
        "policy_version": row[3],
        "analysis": analysis_out or action,
        "cv_analysis": analysis_out or action,
        "decision": decision_out,
        "context": ctx,
        "case": case_info,
    }


@router.get("/{case_id}/evidence")
def get_case_evidence(case_id: str, db=Depends(get_db)) -> Dict:
    bundle = get_evidence_bundle(case_id)
    if not bundle or "ct_hashes" not in bundle or "ocr_extract" not in bundle:
        try:
            from sqlalchemy import text as _text
            import json as _json
            row = db.execute(
                _text(
                    "SELECT retrieved_context FROM decision_logs "
                    "WHERE json_extract(input_data, '$.case_id') = :id "
                    "ORDER BY system_from DESC LIMIT 1"
                ),
                {"id": case_id},
            ).fetchone()
            if row:
                ctx = _json.loads(row[0] or "{}")
                candidate = ctx.get("evidence_bundle") or {}
                if candidate:
                    bundle = candidate
        except Exception:
            pass
    if not bundle:
        return {"status": "not_found", "case_id": case_id}
    return {"status": "ok", "case_id": case_id, "evidence": bundle}


@router.post("/{case_id}/add-images")
async def add_images(case_id: str, images: list[UploadFile] = File(...), db=Depends(get_db), request: Request = None) -> Dict:
    """Append images and trigger re-analysis, logging a new decision entry."""
    from src.app.services.image_intake import sanitize_image
    from src.app.services.cv_triage_basic import BasicCVTriage
    from src.app.services.cv_provider import ManagedCVProvider
    sanitize_t0 = None
    try:
        import time as _t
        sanitize_t0 = _t.perf_counter()
    except Exception:
        sanitize_t0 = None
    sanitized = []
    blocked_uploads: List[Dict[str, Any]] = []
    for idx, img in enumerate(images or []):
        raw = await img.read()
        gate = strict_image_ingest_gate(
            filename=_safe_filename(getattr(img, "filename", None), idx),
            content_type=getattr(img, "content_type", None),
            blob=raw,
            size_bytes=len(raw),
        )
        if bool(gate.get("blocked")):
            blocked_uploads.append(
                {
                    "index": idx,
                    "filename": _safe_filename(getattr(img, "filename", None), idx),
                    "reasons": list(gate.get("block_reasons") or []),
                    "ingest_gate": gate.get("ingest_gate"),
                }
            )
            continue
        sanitized.append(sanitize_image(raw))
    if blocked_uploads:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "ingest_gate_blocked",
                "message": "One or more uploaded images failed strict ingest checks.",
                "blocked_uploads": blocked_uploads[:8],
            },
        )
    sanitize_ms = None
    try:
        if sanitize_t0 is not None:
            sanitize_ms = int((_t.perf_counter() - sanitize_t0) * 1000)
    except Exception:
        sanitize_ms = None
    labels: list[str] = []
    extracted_text = ""
    cv_dt_ms = 0
    try:
        if sanitized:
            import time as _t
            _t0 = _t.perf_counter()
            labels, extracted_text, *_ = await ManagedCVProvider().get_labels_and_text(sanitized[0].get("bytes") or b"")
            cv_dt_ms = int((_t.perf_counter() - _t0) * 1000)
    except Exception:
        pass
    # Fetch tenant_id from case record when available
    tenant_id = None
    customer_tier = None
    try:
        from sqlalchemy import text as _text
        row = db.execute(_text("SELECT tenant_id FROM cases WHERE id = :id"), {"id": case_id}).fetchone()
        if row:
            tenant_id = row[0]
    except Exception:
        tenant_id = None
    try:
        if request is not None and hasattr(request, "headers"):
            customer_tier = request.headers.get("X-User-Tier") or request.headers.get("x-user-tier")
    except Exception:
        customer_tier = None
    # Reverse image search on added image
    reverse_hits: list[Dict] = []
    try:
        if sanitized and sanitized[0].get("phash"):
            reverse_hits = ReverseImageSearch().find_similar(sanitized[0]["phash"], max_distance=8, limit=5)
    except Exception:
        reverse_hits = []
    triage = BasicCVTriage()
    triage_t0 = None
    try:
        import time as _t2
        triage_t0 = _t2.perf_counter()
    except Exception:
        triage_t0 = None
    res = triage.analyze(labels=labels, extracted_text=extracted_text)
    try:
        import inspect as _inspect
        analysis = await res if _inspect.isawaitable(res) else res
    except Exception:
        analysis = res
    triage_ms = None
    try:
        if triage_t0 is not None:
            triage_ms = int((_t2.perf_counter() - triage_t0) * 1000)
    except Exception:
        triage_ms = None
    agent_chain = [
        {"agent": "Image_Intake_Agent", "confidence": 1.0, "duration_ms": sanitize_ms},
        {"agent": "CV_Label_Agent", "confidence": analysis.get("confidence"), "duration_ms": cv_dt_ms},
        {"agent": "Routing_Agent", "confidence": None, "duration_ms": triage_ms},
    ]

    risk_quant = {}
    try:
        risk_quant = quantify_risk(
            security=None,
            cv_analysis=analysis or {},
            fraud=None,
            policy_gates=None,
            monetary_exposure=None,
            history_score=None,
        )
    except Exception:
        risk_quant = {}

    needs_human = False
    try:
        if analysis.get("needs_human_review", False):
            needs_human = True
        if conf_val is not None and float(conf_val) < float(_get_support_thresholds()["cv_confidence_low_min"]):
            needs_human = True
        if analysis.get("severity") in ("major", "high", "critical"):
            needs_human = True
        if risk_quant.get("risk_band") == "high":
            needs_human = True
        if gate_force_review:
            needs_human = True
    except Exception:
        pass
    # Trust routing for add-images flow (neutral trust score)
    try:
        trust_dec = route_from_trust(
            trust_score=0.5,
            risk_band=risk_quant.get("risk_band"),
            amount_usd=(risk_quant.get("exposure", {}) or {}).get("exposure_cents", 0) / 100.0 if isinstance(risk_quant, dict) else None,
        )
        if trust_dec.route == "security_review":
            needs_human = True
        try:
            log_trace_event(
                trace_id=case_id,
                event_type="trust_routing",
                source_type="agent",
                source_id="Trust_Routing_Agent",
                target_type="system",
                target_id=None,
                payload={
                    "trust_score": trust_dec.trust_score,
                    "tier": trust_dec.tier,
                    "route": trust_dec.route,
                    "reasons": trust_dec.reasons,
                },
            )
        except Exception:
            pass
    except Exception:
        pass

    rule_eval = _evaluate_cv_rules(
        description="",
        issue_type="add_images",
        analysis=analysis or {},
        extracted_text=extracted_text or "",
        labels=labels,
        reverse_hits=reverse_hits,
        fraud_score=None,
        fraud_level=None,
        trust=None,
        order_id=None,
    )
    # Security observer scan for CV evidence (add-images flow)
    security_details = {}
    security_sev = None
    gate_force_review = False
    try:
        security_payload = {
            "description": "",
            "issue_type": "add_images",
            "ocr_text": extracted_text,
            "labels": labels,
            "reverse_hits": reverse_hits,
            "cv_rules": rule_eval.get("rules"),
            "cv_signals": rule_eval.get("signals"),
        }
        security_analysis = analyze_payload(security_payload)
        security_details = security_analysis.get("details") or {}
        security_sev = security_analysis.get("severity")
        try:
            emit_security_event("/api/v1/support/complaints/add-images", {"payload": security_payload, "analysis": security_details}, request=request)
        except Exception:
            pass
        try:
            log_trace_event(
                trace_id=case_id,
                event_type="security_scan",
                source_type="agent",
                source_id="Security_Observer_Agent",
                target_type="system",
                target_id=None,
                payload={"details": security_details, "severity": security_sev},
            )
        except Exception:
            pass
        risk_score = float(security_details.get("risk_adj") or 0.0)
        if risk_score > 1.0 and risk_score <= 100.0:
            risk_score = risk_score / 100.0
        gate = evaluate_policy_gate(
            {
                "tool": "support.complaints.add-images",
                "params": {"case_id": case_id},
                "risk_score": risk_score,
                "policy_version": "v1",
                "request_type": "cv",
                "signals": security_details.get("signals") or {},
                "severity": security_sev or "info",
                "pii_types": (security_details.get("evidence") or {}).get("pii_types") or [],
                "ai_assisted": True,
                "buyer_type": None,
                "compliance_provided": None,
            }
        )
        log_trace_event(
            trace_id=case_id,
            event_type="policy_gate",
            source_type="agent",
            source_id="CV_Policy_Gate_Agent",
            target_type="system",
            target_id=None,
            payload={
                "decision": gate.decision,
                "reasons": gate.reasons,
                "rule_hits": gate.rule_hits,
                "policy_version": gate.policy_version,
                "compliance_tags": gate.compliance_tags,
                "action": gate.action,
            },
        )
        if gate.decision in ("review", "deny"):
            gate_force_review = True
    except Exception:
        security_details = {}
        security_sev = None
    # Populate forensic/ocr/supply-chain analysis for the new images (best-effort)
    forensics = {}
    serial_ocr = {}
    supply_chain = {}
    try:
        if sanitized:
            from src.app.services.image_forensics import ImageForensicsService
            forensics = ImageForensicsService().analyze_image(sanitized[0].get("bytes") or b"")
    except Exception:
        forensics = {}
    try:
        if sanitized:
            from src.app.services.serial_extractor import SerialExtractor
            serial_ocr = SerialExtractor().extract_serial(sanitized[0].get("bytes") or b"")
    except Exception:
        serial_ocr = {}
    try:
        if sanitized:
            from src.app.services.supply_chain_cv import CVSupplyChainMonitor
            supply_chain = CVSupplyChainMonitor().analyze_upload(sanitized[0].get("bytes") or b"", {})
    except Exception:
        supply_chain = {}

    evidence_bundle = build_evidence_bundle(
        case_id=case_id,
        sanitized_images=sanitized,
        labels=labels,
        extracted_text=extracted_text,
        analysis=analysis or {},
        reverse_hits=reverse_hits,
        forensics=forensics,
        ocr=serial_ocr,
        supply_chain=supply_chain,
        provider="ollama" if labels or extracted_text else "none",
        model=os.getenv("CV_MODEL", "llava"),
        processing_time_ms=cv_dt_ms,
        sanitize_time_ms=sanitize_ms,
        fraud=None,
        trust=None,
        issue_type="add_images",
        description=None,
    )

    new_id = log_decision(
        agent_name="cv_triage_agent",
        input_data={"parent_case_id": case_id},
        retrieved_context={
            "labels": labels,
            "images": [{"sha256": s.get("sha256"), "phash": s.get("phash")} for s in sanitized],
            "reverse_image_hits": reverse_hits,
            "agent_chain": agent_chain,
            "risk_quantification": risk_quant,
            "customer_tier": customer_tier,
            "evidence_bundle": evidence_bundle,
            "cv_rules": rule_eval.get("rules"),
            "security_analysis": security_details,
        },
        proposed_action={"analysis": analysis},
        agent_reasoning="reanalysis_add_images",
        policy_version="v1",
        approval_required=needs_human,
        execution_status="queued",
        tenant_id=tenant_id,
    )
    try:
        log_trace_event(
            trace_id=new_id,
            event_type="security_scan",
            source_type="agent",
            source_id="Security_Observer_Agent",
            target_type="system",
            target_id=None,
            payload={"details": security_details, "severity": security_sev},
        )
    except Exception:
        pass
    try:
        log_trace_event(
            trace_id=new_id,
            event_type="evidence_bundle",
            source_type="agent",
            source_id="CV_Evidence_Agent",
            target_type="system",
            target_id=None,
            payload={"case_id": case_id, "bundle": evidence_bundle},
        )
    except Exception:
        pass
    try:
        persist_evidence_bundle(case_id, evidence_bundle)
    except Exception:
        pass
    try:
        log_trace_event(
            trace_id=new_id,
            event_type="policy_gate",
            source_type="agent",
            source_id="CV_Rule_Agent",
            target_type="system",
            target_id=None,
            payload={"rules": rule_eval.get("rules"), "signals": rule_eval.get("signals")},
        )
    except Exception:
        pass
    try:
        log_trace_event(
            trace_id=new_id,
            event_type="cv_pipeline",
            source_type="agent",
            source_id="CV_Triage_Agent",
            target_type="agent",
            target_id="Complaint_Case",
            payload={"labels": labels, "confidence": analysis.get("confidence"), "severity": analysis.get("severity")},
        )
    except Exception:
        pass
    # Persist CV analysis evidence history (first image)
    try:
        if sanitized:
            from src.app.services.cv_evidence import persist_cv_analysis
            persist_cv_analysis(
                case_id=case_id,
                image_sha256=sanitized[0].get("sha256"),
                image_phash=sanitized[0].get("phash"),
                analysis=analysis,
                labels=labels,
                extracted_text=extracted_text,
                provider="ollama" if labels or extracted_text else "none",
                model=os.getenv("CV_MODEL", "llava"),
                processing_time_ms=cv_dt_ms,
            )
    except Exception:
        pass
    return {"status": "submitted", "new_decision_id": new_id, "analysis": analysis, "agent_chain": agent_chain}


@router.get("/{case_id}/return-label")
async def get_return_label(case_id: str) -> Dict:
    # Delegate to the single honest label path. When no real carrier is configured the label is a
    # stub (tracking_number=None, status='stub') — we surface that instead of fabricating a tracking
    # number that looks like a real shipment.
    from src.app.services.shipping_stub import ShippingService

    label = await ShippingService().create_return_label(case_id)
    return {"status": "ok" if label.get("ok") else "stub", "case_id": case_id, "label": label}
