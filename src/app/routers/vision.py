from fastapi import APIRouter, UploadFile, File, Depends, HTTPException, Query
from typing import Any, Dict, List, Optional
import asyncio as _asyncio
import concurrent.futures as _futures
import functools as _functools
import json
import os
import re
import uuid
import hashlib
import inspect

from src.app.models.event_log import ensure_event_log_table
from src.app.models.db import db_session
from sqlalchemy import text as sql_text
from src.app.security.auth import require_role, ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER
from src.app.services.cv_triage_basic import BasicCVTriage
from src.app.services.cv_provider import ManagedCVProvider, VisionProviderBusy
from src.app.services.cv_ocr import extract_text as extract_text_stage_a
from src.app.services.image_intent_router import classify_image_intent
from src.app.services.intake_gate import strict_image_ingest_gate
from src.app.services.image_intake import sanitize_image
from src.app.routers.support_complaints import _normalize_ocr_and_detect, _probe_redirect_chain
from src.app.security import linked_artifact_analysis
from src.app.security.passive_payload_analysis import classify_passive_payload
from src.app.security.threat_hunter_leads import build_threat_hunter_leads
from src.app.security.siem_adapter import build_normalized_security_event, emit_security_handoff
from src.app.platform.tenant_context import current_tenant_id
from src.app.services.faq_bank import match_faq

router = APIRouter(prefix="/api/v1/vision", tags=["vision"])

_IMAGE_WORKERS = max(1, min(int(os.getenv("CV_IMAGE_WORKERS", "3") or 3), 8))
_IMAGE_EXECUTOR = _futures.ThreadPoolExecutor(
    max_workers=_IMAGE_WORKERS,
    thread_name_prefix="vision-bounded",
)


def _persist_artifact_verdict(*, artifact_id: str, sha256: str, state: str,
                              coverage: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Append the upload verdict under the request's authorized tenant context."""
    from src.app.platform.tenant_context import current_tenant_id
    from src.app.security.artifact_authority import (
        invalidate_bindings_for_late_verdict,
        record_verdict,
    )

    tenant_id = current_tenant_id()
    with db_session() as db:
        current = db.execute(
            sql_text(
                "SELECT verdict_version, state FROM artifact_security_verdicts "
                "WHERE tenant_id=:tenant AND artifact_id=:artifact "
                "ORDER BY verdict_version DESC LIMIT 1"
            ),
            {"tenant": tenant_id, "artifact": artifact_id},
        ).mappings().first()
        previous_state = str(current["state"]) if current else ""
        previous_version = int(current["verdict_version"]) if current else 0
        if not current:
            last = record_verdict(
                db, artifact_id=artifact_id, tenant_id=tenant_id,
                artifact_sha256=sha256, state="received", reason="upload_received",
            )
            previous_version = int(last["verdict_version"])
            if state in {"pending", "clean"}:
                for next_state, reason in (
                    ("admitted", "strict_admission_passed"),
                    ("pending", "inspection_started"),
                ):
                    last = record_verdict(
                        db, artifact_id=artifact_id, tenant_id=tenant_id,
                        artifact_sha256=sha256, state=next_state, reason=reason,
                        expected_previous_version=previous_version,
                    )
                    previous_version = int(last["verdict_version"])
                if state == "clean":
                    last = record_verdict(
                        db, artifact_id=artifact_id, tenant_id=tenant_id,
                        artifact_sha256=sha256, state="clean", reason="inspection_complete",
                        coverage=coverage, expected_previous_version=previous_version,
                    )
            else:
                last = record_verdict(
                    db, artifact_id=artifact_id, tenant_id=tenant_id,
                    artifact_sha256=sha256, state=state, reason=f"inspection_{state}",
                    coverage=coverage, expected_previous_version=previous_version,
                )
        elif previous_state == state or (previous_state == "clean" and state == "pending"):
            last = {
                "artifact_id": artifact_id, "tenant_id": tenant_id,
                "artifact_sha256": sha256, "verdict_version": previous_version,
                "state": previous_state,
            }
        else:
            last = record_verdict(
                db, artifact_id=artifact_id, tenant_id=tenant_id,
                artifact_sha256=sha256, state=state, reason=f"inspection_{state}",
                coverage=coverage, expected_previous_version=previous_version,
            )
            if previous_state == "clean" and state in {"quarantined", "degraded"}:
                invalidate_bindings_for_late_verdict(
                    db, tenant_id=tenant_id, artifact_id=artifact_id,
                    reason=f"late_{state}_verdict",
                )
        db.commit()
        return last


async def _run_bounded_image_work(fn, *, timeout: float):
    """Run blocking image work without growing the default executor queue.

    Cancelling or timing out the await cancels work that has not started. Work already
    executing must still obey its provider/subprocess deadline; Python cannot kill a
    running native thread safely.
    """
    loop = _asyncio.get_running_loop()
    future = loop.run_in_executor(_IMAGE_EXECUTOR, fn)
    try:
        return await _asyncio.wait_for(future, timeout=max(0.1, float(timeout)))
    finally:
        if not future.done():
            future.cancel()

# Product photo heuristic: labels that suggest a clean, undamaged product shot
_PRODUCT_LABEL_KW = {
    "laptop", "phone", "tablet", "monitor", "keyboard", "headphone",
    "camera", "printer", "router", "speaker", "watch", "console",
    "computer", "desktop", "mouse", "charger", "cable", "adapter",
}

_DAMAGE_LABEL_KW = {
    "crack", "broken", "dent", "scratch", "shatter", "damage",
    "defect", "torn", "crushed", "scuff", "stain",
}

_BRAND_HINT_KW = {
    "apple": ("apple", "macbook", "imac", "mac mini", "mac pro"),
    "msi": ("msi", "raider", "stealth", "creator", "thin a15", "modern 15"),
    "lenovo": ("lenovo", "thinkpad", "ideapad", "legion", "yoga"),
    "asus": ("asus", "vivobook", "zenbook", "rog", "tuf", "proart"),
    "dell": ("dell", "xps", "inspiron", "latitude", "precision", "alienware"),
    "hp": ("hp", "hewlett", "envy", "spectre", "pavilion", "omen", "victus", "zbook"),
    "microsoft": ("microsoft", "surface"),
    "acer": ("acer", "aspire", "nitro", "predator", "swift"),
}

_MIN_STAGE_B_OCR_BYTES = max(1024, int(os.getenv("CV_STAGE_B_OCR_MIN_BYTES", "4096") or 4096))


def _canonical_qr_assessment(signals: Dict[str, Any]) -> Dict[str, Any] | None:
    payloads = signals.get("qr_payloads")
    if not isinstance(payloads, list) or not payloads:
        return None
    if bool(signals.get("qr_prompt_injection")):
        risk_levels = ["malicious"]
        action = "block"
        reason = "QR payload contains instruction-like content targeting the assistant."
    elif bool(signals.get("qr_external_url_detected") or signals.get("qr_external_url")):
        risk_levels = [str(x.get("risk_level") or "review") for x in payloads if isinstance(x, dict)] or ["review"]
        action = "review"
        reason = str(signals.get("qr_reason_summary") or "QR destination requires review.")
    else:
        risk_levels = [str(x.get("risk_level") or "benign") for x in payloads if isinstance(x, dict)] or ["benign"]
        action = "allow"
        reason = str(signals.get("qr_reason_summary") or "QR content decoded and no risky pattern was observed.")
    return {
        "risk_levels": risk_levels[:5],
        "reason_summary": reason,
        "policy_action": action,
        "decoded_count": len(payloads),
    }


def _needs_damage_reasoning(labels: List[str], text: str, filename: str) -> bool:
    combined = " ".join([*(str(label).lower() for label in labels), str(text or "").lower(),
                         str(filename or "").lower()])
    return any(token in combined for token in (
        *_DAMAGE_LABEL_KW, "failed", "failure", "dead", "black screen", "won't boot",
        "wont boot", "error screen", "repair", "warranty", "return",
    ))


def _vision_payload_drilldown(
    finding_type: str,
    *,
    payload_analysis: Dict[str, Any],
    security_signals: Dict[str, Any],
    linked_artifact: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    linked = linked_artifact if isinstance(linked_artifact, dict) else {}
    if finding_type == "lolbin_command_sequence":
        return {
            "headline": "Hidden LOLBin command-sequence pattern observed",
            "what_to_look_for": [
                "PowerShell, certutil, mshta, regsvr32, rundll32, bitsadmin, wscript, or cscript launches",
                "Encoded commands, download-and-execute chains, or suspicious child processes",
                "Outbound requests to fetch payloads immediately after artifact handling",
            ],
            "forensic_checks": list(payload_analysis.get("runtime_evidence_required") or []),
            "human_verification": [
                "Treat this as a passive artifact hypothesis until sandbox and endpoint telemetry confirm execution.",
            ],
            "affected_scope": "Any endpoint or user session that opened or processed the image may be affected.",
            "potential_damage": "Payload staging, malware execution, or follow-on compromise using trusted tools.",
        }
    if finding_type == "c2_beacon_pattern":
        return {
            "headline": "Hidden C2 beacon pattern observed",
            "what_to_look_for": [
                "Repeated low-volume callback traffic or beacon intervals",
                "Proxy, DNS, firewall, or XDR telemetry showing check-ins after the image was handled",
                "Small recurring packets, jitter, or unusual periodic requests",
            ],
            "forensic_checks": list(payload_analysis.get("runtime_evidence_required") or []),
            "human_verification": [
                "Do not treat this as confirmed command-and-control until runtime telemetry shows callback behavior.",
            ],
            "affected_scope": "Any host that opened the artifact or shows the same callback behavior in telemetry.",
            "potential_damage": "Persistence and remote tasking if the hidden pattern was operationalized.",
        }
    if finding_type == "data_exfiltration_instruction":
        return {
            "headline": "Hidden data-exfiltration instructions observed",
            "what_to_look_for": [
                "Archive creation, compression, browser uploads, curl/wget/scp/rclone activity",
                "Cloud bucket access, unusual file access, or outbound transfers after artifact interaction",
                "Endpoint, eBPF, EDR, proxy, and identity evidence tied to the same user or host",
            ],
            "forensic_checks": list(payload_analysis.get("runtime_evidence_required") or []),
            "human_verification": [
                "Treat this as unconfirmed until endpoint, CASB/DLP, or proxy telemetry shows actual transfer activity.",
            ],
            "affected_scope": "Potentially affected users are those who opened the artifact or had access to targeted data sources.",
            "potential_damage": "Sensitive files, credentials, or business data may have been staged or targeted for theft.",
        }
    if finding_type == "prompt_injection_hidden":
        carrier = "steganography"
        if bool(security_signals.get("qr_prompt_injection")):
            carrier = "QR payload"
        elif bool(security_signals.get("invisible_text_suspected")):
            carrier = "text overlay / hidden OCR content"
        return {
            "headline": "Hidden prompt injection detected",
            "carrier": carrier,
            "what_to_look_for": [
                "Model or agent logs showing unsafe tool requests or abnormal context leakage",
                "Any workflow that ingested the artifact before sanitization",
                "Prompt text attempting to override instructions or reveal protected context",
            ],
            "human_verification": [
                "Confirm whether the artifact was ingested by any agent, OCR pipeline, or tool-enabled model before allowing automation.",
            ],
            "business_risk": "AI decision quality, tool safety, and downstream automation integrity may be affected.",
        }
    if finding_type == "ssn_leakage_linked_qr":
        return {
            "headline": "Linked QR path suggests SSN or PII leakage",
            "linked_artifact_type": linked.get("linked_artifact_type"),
            "ssn_count": len(linked.get("ssn_hits") or []),
            "pii_types": linked.get("pii_type") or [],
            "what_to_look_for": [
                "Public-link exposure, object permission failures, or RBAC/ABAC misconfiguration",
                "Access logs, referrers, GeoIP, and hosting ASN traffic to the exposed artifact",
                "Whether the exposure came from insider misuse, supplier publication, or external access",
            ],
            "privacy_scope": [
                "Assess whether the linked destination exposed regulated identity data to unauthorised parties.",
            ],
            "human_verification": [
                "Validate destination ownership, access controls, and whether the linked artifact was publicly reachable.",
            ],
            "business_risk": "Potential privacy-reporting, reputational, and legal exposure if the linked content was publicly accessible.",
        }
    return {}


def _vision_artifact_evidence_refs(
    *,
    payload_analysis: Dict[str, Any],
    security_signals: Dict[str, Any],
    linked_artifact: Dict[str, Any] | None,
    extracted_text: str,
) -> List[str]:
    refs: List[str] = []
    if payload_analysis.get("payload_type") == "qr":
        refs.append("image.qr_payloads[0].data")
    if payload_analysis.get("payload_type") == "embedded_text" and str(extracted_text or "").strip():
        refs.append("image.ocr_text")
    steg_details = security_signals.get("steg_details") if isinstance(security_signals.get("steg_details"), dict) else {}
    if str(steg_details.get("decoded_content") or "").strip():
        refs.append("image.steg_details.decoded_content")
    elif bool(security_signals.get("steg_suspicious")):
        refs.append("image.steg_signal")
    if bool(security_signals.get("qr_code_detected")):
        refs.append("image.qr_code_detected")
    linked = linked_artifact if isinstance(linked_artifact, dict) else {}
    if linked.get("linked_artifact_available"):
        refs.append("linked_artifact.fetch")
    if linked.get("ssn_hits"):
        refs.append("linked_artifact.ssn_hits")
    if linked.get("pii_type"):
        refs.append("linked_artifact.pii_type")
    if linked.get("linked_final_url"):
        refs.append("linked_artifact.final_url")
    return list(dict.fromkeys([ref for ref in refs if ref]))[:8]


def _vision_artifact_provenance(
    *,
    source_name: str,
    payload_analysis: Dict[str, Any],
    security_signals: Dict[str, Any],
    linked_artifact: Dict[str, Any] | None,
    extracted_text: str,
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    payload_type = str(payload_analysis.get("payload_type") or "").strip().lower()
    if payload_type == "qr":
        rows.append(
            {
                "source_file": source_name,
                "extraction_method": "qr_decode",
                "match_ref": "image.qr_payloads[0].data",
                "confidence": "high",
            }
        )
    elif payload_type == "embedded_text" and str(extracted_text or "").strip():
        rows.append(
            {
                "source_file": source_name,
                "extraction_method": "ocr_text_extract",
                "match_ref": "image.ocr_text",
                "confidence": "medium",
            }
        )
    steg_details = security_signals.get("steg_details") if isinstance(security_signals.get("steg_details"), dict) else {}
    if str(steg_details.get("decoded_content") or "").strip():
        rows.append(
            {
                "source_file": source_name,
                "extraction_method": "steg_lsb_extract",
                "match_ref": "image.steg_details.decoded_content",
                "confidence": "medium",
            }
        )
    elif bool(security_signals.get("steg_suspicious")):
        rows.append(
            {
                "source_file": source_name,
                "extraction_method": "steg_detector",
                "match_ref": "image.steg_signal",
                "confidence": "medium",
            }
        )
    linked = linked_artifact if isinstance(linked_artifact, dict) else {}
    if linked.get("linked_artifact_available"):
        linked_rows = linked.get("linked_artifact_provenance")
        if isinstance(linked_rows, list) and linked_rows:
            rows.extend([row for row in linked_rows if isinstance(row, dict)])
        else:
            rows.append(
                {
                    "source_file": str(linked.get("linked_filename") or linked.get("linked_final_url") or "linked_artifact"),
                    "extraction_method": "passive_link_fetch",
                    "match_ref": "linked_artifact.fetch",
                    "confidence": "medium",
                }
            )
    return rows[:8]


def _compute_damage_score(analysis: Dict) -> float:
    """Derive a 0.0-1.0 damage score from CV triage analysis."""
    if not isinstance(analysis, dict):
        return 0.0
    confidence = float(analysis.get("confidence") or 0.0)
    damage_type = str(analysis.get("damage_type") or "").lower()
    severity = str(analysis.get("severity") or "").lower()
    if damage_type == "unknown" or analysis.get("insufficient_data"):
        return max(0.05, confidence * 0.2)
    severity_map = {"critical": 0.95, "major": 0.75, "minor": 0.45, "undetermined": 0.25}
    base = severity_map.get(severity, 0.3)
    return round(min(1.0, base * max(0.4, confidence)), 3)


def _is_product_photo(labels: List[str], damage_score: float) -> bool:
    """Heuristic: image is a clean product photo (not damage evidence)."""
    if damage_score > 0.4:
        return False
    label_text = " ".join(labels).lower()
    has_product = any(kw in label_text for kw in _PRODUCT_LABEL_KW)
    has_damage = any(kw in label_text for kw in _DAMAGE_LABEL_KW)
    return has_product and not has_damage


def _compute_image_hash(content: bytes) -> str:
    """SHA-256 of raw image bytes for dedup."""
    return hashlib.sha256(content).hexdigest()[:32]


def _mask_ssn(value: str) -> str:
    digits = re.sub(r"\D", "", str(value or ""))
    return f"***-**-{digits[-4:]}" if len(digits) >= 4 else "***-**-****"


def _redact_linked_artifact_pii(linked: Dict[str, Any]) -> Dict[str, Any]:
    """Mask the RAW PII the linked-artifact scan extracted so the detection SIGNAL survives
    (ssn_detected / ssn_count / pii_type) but the cleartext values never propagate into the triage
    response, logs, traces, or the persisted event — echoing them there turns the detector into a
    second exposure surface (data-minimisation / Privacy Act). Masks in place; keeps last-4 for
    correlation; idempotent; leaves all non-PII metadata (url, country, asn, summaries) intact."""
    if not isinstance(linked, dict):
        return linked
    hits = linked.get("ssn_hits")
    if isinstance(hits, list) and hits:
        linked["ssn_hits"] = [_mask_ssn(v) for v in hits]
    for key in ("card_hits", "pan_hits", "cc_hits", "card_numbers"):
        vals = linked.get(key)
        if isinstance(vals, list) and vals:
            linked[key] = [
                f"****-****-****-{re.sub(r'[^0-9]', '', str(v))[-4:]}"
                if len(re.sub(r'[^0-9]', '', str(v))) >= 4 else "****"
                for v in vals
            ]
    return linked


def _labels_are_weak(labels: List[str]) -> bool:
    vals = [str(x).strip().lower() for x in (labels or []) if str(x).strip()]
    if not vals:
        return True
    return all(len(v) <= 8 or any(tok in v for tok in ("text", "overlay", "image", "photo")) for v in vals)


def _brand_hint_from_text(*parts: str) -> Optional[str]:
    combined = " ".join(str(p or "") for p in parts).lower()
    if not combined.strip():
        return None
    # Common weak MSI overlay artifact naming: "ms-texti", "ms texti".
    # Treat this as MSI only on the weak-label rescue path, not as a global alias.
    if any(tok in combined for tok in ("ms-texti", "ms texti")):
        return "msi"
    for brand, keywords in _BRAND_HINT_KW.items():
        if any(kw in combined for kw in keywords):
            return brand
    return None


def _derive_query_from_analysis(analysis: Dict) -> str:
    if not isinstance(analysis, dict):
        return "product"
    damage_type = str(analysis.get("damage_type") or "").lower()
    component = str(analysis.get("component") or "").lower()
    if damage_type and damage_type != "unknown":
        return f"{damage_type} {component}".strip()
    if component:
        return component
    return "device"


@router.post("/triage")
async def triage(
    image: UploadFile = File(...),
    fast: bool = Query(False),
    artifact_id: Optional[str] = Query(None, min_length=8, max_length=128),
    role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict:
    """Run lightweight CV triage from uploaded image and persist event metadata."""
    if image is None:
        raise HTTPException(status_code=400, detail="image_required")

    try:
        mime = image.content_type
        name = image.filename
    except Exception:
        mime = None
        name = None

    raw_content = await image.read()
    if not raw_content:
        raise HTTPException(status_code=400, detail="empty_image")
    artifact_id = str(artifact_id or uuid.uuid4())
    artifact_sha256 = hashlib.sha256(raw_content).hexdigest()
    gate = strict_image_ingest_gate(
        filename=str(name or "image.jpg"),
        content_type=mime,
        blob=raw_content,
        size_bytes=len(raw_content),
    )
    if bool(gate.get("blocked")):
        try:
            persisted_artifact = _persist_artifact_verdict(
                artifact_id=artifact_id,
                sha256=artifact_sha256,
                state="quarantined",
                coverage={"strict_admission": "fail"},
            )
        except Exception:
            persisted_artifact = None
        raise HTTPException(
            status_code=400,
            detail={
                "error": "ingest_gate_blocked",
                "message": "Upload blocked by strict ingest gate (type/size/archive/AV policy).",
                "ingest_gate": gate,
                "artifact": persisted_artifact or {
                    "artifact_id": artifact_id,
                    "sha256": artifact_sha256,
                    "state": "degraded",
                    "authority": "blocked",
                },
            },
        )
    try:
        sanitized = sanitize_image(raw_content)
        if isinstance(sanitized, dict) and str(sanitized.get("status") or "") == "sanitized":
            sanitized_content = sanitized.get("bytes")
        else:
            sanitized_content = None
    except Exception as exc:
        try:
            _persist_artifact_verdict(
                artifact_id=artifact_id, sha256=artifact_sha256,
                state="degraded", coverage={"sanitization": "error"},
            )
        except Exception:
            pass
        raise HTTPException(status_code=422, detail={
            "error": "image_malformed_or_unsupported",
            "stage": "sanitization",
            "message": "The image could not be decoded and sanitized safely.",
            "artifact": {
                "artifact_id": artifact_id, "sha256": artifact_sha256,
                "state": "degraded", "authority": "blocked",
            },
        }) from exc
    if not sanitized_content:
        try:
            _persist_artifact_verdict(
                artifact_id=artifact_id, sha256=artifact_sha256,
                state="degraded", coverage={"sanitization": "error"},
            )
        except Exception:
            pass
        raise HTTPException(status_code=422, detail={
            "error": "image_malformed_or_unsupported",
            "stage": "sanitization",
            "message": "The image could not be decoded and sanitized safely.",
            "artifact": {
                "artifact_id": artifact_id, "sha256": artifact_sha256,
                "state": "degraded", "authority": "blocked",
            },
        })

    # Bound the VLM/OCR cost: reject decode-bombs and downscale a COPY for the model pass.
    # `raw_content` is preserved only for steg/forensic analysis below, which is
    # fast (numpy) and MUST see untouched pixels. Without this a 2-24 MP photo hangs the VLM
    # for minutes — a trivial DoS and a functional gap on normal e-commerce image sizes.
    analysis_content = sanitized_content
    downscale_meta: Dict[str, Any] = {}
    try:
        from src.app.services.image_downscale import bound_image_for_vlm
        _bound = bound_image_for_vlm(sanitized_content)
        if bool(_bound.get("reject")):
            _m = _bound.get("meta") or {}
            _reason = str(_bound.get("reason") or "")
            if _reason in {"decode", "resize"}:
                try:
                    _persist_artifact_verdict(
                        artifact_id=artifact_id, sha256=artifact_sha256,
                        state="degraded", coverage={"safe_image_decode": "error"},
                    )
                except Exception:
                    pass
                raise HTTPException(
                    status_code=422,
                    detail={
                        "error": "image_malformed_or_unsupported",
                        "reason": _reason,
                        "message": "The image is malformed or cannot be decoded safely.",
                        "artifact": {
                            "artifact_id": artifact_id, "sha256": artifact_sha256,
                            "state": "degraded", "authority": "blocked",
                        },
                    },
                )
            raise HTTPException(
                status_code=413,
                detail={
                    "error": "image_too_large",
                    "reason": _reason,
                    "message": (
                        "This image is too large to process safely. Please upload a smaller "
                        "product photo (under 30 MP / 25 MB)."
                    ),
                    "image": {"megapixels": _m.get("megapixels"), "bytes": _m.get("bytes")},
                },
            )
        analysis_content = _bound.get("bytes")
        downscale_meta = _bound.get("meta") or {}
        downscale_meta["downscaled"] = bool(_bound.get("downscaled"))
    except HTTPException:
        raise
    except Exception as exc:
        try:
            _persist_artifact_verdict(
                artifact_id=artifact_id, sha256=artifact_sha256,
                state="degraded", coverage={"safe_image_decode": "error"},
            )
        except Exception:
            pass
        raise HTTPException(status_code=422, detail={
            "error": "image_malformed_or_unsupported",
            "reason": "decode_or_resize",
            "message": "The image is malformed or cannot be decoded safely.",
            "artifact": {
                "artifact_id": artifact_id, "sha256": artifact_sha256,
                "state": "degraded", "authority": "blocked",
            },
        }) from exc
    if not analysis_content:
        raise HTTPException(status_code=422, detail="image_decode_or_resize_failed")

    labels = []
    extracted_text = ""
    product_identity = None
    ocr_meta: Dict[str, Any] = {}
    provider_name = "fast_local" if fast else "none"
    analysis_state: Dict[str, Any] = {
        "analysis_pending": bool(fast),
        "analysis_degraded": False,
        "degraded_reasons": [],
    }
    if not fast:
        try:
            provider = ManagedCVProvider()
            provider_name = provider.provider
            labels, extracted_text, product_identity = await _asyncio.wait_for(
                provider.get_labels_and_text(analysis_content, mode="visual_search"),
                timeout=float(os.getenv("CV_PROVIDER_TOTAL_TIMEOUT_S", "10.0") or 10.0),
            )
            ocr_meta = dict(getattr(provider, "last_ocr_meta", {}) or {})
        except _asyncio.TimeoutError:
            labels, extracted_text, product_identity = [], "", None
            ocr_meta = {}
            analysis_state["analysis_degraded"] = True
            analysis_state["degraded_reasons"].append("vision_provider_timeout")
        except VisionProviderBusy:
            labels, extracted_text, product_identity = [], "", None
            ocr_meta = {}
            analysis_state["analysis_pending"] = True
            analysis_state["analysis_degraded"] = True
            analysis_state["degraded_reasons"].append("vision_provider_busy")
        except Exception:
            labels, extracted_text, product_identity = [], "", None
            ocr_meta = {}
            analysis_state["analysis_degraded"] = True
            analysis_state["degraded_reasons"].append("vision_provider_error")

    # P3: Always append sanitized filename as a weak hint (not just when labels empty)
    if name:
        fname_hint = os.path.splitext(str(name).lower())[0].replace("-", " ").replace("_", " ")
        if fname_hint and fname_hint not in " ".join(labels).lower():
            labels = (labels or []) + [fname_hint]

    triager = BasicCVTriage()
    damage_bytes = (analysis_content if not fast and
                    _needs_damage_reasoning(labels, extracted_text, str(name or "")) else None)
    try:
        triage_result = triager.analyze(
            labels,
            extracted_text or "",
            image_bytes=damage_bytes,
            mime=mime or "image/jpeg",
        )
    except TypeError:
        # Test doubles and older triage implementations may still expose the
        # legacy two-argument signature.
        triage_result = triager.analyze(labels, extracted_text or "")
    if inspect.isawaitable(triage_result):
        try:
            analysis = await _asyncio.wait_for(
                triage_result,
                timeout=float(os.getenv("CV_DAMAGE_REASONING_TIMEOUT_S", "8.0") or 8.0),
            )
        except _asyncio.TimeoutError:
            analysis_state["analysis_degraded"] = True
            analysis_state["degraded_reasons"].append("damage_reasoning_timeout")
            analysis = await triager.analyze(labels, extracted_text or "")
    else:
        analysis = triage_result

    from src.app.services.response_normalizer import ResponseNormalizer
    _damage_score = _compute_damage_score(analysis)
    resp = {
        "query": _derive_query_from_analysis(analysis),
        "label": analysis.get("damage_type") or "unknown",
        # Plain-English verdict for the UI — always present
        "summary": ResponseNormalizer.cv_triage_to_english(analysis),
        "mime": mime,
        "filename": name,
        "provider": provider_name,
        "labels": labels[:20],
        "extracted_text": (extracted_text or "")[:500],
        "ocr_confidence": ocr_meta.get("ocr_confidence"),
        "ocr_engine": ocr_meta.get("ocr_engine"),
        "ocr_word_count": ocr_meta.get("ocr_word_count"),
        "cv_extraction_method": ocr_meta.get("cv_extraction_method"),
        "analysis": analysis,
        "damage_score": _damage_score,
        "is_product_photo": _is_product_photo(labels, _damage_score),
        "image_hash": _compute_image_hash(raw_content),
        "ingest_gate": gate,
        "vlm_input": downscale_meta,  # {megapixels, bytes, downscaled, downscaled_to?} — the model saw this
        "analysis_state": analysis_state,
    }

    # P4: Always surface product identity — decoupled from security flags.
    # Even security-flagged images carry brand/model info useful for recommendations.
    if product_identity:
        resp["product_identity"] = product_identity

    # Run image intent router for smart routing guidance
    try:
        intent_result = classify_image_intent(
            image_labels=labels[:12],
            image_ocr_text=(extracted_text or "")[:500],
            damage_score=resp["damage_score"],
            is_product_photo=resp["is_product_photo"],
        )
        resp["intent_routing"] = intent_result
        # Promote intent + damage_score to top-level so the frontend can gate without
        # digging into nested structures (App.tsx toImageTriageContexts reads these)
        resp["intent"] = intent_result.get("intent", "visual_search")
        resp["damage_score"] = max(float(resp.get("damage_score") or 0.0),
                                   float(intent_result.get("damage_score") or 0.0))
    except Exception:
        resp["intent_routing"] = {"intent": "disambiguate", "confidence": 0.0, "reason": "router_error"}
        resp["intent"] = "visual_search"

    # Security scan: QR/barcode + adversarial detection (best-effort)
    security_clean = True
    security_signals: Dict[str, Any] = {}

    # P5: Cross-validate filename brand vs vision model brand (spoofing detection)
    try:
        from src.app.services.filename_brand_validator import validate_filename_vs_labels
        brand_validation = validate_filename_vs_labels(
            filename=str(name or ""),
            vision_labels=labels,
            product_identity=product_identity,
        )
        if brand_validation.get("mismatch"):
            security_signals["filename_brand_mismatch"] = True
            resp["brand_validation"] = brand_validation
    except Exception:
        pass

    qr_product_data: Dict[str, Any] = {}
    linked_artifact_result: Dict[str, Any] | None = None
    qr_redirect_probe: Dict[str, Any] = {"enabled": False, "checked": False, "chain": []}
    qr_risk_levels: List[str] = []
    qr_reason_summaries: List[str] = []
    try:
        from src.app.rules.barcode_decode import decode_barcodes
        if fast:
            try:
                qr = await _run_bounded_image_work(
                    _functools.partial(
                        decode_barcodes,
                        # SECURITY control: decode the QR on the FULL-RES upload (feeds the
                        # qr_external_url_detected -> text_only wipe). A small malicious QR can be
                        # lost after the ~1280px VLM downscale, so this must NOT use analysis_content.
                        [(str(name or "image.jpg"), raw_content)],
                    ),
                    timeout=float(os.getenv("CV_FAST_QR_TIMEOUT_S", "1.5") or 1.5),
                )
            except Exception:
                qr = []
                analysis_state["analysis_pending"] = True
                analysis_state["degraded_reasons"].append("qr_decode_deferred")
        else:
            try:
                qr = await _run_bounded_image_work(
                    _functools.partial(
                        decode_barcodes,
                        # SECURITY control: decode the QR on the FULL-RES upload (feeds the
                        # qr_external_url_detected -> text_only wipe). A small malicious QR can be
                        # lost after the ~1280px VLM downscale, so this must NOT use analysis_content.
                        [(str(name or "image.jpg"), raw_content)],
                    ),
                    timeout=float(os.getenv("CV_QR_TIMEOUT_S", "4.0") or 4.0),
                )
            except Exception:
                qr = []
                analysis_state["analysis_degraded"] = True
                analysis_state["degraded_reasons"].append("qr_decode_error")
        qr_codes = qr.codes if hasattr(qr, "codes") else (qr if isinstance(qr, list) else [])
        if qr_codes:
            security_signals["qr_code_detected"] = True
            qr_risk_levels = [
                str(c.get("risk_level") or "benign").strip().lower()
                for c in qr_codes
                if isinstance(c, dict)
            ]
            qr_reason_summaries = [
                str(c.get("risk_reason") or "").strip()
                for c in qr_codes
                if isinstance(c, dict) and str(c.get("risk_reason") or "").strip()
            ][:3]
            security_signals["qr_benign_detected"] = all(level == "benign" for level in qr_risk_levels) if qr_risk_levels else True
            security_signals["qr_policy_action"] = (
                "allow"
                if security_signals["qr_benign_detected"]
                else ("review" if any(level == "review" for level in qr_risk_levels) else "block")
            )
            if qr_reason_summaries:
                security_signals["qr_reason_summary"] = qr_reason_summaries[0]
            # Surface decoded QR payloads (first 5, truncated to 300 chars each)
            security_signals["qr_payloads"] = [
                {
                    "data": str(c.get("data") or "")[:300],
                    "type": str(c.get("type") or "QR_CODE"),
                    "payload_type": str(c.get("payload_type") or "other"),
                    "risk_level": str(c.get("risk_level") or "benign"),
                    "risk_reason": str(c.get("risk_reason") or "")[:180],
                }
                for c in qr_codes[:5]
                if str(c.get("data") or "").strip()
            ]
            security_signals["qr_payload_types"] = list({
                str(c.get("payload_type") or "").strip()
                for c in qr_codes
                if str(c.get("payload_type") or "").strip()
            })
            # Check for prompt injection in QR data
            try:
                from src.app.routers.support_complaints import _detect_ocr_prompt_injection
                for c in qr_codes:
                    if _detect_ocr_prompt_injection(str(c.get("data") or "")):
                        security_signals["qr_prompt_injection"] = True
                        security_signals["qr_policy_action"] = "block"
                        security_signals["qr_reason_summary"] = "QR payload contains instruction-like content targeting the assistant."
                        security_clean = False
                        break
            except Exception:
                pass
            # Check for external URLs
            try:
                from urllib.parse import urlparse
                for c in qr_codes:
                    data = str(c.get("data") or "").strip()
                    if data.lower().startswith(("http://", "https://")):
                        host = (urlparse(data).hostname or "").lower()
                        if host and host not in ("127.0.0.1", "localhost"):
                            security_signals["qr_external_url"] = True
                            security_signals["qr_external_url_detected"] = True
                            if not bool(security_signals.get("qr_prompt_injection")):
                                security_signals["qr_policy_action"] = "review"
                                security_signals["qr_reason_summary"] = f"QR points to external host {host}."
                            security_clean = False
                            if not fast:
                                try:
                                    qr_redirect_probe = await _probe_redirect_chain(data, timeout_s=1.25, max_hops=3)
                                except Exception:
                                    qr_redirect_probe = {"enabled": True, "checked": False, "chain": [], "error": "probe_exception"}
                                # ── Auto-analyze linked artifact (SSN / PII / payload scan) ──
                                # Run in a thread executor so the synchronous HTTP calls inside
                                # analyze_linked_artifact do not block the event loop.
                                try:
                                    linked = await _run_bounded_image_work(
                                        _functools.partial(
                                            linked_artifact_analysis.analyze_linked_artifact,
                                            url=data,
                                            timeout=3.0,
                                        ),
                                        timeout=4.0,
                                    )
                                    # Mask raw SSN/PAN in place BEFORE `linked` propagates into the
                                    # response, findings, traces, and the persisted event. Detection
                                    # signals (ssn_detected/ssn_count/pii_type) are set from it below.
                                    if isinstance(linked, dict):
                                        _redact_linked_artifact_pii(linked)
                                    linked_artifact_result = linked if isinstance(linked, dict) else None
                                    resp["linked_artifact"] = linked
                                    if linked_artifact_result:
                                        linked_summary = str(linked_artifact_result.get("linked_reason_summary") or "").strip()
                                        linked_action = str(linked_artifact_result.get("linked_policy_action") or "review").strip()
                                        if linked_summary:
                                            security_signals["linked_artifact_reason_summary"] = linked_summary
                                        security_signals["linked_artifact_policy_action"] = linked_action
                                    if linked.get("pii_detected"):
                                        security_signals["pii_detected"] = True
                                        security_signals["pii_types"] = linked.get("pii_type", [])
                                        security_clean = False
                                    if linked.get("ssn_hits"):
                                        security_signals["ssn_detected"] = True
                                        security_signals["ssn_count"] = len(linked["ssn_hits"])
                                        security_clean = False
                                except Exception:
                                    pass
                            else:
                                qr_redirect_probe = {"enabled": False, "checked": False, "chain": [], "deferred": True}
                            break
            except Exception:
                pass
            # ── Productive QR data extraction ──
            # Extract useful product information from QR data (model URLs, serial numbers)
            try:
                from urllib.parse import urlparse as _qr_urlparse
                import re as _qr_re
                _MANUFACTURER_HOSTS = {
                    "apple.com", "www.apple.com", "store.apple.com",
                    "lenovo.com", "www.lenovo.com", "psref.lenovo.com",
                    "dell.com", "www.dell.com",
                    "hp.com", "www.hp.com", "support.hp.com",
                    "asus.com", "www.asus.com",
                    "acer.com", "www.acer.com",
                    "samsung.com", "www.samsung.com",
                    "microsoft.com", "www.microsoft.com",
                }
                for c in qr_codes:
                    data = str(c.get("data") or "").strip()
                    if not data:
                        continue
                    # URL-based product data
                    if data.lower().startswith(("http://", "https://")):
                        parsed = _qr_urlparse(data)
                        host = (parsed.hostname or "").lower()
                        if any(host.endswith(mfr) for mfr in _MANUFACTURER_HOSTS):
                            qr_product_data["manufacturer_url"] = data[:500]
                            # Extract brand from host
                            for mfr in ("apple", "lenovo", "dell", "hp", "asus", "acer", "samsung", "microsoft"):
                                if mfr in host:
                                    qr_product_data["brand_hint"] = mfr.capitalize()
                                    break
                            # Extract model from URL path segments
                            path_parts = [p for p in (parsed.path or "").split("/") if p]
                            if path_parts:
                                qr_product_data["url_path_hint"] = "/".join(path_parts[:3])
                    # Serial number / model number patterns (non-URL QR data)
                    else:
                        # Common serial/model patterns: alphanumeric 6-20 chars
                        sn_match = _qr_re.search(r'\b[A-Z0-9]{6,20}\b', data.upper())
                        if sn_match:
                            qr_product_data["serial_or_model_hint"] = sn_match.group()
                        # Check for structured data (JSON, key=value)
                        if "model" in data.lower() or "product" in data.lower():
                            qr_product_data["structured_data_hint"] = data[:200]
            except Exception:
                pass
    except Exception:
        pass

    if qr_codes := security_signals.get("qr_payloads"):
        if bool(security_signals.get("qr_prompt_injection")):
            for item in qr_codes if isinstance(qr_codes, list) else []:
                if isinstance(item, dict):
                    item["risk_level"] = "malicious"
                    item["risk_reason"] = "QR payload contains instruction-like content targeting the assistant."
            qr_risk_levels = ["malicious"]
        resp["qr_assessment"] = _canonical_qr_assessment(security_signals)

    if not fast:
        try:
            from src.app.security.adversarial_image_detector import detect_adversarial
            adv = await _run_bounded_image_work(
                # SECURITY control on FULL-RES bytes: downscaling attenuates adversarial
                # perturbations, so this must see raw_content (like steg), not analysis_content.
                _functools.partial(detect_adversarial, raw_content),
                timeout=8.0,
            )
            if hasattr(adv, "is_adversarial") and adv.is_adversarial:
                security_signals["adversarial_detected"] = True
                security_clean = False
            if hasattr(adv, "diffusion_score") and adv.diffusion_score > 0.7:
                security_signals["ai_generated_suspected"] = True
        except Exception:
            pass

    # ── Fix 3: steganography detection ──
    if not fast:
        try:
            from src.app.security.steg_detector import detect_steganography
            steg = await _run_bounded_image_work(
                _functools.partial(detect_steganography, raw_content),
                timeout=8.0,
            )
            steg_score = float(getattr(steg, "steg_score", 0.0) or 0.0)
            steg_elevated_min = float(os.getenv("CV_STEG_ELEVATED_MIN", "0.385") or 0.385)
            if hasattr(steg, "is_suspicious") and steg.is_suspicious:
                security_signals["steg_suspicious"] = True
                security_clean = False
            if steg_score:
                security_signals["steg_score"] = round(steg_score, 3)
            if steg_score >= steg_elevated_min:
                security_signals["steg_score_elevated"] = True
                # Keep a near-threshold statistical signal visible for drift and
                # evidence review, but do not turn it into a user-facing block.
                # Compressed/blurred benign images can sit in this advisory band;
                # only the detector's calibrated verdict (or another active
                # finding) may require quarantine/re-upload.
            if getattr(steg, "explanations", None):
                security_signals["steg_explanations"] = list(getattr(steg, "explanations", []) or [])[:8]
            if getattr(steg, "details", None):
                security_signals["steg_details"] = dict(getattr(steg, "details", {}) or {})
        except Exception:
            pass

    # OCR normalization + detector pass (PayID/PCI/crypto/ransom/encoded/unicode).
    try:
        ocr_det = _normalize_ocr_and_detect(extracted_text)
        stage_a_text = str(extracted_text or "").strip()
        filename_hint_for_ocr = os.path.splitext(str(name or "").lower())[0].replace("-", " ").replace("_", " ")
        deep_trigger = bool(
            (
                not stage_a_text
                and any(
                    bool(security_signals.get(sig))
                    for sig in (
                        "qr_code_detected",
                        "qr_external_url",
                        "qr_external_url_detected",
                        "filename_brand_mismatch",
                    )
                )
            )
            or (len(stage_a_text) < 12 and bool(security_signals.get("qr_code_detected")))
            or (not stage_a_text and any(tok in filename_hint_for_ocr for tok in ("ms texti", "ms-texti")))
        )
        if deep_trigger and not fast:
            # Run one cheap CPU OCR pass before the multi-contrast ladder. This preserves security
            # coverage when the VLM is unavailable without paying for OCR on ordinary product photos.
            try:
                stage_a = await _run_bounded_image_work(
                    _functools.partial(
                        extract_text_stage_a,
                        analysis_content,
                        provider=os.getenv("CV_SELECTIVE_OCR_PROVIDER", "tesseract"),
                        fallback=None,
                    ),
                    timeout=float(os.getenv("CV_SELECTIVE_OCR_TIMEOUT_S", "3.0") or 3.0),
                )
                stage_a_text = str(stage_a.get("text") or "").strip()
                if stage_a_text:
                    extracted_text = stage_a_text[:500]
                    ocr_det = _normalize_ocr_and_detect(extracted_text)
                    ocr_meta.update({
                        "ocr_confidence": float(stage_a.get("confidence") or 0.0),
                        "ocr_engine": str(stage_a.get("provider") or "tesseract"),
                        "ocr_word_count": len(stage_a_text.split()),
                        "cv_extraction_method": "selective_ocr_stage_a",
                    })
            except _asyncio.TimeoutError:
                analysis_state["analysis_degraded"] = True
                analysis_state["degraded_reasons"].append("selective_ocr_timeout")

        if (deep_trigger and not fast and not stage_a_text
                and len(analysis_content) >= _MIN_STAGE_B_OCR_BYTES):
            # Risk-triggered deep OCR for low-evidence or overlay-heavy images.
            from src.app.cv.cv_pipeline import run_risk_triggered_multicontrast_ocr
            try:
                deep = await _run_bounded_image_work(
                    _functools.partial(
                        run_risk_triggered_multicontrast_ocr,
                        analysis_content,
                        ocr_provider=None,
                        enabled=True,
                    ),
                    timeout=float(os.getenv("CV_DEEP_OCR_TIMEOUT_S", "6.0") or 6.0),
                )
            except _asyncio.TimeoutError:
                deep = {"best_text": "", "best_confidence": 0.0, "triggered": True,
                        "error": "deep_ocr_timeout"}
                analysis_state["analysis_degraded"] = True
                analysis_state["degraded_reasons"].append("deep_ocr_timeout")
            deep_text = str(deep.get("best_text") or "").strip()
            deep_conf = float(deep.get("best_confidence") or 0.0)
            deep_min_conf = float(os.getenv("CV_STAGE_B_OCR_CONFIDENCE_MIN", "0.45") or 0.45)
            if deep_text:
                extracted_text = deep_text[:500]
                ocr_det = _normalize_ocr_and_detect(extracted_text)
            if bool(deep.get("invisible_text_suspected")):
                security_signals["invisible_text_suspected"] = True
                security_clean = False
            # Stage-B still uncertain: keep visual flow available, but mark untrusted/degraded.
            if (not deep_text) or deep_conf < deep_min_conf:
                analysis_state["analysis_degraded"] = True
                analysis_state["degraded_reasons"].append("ocr_low_confidence")
        elif deep_trigger and not fast:
            # Tiny synthetic or low-information images are not good candidates
            # for expensive OCR rescue. Skip the deep pass and let later
            # identity rescue / security logic operate on the lighter signals.
            analysis_state["analysis_degraded"] = True
            analysis_state["degraded_reasons"].append("ocr_low_confidence")

        if "ocr_low_confidence" in analysis_state["degraded_reasons"]:
            # Backward-compatible observability signal. It does not make the image suspicious.
            security_signals["ocr_low_confidence_uncertain"] = True

        if bool(ocr_det.get("payment_social_engineering")):
            security_signals["payment_social_engineering"] = True
            security_clean = False
        if bool(ocr_det.get("pci_card_exposed")):
            security_signals["pci_card_exposed"] = True
            security_clean = False
        if bool(ocr_det.get("crypto_payment_uri")):
            security_signals["crypto_payment_uri"] = True
            security_clean = False
        if bool(ocr_det.get("ransomware_indicator")):
            security_signals["ransomware_indicator"] = True
            security_clean = False
        if bool(ocr_det.get("encoded_payload_detected")):
            security_signals["encoded_payload_detected"] = True
            security_clean = False
        if bool(ocr_det.get("homoglyph_injection")):
            security_signals["homoglyph_injection"] = True
            security_clean = False
    except Exception:
        pass

    # Product identity rescue for weak/flagged product-like images.
    if not fast and not product_identity:
        try:
            weak_labels = _labels_are_weak(labels)
            flagged = bool(security_signals)
            product_like = _is_product_photo(labels, resp["damage_score"]) or any(
                kw in " ".join(str(x).lower() for x in (labels or []))
                for kw in _PRODUCT_LABEL_KW
            )
            if weak_labels or flagged or product_like:
                from src.app.services.product_identity_agent import (
                    identify_product_from_image,
                    identify_product_from_text,
                )

                hint_text = " ".join(labels or [])
                filename_hint = os.path.splitext(str(name or ""))[0].replace("-", " ").replace("_", " ")
                text_rescue = identify_product_from_text(
                    labels=labels or [],
                    ocr_text="",
                    user_query=filename_hint,
                    trace_id=None,
                )
                if bool(text_rescue.get("identified")) and str(text_rescue.get("brand") or "").strip():
                    product_identity = {
                        "brand": str(text_rescue.get("brand") or "").strip(),
                        "model": str(text_rescue.get("model") or "").strip() or None,
                        "category": str(text_rescue.get("product_type") or "laptop").strip().lower(),
                        "confidence": float(text_rescue.get("confidence") or 0.0),
                        "source": "visual_brand_hint",
                    }

                if not product_identity and not weak_labels:
                    direct_hint_brand = _brand_hint_from_text(hint_text, filename_hint)
                    if direct_hint_brand:
                        product_identity = {
                            "brand": direct_hint_brand.upper() if direct_hint_brand == "msi" else direct_hint_brand.capitalize(),
                            "model": None,
                            "category": "laptop",
                            "confidence": 0.31,
                            "source": "filename_or_label_hint",
                        }

                stage_b_enabled = str(
                    os.getenv("CV_IDENTITY_STAGE_B_ENABLED", "0") or "0"
                ).strip().lower() in ("1", "true", "yes", "on")
                if not product_identity and stage_b_enabled:
                    identity_timeout = float(os.getenv("CV_IDENTITY_STAGE_B_TIMEOUT_S", "6.0") or 6.0)
                    stage_b = await _run_bounded_image_work(
                        _functools.partial(
                            identify_product_from_image,
                            analysis_content,
                            user_query=filename_hint or None,
                            trace_id=None,
                            timeout_s=identity_timeout,
                        ),
                        timeout=identity_timeout + 0.5,
                    )
                    if isinstance(stage_b, dict):
                        brand = str(stage_b.get("brand") or "").strip()
                        if bool(stage_b.get("identified")) and brand:
                            product_identity = {
                                "brand": brand,
                                "model": str(stage_b.get("model") or "").strip() or None,
                                "category": str(stage_b.get("product_type") or "laptop").strip().lower(),
                                "confidence": float(stage_b.get("confidence") or 0.0),
                                "source": "vision_stage_b",
                            }
                elif not product_identity:
                    analysis_state["analysis_degraded"] = True
                    analysis_state["degraded_reasons"].append("identity_unresolved_after_provider")
        except _asyncio.TimeoutError:
            analysis_state["analysis_degraded"] = True
            analysis_state["degraded_reasons"].append("identity_stage_b_timeout")
        except Exception:
            analysis_state["analysis_degraded"] = True
            analysis_state["degraded_reasons"].append("identity_stage_b_error")

    if product_identity:
        resp["product_identity"] = product_identity

    payload_analysis = classify_passive_payload(
        filename=str(name or ""),
        extracted_text=(extracted_text or "")[:500],
        signals=security_signals,
    )
    security_signals = dict(payload_analysis.get("signals_updated") or security_signals)
    canonical_qr = _canonical_qr_assessment(security_signals)
    if canonical_qr:
        resp["qr_assessment"] = canonical_qr
    if payload_analysis.get("attack_hypothesis") not in (None, "", "unknown"):
        if payload_analysis.get("suggested_next_step") != "allow" or security_signals:
            security_clean = False
    payload_findings: list[dict[str, Any]] = []
    hypothesis = str(payload_analysis.get("attack_hypothesis") or "").strip().lower()
    payload_map = {
        "lolbin_command_sequence": {
            "finding_type": "lolbin_command_sequence",
            "headline": "Hidden LOLBin command sequence detected",
            "business_risk": "The image appears to hide commands that abuse trusted operating-system tools to fetch or launch payloads.",
        },
        "c2_beacon": {
            "finding_type": "c2_beacon_pattern",
            "headline": "Hidden C2 beacon pattern detected",
            "business_risk": "The decoded content resembles callback or beacon instructions that should be threat-hunted on network and endpoint telemetry.",
        },
        "data_exfiltration": {
            "finding_type": "data_exfiltration_instruction",
            "headline": "Hidden data-exfiltration instructions detected",
            "business_risk": "The image appears to hide instructions for collecting or moving sensitive data out of the environment.",
        },
        "prompt_injection": {
            "finding_type": "prompt_injection_hidden",
            "headline": "Hidden prompt injection detected",
            "business_risk": "The artifact appears designed to manipulate AI or agent workflows if the content is ingested without sanitization.",
        },
        "pii_data_exfil_via_qr": {
            "finding_type": "ssn_leakage_linked_qr",
            "headline": "Linked QR path suggests SSN or PII leakage",
            "business_risk": "The QR-linked content appears to expose sensitive identity data and should be treated as a privacy incident candidate.",
        },
    }
    mapped = payload_map.get(hypothesis)
    if mapped:
        evidence_lines = list(security_signals.get("steg_explanations") or [])[:3] or [
            str(x) for x in (payload_analysis.get("lolbin_hits") or [])[:3]
        ]
        evidence_refs = _vision_artifact_evidence_refs(
            payload_analysis=payload_analysis,
            security_signals=security_signals,
            linked_artifact=linked_artifact_result,
            extracted_text=extracted_text or "",
        )
        artifact_provenance = _vision_artifact_provenance(
            source_name=str(name or "image"),
            payload_analysis=payload_analysis,
            security_signals=security_signals,
            linked_artifact=linked_artifact_result,
            extracted_text=extracted_text or "",
        )
        suggested_next_step = str(payload_analysis.get("suggested_next_step") or "review").strip().lower() or "review"
        confidence_score = 0.78 if suggested_next_step in {"review", "block"} else 0.62
        payload_findings.append(
            {
                "finding_id": f"vision_{mapped['finding_type']}",
                "finding_type": mapped["finding_type"],
                "headline": mapped["headline"],
                "business_risk": mapped["business_risk"],
                "business_outcome": mapped["business_risk"],
                "summary": mapped["headline"],
                "source_type": "vision_image_payload",
                "evidence_kind": "direct" if str(payload_analysis.get("claim_status") or "") == "observed" else "inferred",
                "confidence_score": confidence_score,
                "ocr_confidence": ocr_meta.get("ocr_confidence"),
                "mitre_attack": payload_analysis.get("mitre_attack") or [],
                "possible_mitre_attack": payload_analysis.get("possible_mitre_attack") or [],
                "mitre_atlas": payload_analysis.get("mitre_atlas") or [],
                "possible_mitre_atlas": payload_analysis.get("possible_mitre_atlas") or [],
                "pasta_stage": payload_analysis.get("pasta_stage"),
                "decode_path": payload_analysis.get("decode_path"),
                "suggested_next_step": suggested_next_step,
                "evidence": evidence_lines,
                "evidence_refs": evidence_refs,
                "artifact_provenance": artifact_provenance,
                "claim_status": payload_analysis.get("claim_status") or "possible",
                "finding_group": payload_analysis.get("finding_group") or "unconfirmed_higher_order_hypotheses",
                "confidence_band": "medium" if suggested_next_step in {"review", "allow"} else "high",
                "evidence_lane": payload_analysis.get("evidence_lane") or "passive_artifact_observation",
                "next_steps": list(payload_analysis.get("runtime_evidence_required") or []),
                "linked_artifact": linked_artifact_result if isinstance(linked_artifact_result, dict) else None,
                "threat_context": {
                    "pasta_stage": payload_analysis.get("pasta_stage"),
                    "mitre_attack": payload_analysis.get("mitre_attack") or [],
                    "possible_mitre_attack": payload_analysis.get("possible_mitre_attack") or [],
                    "mitre_atlas": payload_analysis.get("mitre_atlas") or [],
                    "possible_mitre_atlas": payload_analysis.get("possible_mitre_atlas") or [],
                    "claim_status": payload_analysis.get("claim_status") or "possible",
                    "evidence_lane": payload_analysis.get("evidence_lane") or "passive_artifact_observation",
                    "runtime_confirmation_required": bool(payload_analysis.get("runtime_confirmation_required")),
                    "runtime_evidence_required": list(payload_analysis.get("runtime_evidence_required") or []),
                },
                "drilldown": _vision_payload_drilldown(
                    mapped["finding_type"],
                    payload_analysis=payload_analysis,
                    security_signals=security_signals,
                    linked_artifact=linked_artifact_result,
                ),
            }
        )

    # ── Auto-queue sandbox detonation for high-risk hypotheses ──────────────
    # c2_beacon and lolbin_command_sequence require runtime confirmation;
    # queue a background detonation job when either is detected.
    _sandbox_queue_result: dict = {}
    try:
        from src.app.services.sandbox_queue import queue_sandbox_detonation, should_auto_queue

        if should_auto_queue(hypothesis):
            _steg_decoded = str((security_signals.get("steg_details") or {}).get("decoded_content") or "")
            _qr_urls = [str(u) for u in (security_signals.get("qr_payloads") or []) if str(u).strip()]
            _sandbox_queue_result = queue_sandbox_detonation(
                hypothesis=hypothesis,
                trace_id=str(resp.get("trace_id") or ""),
                tenant_id=None,
                decoded_content=_steg_decoded or None,
                urls=_qr_urls,
                steg_score=float((security_signals.get("steg_details") or {}).get("steg_score") or 0.0),
                source="image_scan",
            )
    except Exception as _sq_exc:
        import logging as _sqlog
        _sqlog.getLogger(__name__).debug("vision: sandbox_queue failed (non-fatal): %s", _sq_exc)

    detected_security_risk = not security_clean
    if detected_security_risk:
        artifact_state = "quarantined"
    elif bool(analysis_state.get("analysis_pending")):
        artifact_state = "pending"
    elif bool(analysis_state.get("analysis_degraded")):
        artifact_state = "degraded"
    else:
        artifact_state = "clean"
    # Incomplete inspection is not a clean verdict. Keep security_risk distinct so
    # a timeout is not mislabeled as a confirmed attack.
    canonical_clean = artifact_state == "clean"
    analysis_state["security_risk"] = detected_security_risk
    analysis_state["artifact_state"] = artifact_state
    analysis_state["degraded_reasons"] = sorted(set(analysis_state["degraded_reasons"]))
    resp["artifact"] = {
        "artifact_id": artifact_id,
        "sha256": artifact_sha256,
        "verdict_version": 1,
        "state": artifact_state,
        "authority": "read_only" if canonical_clean else "blocked",
    }
    _degraded = set(str(x) for x in (analysis_state.get("degraded_reasons") or []))
    def _coverage_status(*, fail: bool = False, prefixes: tuple[str, ...] = (), not_applicable: bool = False) -> str:
        if fail:
            return "fail"
        if not_applicable:
            return "not_applicable"
        matching = [reason for reason in _degraded if any(reason.startswith(prefix) for prefix in prefixes)]
        if any("timeout" in reason for reason in matching):
            return "timeout"
        if matching:
            return "error"
        return "pass"
    inspection_coverage = [
        {"check": "strict_admission", "status": "pass", "authority_effect": "admitted"},
        {"check": "safe_image_decode", "status": "pass", "authority_effect": "decoded"},
        {"check": "vision_provider", "status": _coverage_status(prefixes=("provider_", "managed_cv_", "identity_")), "authority_effect": artifact_state},
        {
            "check": "qr_decode_and_policy",
            "status": "skipped" if fast else _coverage_status(
                fail=bool(security_signals.get("qr_prompt_injection") or security_signals.get("qr_external_url_detected")),
                prefixes=("qr_decode_",),
                not_applicable=not bool(security_signals.get("qr_code_detected")),
            ),
            "authority_effect": "blocked" if bool(security_signals.get("qr_prompt_injection")) else "none",
        },
        {
            "check": "adversarial_image",
            "status": "skipped" if fast else _coverage_status(
                fail=bool(security_signals.get("adversarial_detected")), prefixes=("adversarial_",)
            ),
            "authority_effect": "blocked" if bool(security_signals.get("adversarial_detected")) else "none",
        },
        {
            "check": "steganography",
            "status": "skipped" if fast else _coverage_status(
                fail=bool(security_signals.get("steg_suspicious")), prefixes=("steg_",)
            ),
            "authority_effect": "blocked" if bool(security_signals.get("steg_suspicious")) else "none",
        },
    ]
    try:
        persisted_artifact = _persist_artifact_verdict(
            artifact_id=artifact_id,
            sha256=artifact_sha256,
            state=artifact_state,
            coverage={row["check"]: row["status"] for row in inspection_coverage},
        )
        resp["artifact"].update({
            "verdict_version": persisted_artifact["verdict_version"],
            "state": persisted_artifact["state"],
        })
        # A retry can observe a verdict that advanced after this request began.
        # The durable current version is authoritative; never return a pending
        # security object beside a clean (or quarantined) artifact object.
        artifact_state = str(persisted_artifact["state"])
        canonical_clean = artifact_state == "clean"
        analysis_state["artifact_state"] = artifact_state
        resp["artifact"]["authority"] = "read_only" if canonical_clean else "blocked"
    except Exception:
        analysis_state["analysis_degraded"] = True
        analysis_state["degraded_reasons"].append("artifact_verdict_persistence_error")
        resp["artifact"].update({"state": "degraded", "authority": "blocked"})
        artifact_state = "degraded"
        canonical_clean = False
        analysis_state["artifact_state"] = artifact_state
    resp["security"] = {
        "clean": canonical_clean,
        "artifact_state": artifact_state,
        "commercial_authority": "read_only" if canonical_clean else "blocked",
        "inspection_coverage": inspection_coverage,
        "containment": {
            "model_context": "allowed_sanitized" if canonical_clean else "blocked",
            "memory_write": "blocked" if not canonical_clean else "sanitized_only",
            "commercial_actions": "blocked" if not canonical_clean else "requires_independent_policy_gate",
            "raw_evidence": "retained_by_policy",
        },
        # Plain-English image authenticity verdict for merchant UI
        "verdict": (
            "This image contains security flags — see signals for details."
            if detected_security_risk
            else "Image inspection is incomplete; commercial authority remains blocked."
            if not canonical_clean
            else "Image passed the completed security checks."
        ),
        "signals": security_signals,
        "reupload_needed": detected_security_risk,
        # Surface the OCR/extracted text here so the UI Security Matrix can show it
        "extracted_text": (extracted_text or "")[:500],
        "ocr_confidence": ocr_meta.get("ocr_confidence"),
        "ocr_engine": ocr_meta.get("ocr_engine"),
        "ocr_word_count": ocr_meta.get("ocr_word_count"),
        "cv_extraction_method": ocr_meta.get("cv_extraction_method"),
        "qr_redirect_probe": qr_redirect_probe,
        "analysis_stage": "fast" if fast else "full",
        "deferred_deep_analysis": bool(fast),
        "payload_analysis": payload_analysis,
        "decoded_artifact_available": payload_analysis.get("decoded_artifact_available"),
        "payload_type": payload_analysis.get("payload_type"),
        "attack_hypothesis": payload_analysis.get("attack_hypothesis"),
        "sandbox_detonation_queued": bool(_sandbox_queue_result.get("queued")),
        "sandbox_queue_path": _sandbox_queue_result.get("path"),
        "mitre_attack": payload_analysis.get("mitre_attack") or [],
        "possible_mitre_attack": payload_analysis.get("possible_mitre_attack") or [],
        "mitre_atlas": payload_analysis.get("mitre_atlas") or [],
        "possible_mitre_atlas": payload_analysis.get("possible_mitre_atlas") or [],
        "pasta_stage": payload_analysis.get("pasta_stage"),
        "decode_path": payload_analysis.get("decode_path"),
        "suggested_next_step": payload_analysis.get("suggested_next_step"),
        "claim_status": payload_analysis.get("claim_status") or "suppressed",
        "finding_group": payload_analysis.get("finding_group") or "suppressed_findings",
        "evidence_lane": payload_analysis.get("evidence_lane") or "passive_artifact_signal_only",
        "runtime_confirmation_required": bool(payload_analysis.get("runtime_confirmation_required")),
        "runtime_evidence_required": list(payload_analysis.get("runtime_evidence_required") or []),
        "runtime_evidence_present": list(payload_analysis.get("runtime_evidence_present") or []),
        "lolbin_behavioral_profiles": payload_analysis.get("lolbin_behavioral_profiles") or [],
        "signal_labels": payload_analysis.get("signal_labels") or {},
        "payload_findings": payload_findings,
        "finding_groups": {
            "active_findings": [f for f in payload_findings if str(f.get("finding_group") or "") == "active_findings"],
            "detection_artifact_patterns": [f for f in payload_findings if str(f.get("finding_group") or "") == "detection_artifact_patterns"],
            "unconfirmed_higher_order_hypotheses": [f for f in payload_findings if str(f.get("finding_group") or "") == "unconfirmed_higher_order_hypotheses"],
        },
        "evidence": {
            "source": "vision.triage",
            "evidence_lane": payload_analysis.get("evidence_lane") or "passive_artifact_signal_only",
            "claim_status": payload_analysis.get("claim_status") or "suppressed",
            "payload_hypothesis": payload_analysis.get("attack_hypothesis") or "unknown",
            "ocr_confidence": ocr_meta.get("ocr_confidence"),
            "ocr_engine": ocr_meta.get("ocr_engine"),
            "ocr_word_count": ocr_meta.get("ocr_word_count"),
            "cv_extraction_method": ocr_meta.get("cv_extraction_method"),
            "possible_mitre_attack": payload_analysis.get("possible_mitre_attack") or [],
            "possible_mitre_atlas": payload_analysis.get("possible_mitre_atlas") or [],
            "runtime_confirmation_required": bool(payload_analysis.get("runtime_confirmation_required")),
            "runtime_evidence_required": list(payload_analysis.get("runtime_evidence_required") or []),
            "runtime_evidence_present": list(payload_analysis.get("runtime_evidence_present") or []),
            "artifact_provenance": _vision_artifact_provenance(
                source_name=str(name or "image"),
                payload_analysis=payload_analysis,
                security_signals=security_signals,
                linked_artifact=linked_artifact_result,
                extracted_text=extracted_text or "",
            ),
            "active_findings": [f for f in payload_findings if str(f.get("finding_group") or "") == "active_findings"],
            "detection_artifact_patterns": [f for f in payload_findings if str(f.get("finding_group") or "") == "detection_artifact_patterns"],
            "unconfirmed_higher_order_hypotheses": [f for f in payload_findings if str(f.get("finding_group") or "") == "unconfirmed_higher_order_hypotheses"],
        },
    }
    evidence_snapshot = {
        "sender_infrastructure": {
            "originating_geo": {
                "country": ((linked_artifact_result or {}).get("country") if isinstance(linked_artifact_result, dict) else None),
                "asn_org": ((linked_artifact_result or {}).get("asn_org") if isinstance(linked_artifact_result, dict) else None),
            },
            "reputation": {
                "flags": list((qr_redirect_probe or {}).get("risk_flags") or []),
            },
            "related_incidents": {
                "count": int((linked_artifact_result or {}).get("related_incident_count") or 0) if isinstance(linked_artifact_result, dict) else 0,
            },
        }
    }
    try:
        resp["security"]["threat_hunter_leads"] = build_threat_hunter_leads(
            findings=payload_findings,
            evidence_snapshot=evidence_snapshot,
            llm_assist={},
        )
    except Exception:
        resp["security"]["threat_hunter_leads"] = []
    if not resp["security"]["threat_hunter_leads"] and payload_findings:
        fallback_leads = []
        for idx, finding in enumerate(payload_findings[:3]):
            next_steps = [str(x) for x in (finding.get("next_steps") or []) if str(x).strip()]
            evidence_lines = [str(x) for x in (finding.get("evidence") or []) if str(x).strip()]
            fallback_leads.append(
                {
                    "lead_id": f"fallback_{idx}",
                    "finding_type": str(finding.get("finding_type") or "artifact_hunt"),
                    "title": f"Threat Hunter Lead: {str(finding.get('headline') or finding.get('summary') or 'Investigate artifact behavior')}",
                    "what_we_observed": evidence_lines[:3] or [str(finding.get("business_risk") or "Suspicious artifact behavior detected.")],
                    "why_it_matters": str(finding.get("business_risk") or "This artifact warrants targeted hunting before broader action."),
                    "what_to_hunt_next": next_steps[:4] or ["Correlate this artifact with endpoint, identity, and network telemetry before containment."],
                    "where_to_check": ["XDR / EDR", "DNS / proxy logs", "Email / browser telemetry"],
                    "confirmation_signals": list((finding.get("threat_context") or {}).get("runtime_evidence_required") or []),
                    "disproving_signals": ["No supporting endpoint or network evidence tied to the same host, user, or session."],
                    "push_downstream": ["Human review before autonomous containment"],
                    "likely_kill_chain_stage": str((finding.get("threat_context") or {}).get("pasta_stage") or finding.get("pasta_stage") or "Review"),
                    "confidence_score": float(finding.get("confidence_score") or 0.62),
                    "confidence_band": str(finding.get("confidence_band") or "medium"),
                    "analyst_guidance": "Treat this as an evidence-led lead. Confirm runtime telemetry before promoting it to an active incident.",
                    "business_guidance": "Use the plain-English summary and next steps to brief a human reviewer before any blocking action.",
                    "evidence_refs": [str(x) for x in (finding.get("evidence_refs") or []) if str(x).strip()],
                    "target_checklists": {},
                }
            )
        resp["security"]["threat_hunter_leads"] = fallback_leads
    if artifact_state != "clean":
        normalized_event = build_normalized_security_event(
            source="vision_artifact_inspection",
            tenant_id=current_tenant_id(),
            decision_id=None,
            trace_id=artifact_id,
            message_id_hash=artifact_sha256,
            severity="high" if artifact_state == "quarantined" else "medium",
            verdict_action="block_commercial_authority",
            route="security_review",
            escalation="human_security_review",
            reasons=sorted({
                artifact_state,
                *[str(row.get("check")) for row in inspection_coverage if row.get("status") in {"fail", "timeout", "error"}],
            }),
            tags=["artifact_upload", str(payload_analysis.get("attack_hypothesis") or "unknown")],
            ioc_counts={"payload_findings": len(payload_findings)},
            risk_band="high" if artifact_state == "quarantined" else "medium",
            playbook_id="artifact_security_review",
            ticket_id=None,
            evidence={
                "artifact_id": artifact_id,
                "artifact_sha256": artifact_sha256,
                "verdict_version": resp["artifact"].get("verdict_version"),
                "inspection_coverage": inspection_coverage,
            },
        )
        resp["security"]["siem_handoff"] = {
            "event": normalized_event,
            "status": emit_security_handoff(normalized_event),
        }
    faq_query_parts = [
        str(name or ""),
        str(extracted_text or ""),
        str(payload_analysis.get("attack_hypothesis") or ""),
        " ".join(str(x) for x in (labels or []) if str(x).strip()),
    ]
    if float(security_signals.get("damage_score") or 0.0) >= 0.4:
        faq_query_parts.append("repair cracked screen damage")
    if "blue screen" in str(extracted_text or "").lower() or "bsod" in str(name or "").lower():
        faq_query_parts.append("blue screen bsod windows repair")
    try:
        faq_match, faq_score = match_faq(" ".join(part for part in faq_query_parts if part).strip())
        if faq_match and float(faq_score or 0.0) > 0:
            resp["faq_playbooks"] = [
                {
                    "id": str(faq_match.get("q") or "faq_playbook").lower().replace(" ", "_"),
                    "title": str(faq_match.get("q") or "Recommended support playbook"),
                    "description": str(faq_match.get("a") or "").strip(),
                    "steps": [str(faq_match.get("a") or "").strip()],
                    "tags": list(faq_match.get("tags") or []),
                }
            ]
    except Exception:
        pass
    # Attach productive QR data (manufacturer URLs, model hints) for downstream identity extraction
    if qr_product_data:
        resp["qr_product_data"] = qr_product_data
    if detected_security_risk:
        resp["security_message"] = (
            "For your security, we detected potentially unsafe content in this image. "
            "Please upload a new, unedited photo without QR codes or overlays."
        )

    try:
        ensure_event_log_table()
        ev_id = str(uuid.uuid4())
        payload = json.dumps(resp, ensure_ascii=False)

        with db_session() as db:
            db.execute(
                "INSERT INTO event_log (id, type, payload, status) VALUES (:id, :type, :payload, 'pending')",
                {"id": ev_id, "type": "vision.triage", "payload": payload},
            )
            try:
                db.commit()
            except Exception:
                pass
        resp["event_id"] = ev_id
    except Exception:
        pass

    if not fast and provider_name == "ollama":
        try:
            from src.app.services.model_residency import schedule_router_restore

            resp["router_restore_scheduled"] = schedule_router_restore()
        except Exception:
            resp["router_restore_scheduled"] = False

    return resp
