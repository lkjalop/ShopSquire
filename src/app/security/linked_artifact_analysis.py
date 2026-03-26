from __future__ import annotations

import hashlib
import datetime as dt
import json
import os
import re
import socket
import ssl
from html import unescape
from typing import Any, Dict, List
from urllib.parse import urljoin, urlparse
import ipaddress

from src.app.security.email_attachment_parser import _bank_fingerprint, _extract_bank_fields, _extract_pdf_text, _extract_text, _ocr_pdf_pages, _pdf_forensics
from src.app.security.safe_requests import safe_request
from src.app.security.supplier_governance_store import get_supplier_governance_profile


_URL_PAT = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)
_HTML_HREF_PAT = re.compile(r"""(?:href|src)\s*=\s*["']([^"'#>]+)["']""", re.IGNORECASE)
_META_REFRESH_PAT = re.compile(r"""url\s*=\s*['"]?([^'";>\s]+)""", re.IGNORECASE)
_SSN_PAT = re.compile(
    r"\b(\d{3}[-. ]\d{2}[-. ]\d{4})\b"                               # XXX-XX-XXXX, XXX.XX.XXXX, XXX XX XXXX
    r"|\bSSN[\s:#]*([2-9]\d{2}[1-9]\d[1-9]\d{4})\b"                   # SSN: XXXXXXXXX
    r"|\bSocial\s+Security(?:\s+Number)?[\s:#]*(\d{3}[-. ]?\d{2}[-. ]?\d{4})\b",  # Social Security Number: XXX...
    re.IGNORECASE,
)
# Secondary bare 9-digit match (valid SSN range heuristics: area 001-899 excl 666, group/serial nonzero)
_SSN_BARE_PAT = re.compile(r"\b([2-8]\d{2}(?!00)\d{2}(?!0000)\d{4})\b")
_SSN_GLUE_PAT = re.compile(
    r"\b([2-8]\d{2}[-. ]\d{2}[-. ]\d{4})(?=\d?[/.-]\d{1,2}[/.-]\d{2,4}\b)",
    re.IGNORECASE,
)
_CC_PAT = re.compile(r"\b(?:\d[ -]?){13,19}\b")
_DOB_PAT = re.compile(r"\bdate\s+of\s+birth\b", re.IGNORECASE)
_LURE_PATTERNS = [
    re.compile(r"\bpay(?:ment)?\b", re.IGNORECASE),
    re.compile(r"\binvoice\b", re.IGNORECASE),
    re.compile(r"\bwire\b", re.IGNORECASE),
    re.compile(r"\burgent\b", re.IGNORECASE),
    re.compile(r"\bremit(?:tance)?\b", re.IGNORECASE),
]
_SCRIPT_PATTERNS = [
    re.compile(r"/JavaScript|/JS|OpenAction", re.IGNORECASE),
    re.compile(r"<script\b", re.IGNORECASE),
    re.compile(r"\b(?:mshta|powershell|rundll32|regsvr32|certutil)\b", re.IGNORECASE),
]
_ARCHIVE_EXTS = (".zip", ".rar", ".7z", ".iso")
_MACRO_EXTS = (".docm", ".xlsm", ".pptm")
_ARTIFACT_EXTS = (".pdf", ".csv", ".txt", ".zip", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx")
_PDF_INTERNAL_MARKERS = (
    "endobj",
    "stream",
    "startxref",
    "xref",
    "catalog",
    "mediaBox".lower(),
    "fontdescriptor",
    "cidfont",
    "flatedecode",
    "fontfile",
)
_SUSPICIOUS_DOMAIN_TOKENS = ("verify", "payment", "invoice", "remit", "billing", "update", "bank")
_LOOKALIKE_PATTERNS = (("rn", "m"), ("0", "o"), ("1", "l"), ("vv", "w"), ("cl", "d"))
_PAYMENT_RAIL_DOMAINS = {
    "stripe.com",
    "paypal.com",
    "squareup.com",
    "payoneer.com",
    "wise.com",
    "bill.com",
}


_SCANNED_PAGE_PATH_PREFIXES = {"p", "r", "s", "qr"}


def _internal_domain_hints() -> List[str]:
    raw = str(os.getenv("LINKED_ARTIFACT_INTERNAL_DOMAINS") or "").strip()
    hints = [part.strip().lower() for part in raw.split(",") if part.strip()]
    hints.extend(["shopsquire", "localhost"])
    seen: set[str] = set()
    return [hint for hint in hints if hint and not (hint in seen or seen.add(hint))]


def _classify_linked_owner_scope(*, raw_url: str, final_url: str, pii_detected: bool) -> Dict[str, Any]:
    candidate = str(final_url or raw_url or "").strip()
    host = str(urlparse(candidate).hostname or "").strip().lower()
    owner_scope = "unknown"
    owner_reason = "No destination host was available for privacy ownership assessment."
    if host:
        internal_hints = _internal_domain_hints()
        try:
            ip = ipaddress.ip_address(host)
            if ip.is_private or ip.is_loopback:
                owner_scope = "likely_internal_platform"
                owner_reason = "The linked destination resolves to a private or loopback address."
            else:
                owner_scope = "external_or_third_party"
                owner_reason = "The linked destination resolves to a public IP address."
        except ValueError:
            if any(host == hint or host.endswith(f".{hint}") or hint in host for hint in internal_hints):
                owner_scope = "likely_internal_platform"
                owner_reason = "The linked destination matches an internal or platform-owned domain hint."
            elif host.endswith((".internal", ".corp", ".local")):
                owner_scope = "likely_internal_platform"
                owner_reason = "The linked destination uses an internal-only naming pattern."
            elif host in {"scanned.page", "www.scanned.page", "qr.scanned.page"}:
                owner_scope = "external_redirect_service"
                owner_reason = "The QR destination is a public redirect service; the underlying document owner still needs human verification."
            else:
                owner_scope = "external_or_third_party"
                owner_reason = "The linked destination appears to be publicly hosted outside platform-owned domain hints."

    exposure_scope = "unknown"
    severity_hint = "medium"
    if pii_detected:
        if owner_scope == "likely_internal_platform":
            exposure_scope = "potential_internal_or_customer_pii"
            severity_hint = "critical"
        elif owner_scope == "external_or_third_party":
            exposure_scope = "potential_external_or_third_party_pii"
            severity_hint = "high"
        elif owner_scope == "external_redirect_service":
            exposure_scope = "redirect_service_to_unknown_owner"
            severity_hint = "high"
        else:
            exposure_scope = "regulated_data_owner_unknown"
            severity_hint = "high"

    return {
        "linked_host": host or None,
        "linked_owner_scope": owner_scope,
        "linked_owner_reason": owner_reason,
        "linked_exposure_scope": exposure_scope,
        "linked_breach_severity_hint": severity_hint,
        "linked_human_verification_required": bool(pii_detected),
        "linked_crisis_management_required": bool(pii_detected),
    }


def _load_offline_fixture_map() -> Dict[str, Any]:
    path = os.path.join("config", "security", "linked_artifact_offline_fixtures.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _offline_fixture_for_url(source_url: str) -> Dict[str, Any] | None:
    data = _load_offline_fixture_map()
    entries = data.get("entries") if isinstance(data.get("entries"), list) else []
    clean = str(source_url or "").strip()
    if not clean:
        return None
    for row in entries:
        if not isinstance(row, dict):
            continue
        urls = [str(x).strip() for x in (row.get("urls") or []) if str(x).strip()]
        if clean not in urls:
            continue
        rel = str(row.get("local_path") or "").strip()
        if not rel:
            continue
        abs_path = os.path.abspath(rel)
        if not os.path.isfile(abs_path):
            continue
        return {
            "local_path": abs_path,
            "content_type": str(row.get("content_type") or "").strip().lower(),
            "filename": str(row.get("filename") or os.path.basename(abs_path)).strip(),
            "tag": str(row.get("tag") or "").strip(),
        }
    return None


def _normalize_host_lookalikes(host: str) -> str:
    lowered = str(host or "").strip().lower()
    for old, new in _LOOKALIKE_PATTERNS:
        lowered = lowered.replace(old, new)
    return lowered


def _host_category(host: str) -> str:
    lowered = str(host or "").strip().lower()
    if not lowered:
        return "unknown"
    if lowered in {"scanned.page", "www.scanned.page", "qr.scanned.page"}:
        return "redirect_service"
    if any(tok in lowered for tok in ("verify", "payment", "billing", "invoice", "remit")):
        return "payment_or_verification_host"
    if lowered.endswith((".internal", ".corp", ".local")):
        return "internal_only"
    return "public_host"


def _approved_payment_rail_domains() -> List[str]:
    raw = str(os.getenv("LINKED_ARTIFACT_APPROVED_PAYMENT_DOMAINS") or "").strip()
    parts = [part.strip().lower() for part in raw.split(",") if part.strip()]
    merged = list(dict.fromkeys([*sorted(_PAYMENT_RAIL_DOMAINS), *parts]))
    return merged[:64]


def _host_matches_any(host: str, candidates: List[str]) -> bool:
    lowered = str(host or "").strip().lower()
    if not lowered:
        return False
    for candidate in candidates:
        item = str(candidate or "").strip().lower()
        if not item:
            continue
        if lowered == item or lowered.endswith(f".{item}"):
            return True
    return False


def _best_effort_domain_registration_intel(*, host: str, timeout: float) -> Dict[str, Any]:
    lowered = str(host or "").strip().lower()
    out: Dict[str, Any] = {
        "domain_registration_available": False,
        "domain_age_days": None,
        "registration_created_at": None,
        "registration_source": None,
    }
    if not lowered:
        return out
    try:
        ip = ipaddress.ip_address(lowered)
        if ip.is_private or ip.is_loopback:
            out["registration_error"] = "non_public_host"
            return out
    except ValueError:
        pass
    if lowered.endswith((".internal", ".corp", ".local")) or lowered in {"localhost"}:
        out["registration_error"] = "non_public_host"
        return out
    try:
        resp = safe_request("GET", f"https://rdap.org/domain/{lowered}", timeout=min(max(float(timeout), 2.0), 6.0), allow_redirects=True)
        if int(getattr(resp, "status_code", 0) or 0) >= 400:
            out["registration_error"] = f"http_{int(resp.status_code)}"
            return out
        data = resp.json() if hasattr(resp, "json") else {}
        events = data.get("events") if isinstance(data, dict) else []
        created_raw = None
        for event in events or []:
            if not isinstance(event, dict):
                continue
            action = str(event.get("eventAction") or "").strip().lower()
            if action in {"registration", "registered"}:
                created_raw = str(event.get("eventDate") or "").strip()
                break
        if not created_raw:
            out["registration_error"] = "rdap_missing_registration"
            return out
        normalized = created_raw.replace("Z", "+00:00")
        created_at = dt.datetime.fromisoformat(normalized)
        now = dt.datetime.now(dt.timezone.utc)
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=dt.timezone.utc)
        age_days = max(0, int((now - created_at.astimezone(dt.timezone.utc)).days))
        out.update(
            {
                "domain_registration_available": True,
                "domain_age_days": age_days,
                "registration_created_at": created_at.astimezone(dt.timezone.utc).isoformat(),
                "registration_source": "rdap.org",
            }
        )
    except Exception as exc:
        out["registration_error"] = str(exc)[:180]
    return out


def _best_effort_host_enrichment(*, raw_url: str, timeout: float) -> Dict[str, Any]:
    parsed = urlparse(str(raw_url or "").strip())
    host = str(parsed.hostname or "").strip().lower()
    scheme = str(parsed.scheme or "").strip().lower()
    out: Dict[str, Any] = {
        "host": host or None,
        "scheme": scheme or None,
        "host_category": _host_category(host),
        "dns_resolved": False,
        "resolved_ips": [],
        "tls_observed": False,
        "tls_sha256": None,
        "tls_subject": None,
        "content_type_validated": False,
    }
    if not host:
        return out
    out.update(_best_effort_domain_registration_intel(host=host, timeout=timeout))
    try:
        infos = socket.getaddrinfo(host, 443 if scheme == "https" else 80, proto=socket.IPPROTO_TCP)
        ips = []
        for info in infos:
            try:
                ip = str(info[4][0] or "").strip()
            except Exception:
                ip = ""
            if ip and ip not in ips:
                ips.append(ip)
        out["resolved_ips"] = ips[:8]
        out["dns_resolved"] = bool(ips)
    except Exception as exc:
        out["dns_error"] = str(exc)[:180]
        return out

    if scheme == "https" and out["dns_resolved"]:
        try:
            ctx = ssl.create_default_context()
            with socket.create_connection((host, 443), timeout=max(1.0, float(timeout))) as sock:
                with ctx.wrap_socket(sock, server_hostname=host) as ssock:
                    cert_bin = ssock.getpeercert(binary_form=True)
                    cert = ssock.getpeercert()
                    out["tls_observed"] = True
                    out["tls_sha256"] = hashlib.sha256(cert_bin or b"").hexdigest() if cert_bin else None
                    subject = cert.get("subject") or []
                    parts: List[str] = []
                    for row in subject:
                        for k, v in row:
                            if k and v:
                                parts.append(f"{k}={v}")
                    out["tls_subject"] = ", ".join(parts[:6]) if parts else None
        except Exception as exc:
            out["tls_error"] = str(exc)[:180]
    return out


def _supplier_and_payment_verification(
    *,
    tenant_id: str | None,
    supplier_key: str | None,
    vendor_domain: str | None,
    destination_host: str,
    linked_bank_fingerprint: str | None,
    known_bank_fingerprint: str | None,
) -> Dict[str, Any]:
    supplier = str(supplier_key or vendor_domain or "").strip().lower()
    profile = get_supplier_governance_profile(tenant_id=tenant_id, supplier_key=supplier) if supplier else {}
    approved_domains = [str(x).strip().lower() for x in (profile.get("approved_domains") or []) if str(x).strip()]
    approved_bank_fps = [str(x).strip().lower() for x in (profile.get("approved_bank_fingerprints") or []) if str(x).strip()]
    observed_domains = [str(x).strip().lower() for x in (profile.get("observed_domains") or []) if str(x).strip()]
    approved_rails = _approved_payment_rail_domains()
    bank_fp = str(linked_bank_fingerprint or "").strip().lower()
    baseline_bank_fp = str(known_bank_fingerprint or "").strip().lower()
    domain_match = _host_matches_any(destination_host, approved_domains)
    payment_rail_match = _host_matches_any(destination_host, approved_rails)
    bank_match = bool(bank_fp and baseline_bank_fp and bank_fp == baseline_bank_fp)
    governance_bank_match = bool(bank_fp and bank_fp in approved_bank_fps)
    verification_status = "unverified"
    if domain_match and (bank_match or governance_bank_match or not bank_fp):
        verification_status = "verified_supplier_destination"
    elif payment_rail_match:
        verification_status = "approved_payment_rail"
    elif destination_host and approved_domains:
        verification_status = "supplier_domain_mismatch"
    return {
        "supplier_key": supplier or None,
        "supplier_governance_found": bool(profile),
        "vendor_domain": str(vendor_domain or "").strip().lower() or None,
        "approved_supplier_domain": domain_match,
        "observed_supplier_domain": _host_matches_any(destination_host, observed_domains),
        "approved_payment_rail": payment_rail_match,
        "approved_payment_rail_domains": approved_rails[:12],
        "bank_fingerprint_present": bool(bank_fp),
        "bank_fingerprint_matches_vendor": bank_match,
        "bank_fingerprint_matches_governance": governance_bank_match,
        "verification_status": verification_status,
        "governance_state": profile.get("governance_state") if isinstance(profile, dict) else None,
        "pending_updates": list(profile.get("pending_updates") or [])[:8] if isinstance(profile, dict) else [],
    }


def _normalize_fetch_metric_reason(reason: str | None) -> str:
    raw = str(reason or "").strip().lower()
    if not raw:
        return "linked_artifact_empty"
    if raw.startswith("http_"):
        return raw
    if raw.startswith("linked_fetch_failed:"):
        return "linked_fetch_failed"
    if "too_large" in raw:
        return "linked_artifact_too_large"
    if "empty" in raw:
        return "linked_artifact_empty"
    return re.sub(r"[^a-z0-9_]+", "_", raw)[:64] or "unknown"


def _link_confidence_and_state(
    *,
    artifact_available: bool,
    attack_hypothesis: str,
    pii_types: List[str],
    ssn_hits: List[str],
    suggested_next_step: str,
    fetch_error: str | None,
    host_enrichment: Dict[str, Any],
    content_type: str,
    supplier_verification: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    score = 0.18
    reasons: List[str] = []
    if artifact_available:
        score += 0.18
        reasons.append("artifact_fetched")
    if str(host_enrichment.get("dns_resolved") or "").lower() == "true" or host_enrichment.get("dns_resolved") is True:
        score += 0.08
        reasons.append("dns_resolved")
    if host_enrichment.get("tls_observed"):
        score += 0.08
        reasons.append("tls_observed")
    domain_age_days = host_enrichment.get("domain_age_days")
    if isinstance(domain_age_days, int) and domain_age_days >= 0:
        if domain_age_days < 45:
            score += 0.12
            reasons.append("newly_registered_domain")
        elif domain_age_days > 365:
            score += 0.04
            reasons.append("established_domain")
    if ssn_hits:
        score += 0.36
        reasons.append("regulated_identity_hits")
    elif pii_types:
        score += 0.28
        reasons.append("regulated_data_hits")
    if attack_hypothesis == "linked_payment_fraud":
        score += 0.24
        reasons.append("payment_lure_evidence")
    elif attack_hypothesis == "linked_active_document":
        score += 0.3
        reasons.append("active_document_signal")
    elif attack_hypothesis.startswith("linked_"):
        score += 0.14
        reasons.append("artifact_signal_present")
    if suggested_next_step == "queue_sandbox_detonation":
        score += 0.12
        reasons.append("sandbox_required")
    if fetch_error and not artifact_available:
        score += 0.06
        reasons.append("unresolved_destination")
    if content_type and ("html" in content_type or "pdf" in content_type):
        score += 0.05
        reasons.append("validated_content_type")
    if isinstance(supplier_verification, dict):
        if supplier_verification.get("approved_supplier_domain"):
            score += 0.12
            reasons.append("trusted_supplier_domain")
        elif supplier_verification.get("approved_payment_rail"):
            score += 0.08
            reasons.append("approved_payment_rail")
        elif supplier_verification.get("verification_status") == "supplier_domain_mismatch":
            score += 0.08
            reasons.append("supplier_domain_mismatch")
        if supplier_verification.get("bank_fingerprint_matches_vendor") or supplier_verification.get("bank_fingerprint_matches_governance"):
            score += 0.12
            reasons.append("trusted_bank_fingerprint")
        elif supplier_verification.get("bank_fingerprint_present"):
            score += 0.08
            reasons.append("unverified_bank_fingerprint")
    score = max(0.0, min(0.99, score))
    if score >= 0.86:
        band = "high"
    elif score >= 0.62:
        band = "medium"
    else:
        band = "low"

    verdict_state = "Needs Review"
    verdict_label = "Needs Review"
    if ssn_hits or "pci" in pii_types:
        verdict_state = "Blocked"
        verdict_label = "Blocked"
    elif isinstance(supplier_verification, dict) and supplier_verification.get("approved_supplier_domain") and (
        supplier_verification.get("bank_fingerprint_matches_vendor")
        or supplier_verification.get("bank_fingerprint_matches_governance")
        or not supplier_verification.get("bank_fingerprint_present")
    ):
        verdict_state = "Verified"
        verdict_label = "Verified"
    elif not artifact_available and attack_hypothesis in {"linked_payment_fraud", "unknown_remote_artifact"}:
        verdict_state = "Unverified Destination"
        verdict_label = "Unverified Destination"
    elif artifact_available and attack_hypothesis == "unknown_remote_artifact" and not pii_types:
        verdict_state = "Verified"
        verdict_label = "Verified"

    return {
        "linked_confidence_score": round(score, 3),
        "linked_confidence_band": band,
        "linked_confidence_reasons": reasons[:8],
        "linked_verdict_state": verdict_state,
        "linked_verdict_label": verdict_label,
    }


def _user_facing_evidence_summary(
    *,
    attack_hypothesis: str,
    artifact_available: bool,
    reason_summary: str,
    policy_action: str,
    final_url: str,
    pii_types: List[str],
    ssn_hits: List[str],
    confidence_band: str,
    verdict_label: str,
    supplier_verification: Dict[str, Any] | None = None,
) -> Dict[str, str]:
    host = str(urlparse(final_url).hostname or "").strip().lower()
    what_we_saw = "We analyzed the linked destination."
    why_it_matters = "This destination should be reviewed before anyone acts on it."
    what_happens_next = "The case remains in review until the destination is verified."

    if verdict_label == "Blocked":
        what_we_saw = "We found regulated or payment-sensitive data in the linked destination."
        why_it_matters = "Exposed identity or payment data creates immediate privacy and fraud risk."
        what_happens_next = "Processing is paused and this case should stay blocked until security review is complete."
    elif verdict_label == "Unverified Destination":
        what_we_saw = f"We detected a link to an unverified destination{f' on {host}' if host else ''}."
        why_it_matters = "Unresolved or unverifiable payment destinations are a common fraud pattern."
        what_happens_next = "We paused this flow until the destination can be verified or safely analyzed."
    elif attack_hypothesis == "linked_payment_fraud":
        what_we_saw = f"This invoice links to a payment verification page{f' on {host}' if host else ''}."
        why_it_matters = "Payment-verification links can redirect users away from trusted payment rails."
        what_happens_next = "This case should stay in review before any payment or remittance action is approved."
    elif artifact_available and attack_hypothesis == "unknown_remote_artifact":
        what_we_saw = "The linked destination was fetched and no strong malicious indicators were confirmed."
        why_it_matters = "This lowers the risk of a false positive while preserving an audit trail."
        what_happens_next = "The destination can remain verified unless new evidence appears."

    if isinstance(supplier_verification, dict):
        if supplier_verification.get("approved_supplier_domain"):
            what_we_saw = "The linked destination matches a supplier domain already approved in governance."
            why_it_matters = "This aligns with your trusted supplier baseline and reduces payment-diversion risk."
            what_happens_next = "The destination can stay verified unless other evidence changes the case."
        elif supplier_verification.get("approved_payment_rail"):
            why_it_matters = "The destination uses an approved payment rail, but it still needs document-level validation."
        elif supplier_verification.get("verification_status") == "supplier_domain_mismatch":
            why_it_matters = "The destination does not match the supplier domains already approved in governance."
            what_happens_next = "Keep the case in review until the destination or payment details are independently confirmed."

    if pii_types and verdict_label != "Blocked":
        what_we_saw = f"We found regulated data indicators: {', '.join(pii_types[:3])}."
    if ssn_hits and verdict_label != "Blocked":
        what_we_saw = f"We found SSN-like data in the linked destination ({len(ssn_hits)} hit{'s' if len(ssn_hits) != 1 else ''})."
    if reason_summary:
        why_it_matters = reason_summary
    if policy_action == "sandbox":
        what_happens_next = "The linked content should only be opened in sandbox before any further action."

    return {
        "what_we_saw": what_we_saw,
        "why_it_matters": why_it_matters,
        "what_happens_next": what_happens_next,
        "confidence": confidence_band,
        "verdict": verdict_label,
    }


def _fallback_url_only_assessment(*, raw_url: str, fetch_error: str | None = None) -> Dict[str, Any]:
    parsed = urlparse(raw_url)
    host = str(parsed.hostname or "").strip().lower()
    path = str(parsed.path or "").strip().lower()
    query = str(parsed.query or "").strip().lower()
    host_norm = _normalize_host_lookalikes(host)
    host_tokens = [part for part in re.split(r"[^a-z0-9]+", host_norm) if part]
    suspicious_tokens = [tok for tok in _SUSPICIOUS_DOMAIN_TOKENS if tok in path or tok in query or tok in host_tokens]
    looks_like_verify_subdomain = any(tok in host_tokens for tok in ("verify", "payments", "payment")) and any(tok in suspicious_tokens for tok in ("invoice", "payment", "verify"))
    payment_lure = bool(suspicious_tokens) and any(tok in suspicious_tokens for tok in ("payment", "invoice", "remit", "bank"))
    linked_reason_summary = "Linked URL could not be fetched and needs analyst review."
    linked_policy_action = "review"
    attack_hypothesis = "unknown_remote_artifact"
    suggested_next_step = "review"
    if payment_lure or looks_like_verify_subdomain:
        attack_hypothesis = "linked_payment_fraud"
        linked_reason_summary = "Linked URL could not be fetched, but the destination pattern looks like a payment-verification lure."
        linked_policy_action = "review"
    if host and host != host_norm:
        attack_hypothesis = "linked_payment_fraud"
        linked_reason_summary = "Linked URL could not be fetched and the destination hostname appears lookalike or typo-squatted."
        linked_policy_action = "review"
    out = {
        "linked_artifact_available": False,
        "linked_artifact_type": "url_only_unresolved",
        "linked_content_type": None,
        "linked_filename": None,
        "linked_sha256": None,
        "linked_attack_hypothesis": attack_hypothesis,
        "linked_decode_path": "safe_passive_url_only_assessment",
        "linked_suggested_next_step": suggested_next_step,
        "pii_detected": False,
        "pii_type": [],
        "ssn_hits": [],
        "embedded_urls": [raw_url] if raw_url else [],
        "linked_text_excerpt": "",
        "linked_pdf_has_javascript": False,
        "linked_redirect_chain": [raw_url] if raw_url else [],
        "linked_ocr_used": False,
        "linked_final_url": raw_url,
        "linked_reason_summary": linked_reason_summary,
        "linked_policy_action": linked_policy_action,
        "error": fetch_error or "linked_artifact_empty",
        "linked_url_only_risk_tokens": suspicious_tokens[:8],
    }
    out.update(
        _classify_linked_owner_scope(
            raw_url=raw_url,
            final_url=raw_url,
            pii_detected=False,
        )
    )
    return out


def _provider_candidate_urls(*, source_url: str) -> List[str]:
    """Best-effort provider-specific URL expansion for QR landing pages.

    Some QR SaaS providers serve a SPA shell at the public landing URL and keep
    the actual payload behind a JSON API. When we know the provider shape, fetch
    that metadata passively and surface the real linked artifact instead of
    stopping at index.html.
    """
    parsed = urlparse(source_url)
    host = str(parsed.netloc or "").lower()
    path = str(parsed.path or "").strip("/")
    if host not in {"scanned.page", "www.scanned.page", "qr.scanned.page"}:
        return []

    parts = [p for p in path.split("/") if p]
    if len(parts) < 2 or parts[0] not in _SCANNED_PAGE_PATH_PREFIXES:
        return []
    uid = parts[1].strip()
    if not uid:
        return []

    api_candidates = [
        f"{parsed.scheme or 'https'}://{host}/api/qr-code?uId={uid}",
        f"{parsed.scheme or 'https'}://{host}/api/scan/{uid}",
        f"{parsed.scheme or 'https'}://{host}/api/v1/qr/{uid}",
    ]
    data: Any = {}
    for api_url in api_candidates:
        try:
            resp = safe_request("GET", api_url, timeout=6.0, allow_redirects=True)
            if int(getattr(resp, "status_code", 0) or 0) < 400:
                data = resp.json() if hasattr(resp, "json") else {}
                if isinstance(data, dict) and data:
                    break
        except Exception:
            continue

    if not isinstance(data, dict):
        return []
    # Support both {data: {...}} and flat response shapes
    payload: Dict[str, Any] = (data.get("data") if isinstance(data.get("data"), dict) else None) or data
    candidates: List[str] = []
    for key in ("pdf", "pdfUrl", "documentUrl", "fileUrl", "website", "url", "file", "pdfThumbnail"):
        value = str(payload.get(key) or "").strip()
        if value.startswith(("http://", "https://")):
            candidates.append(value)
    # Also check nested 'content' dict
    if isinstance(payload.get("content"), dict):
        for key in ("pdf", "url", "fileUrl", "documentUrl"):
            value = str(payload["content"].get(key) or "").strip()
            if value.startswith(("http://", "https://")):
                candidates.append(value)
    return candidates


def _guess_artifact_type(content_type: str, filename: str, blob: bytes) -> str:
    ctype = str(content_type or "").lower()
    name = str(filename or "").lower()
    if "pdf" in ctype or name.endswith(".pdf") or blob.startswith(b"%PDF"):
        return "pdf"
    if "csv" in ctype or name.endswith(".csv"):
        return "csv"
    if "spreadsheet" in ctype or name.endswith((".xlsx", ".xlsm", ".xls")):
        return "xlsx"
    if "zip" in ctype or name.endswith(".zip") or blob.startswith(b"PK\x03\x04"):
        return "zip"
    if "html" in ctype or name.endswith((".html", ".htm")):
        return "html"
    if name.endswith(_MACRO_EXTS):
        return "office_macro_candidate"
    if name.endswith(_ARCHIVE_EXTS):
        return "archive"
    return "unknown"


def _content_disposition_filename(resp_headers: Dict[str, Any]) -> str:
    raw = str(resp_headers.get("content-disposition") or "")
    m = re.search(r'filename="?([^";]+)"?', raw, re.IGNORECASE)
    return (m.group(1).strip() if m else "")


def _decode_html_blob(blob: bytes) -> str:
    for enc in ("utf-8", "utf-16", "latin-1"):
        try:
            text = blob.decode(enc, errors="ignore")
            if text.strip():
                return text
        except Exception:
            continue
    return ""


def _ocr_pdf_text(blob: bytes) -> str:
    return _ocr_pdf_pages(blob, max_pages=3, scale=2.0)


def _pdf_text_looks_unusable(text: str) -> bool:
    sample = str(text or "").strip().lower()
    if not sample:
        return True
    marker_hits = sum(1 for marker in _PDF_INTERNAL_MARKERS if marker in sample)
    return marker_hits >= 3


def _extract_candidate_urls(*, blob: bytes, source_url: str) -> List[str]:
    html = _decode_html_blob(blob)
    if not html:
        return _provider_candidate_urls(source_url=source_url)

    base = source_url
    found: List[str] = []
    found.extend(_provider_candidate_urls(source_url=source_url))
    for abs_url in _URL_PAT.findall(html):
        found.append(unescape(abs_url.strip()))
    for rel_url in _HTML_HREF_PAT.findall(html):
        rel = unescape(str(rel_url or "").strip())
        if rel:
            found.append(urljoin(base, rel))
    m = _META_REFRESH_PAT.search(html)
    if m:
        found.append(urljoin(base, unescape(m.group(1).strip())))

    uniq: List[str] = []
    seen: set[str] = set()
    for url in found:
        clean = str(url or "").strip()
        if not clean or clean in seen:
            continue
        seen.add(clean)
        uniq.append(clean)

    source_host = str(urlparse(source_url).netloc or "").lower()

    def _score(url: str) -> tuple[int, int, int]:
        parsed = urlparse(url)
        path = str(parsed.path or "").lower()
        query = str(parsed.query or "").lower()
        host = str(parsed.netloc or "").lower()
        artifact_ext = any(path.endswith(ext) for ext in _ARTIFACT_EXTS)
        artifact_hint = any(tok in path or tok in query for tok in ("pdf", "download", "attachment", "export", "file"))
        same_host = host == source_host
        htmlish = path.endswith((".html", ".htm")) or path in {"", "/"}
        return (
            1 if artifact_ext else 0,
            1 if artifact_hint else 0,
            1 if same_host else 0,
        ) if not htmlish else (
            0 if artifact_ext else 0,
            1 if artifact_hint else 0,
            1 if same_host else 0,
        )

    ranked = sorted(uniq, key=_score, reverse=True)
    return ranked[:12]


def _extract_artifact_text(*, artifact_type: str, blob: bytes, content_type: str, filename: str) -> Dict[str, Any]:
    extracted_text = _extract_text(blob, content_type=content_type, filename=filename)
    pdf_forensics = _pdf_forensics(blob) if artifact_type == "pdf" else {}
    pdf_text = _extract_pdf_text(blob) if artifact_type == "pdf" else ""
    ocr_text = ""
    ocr_used = False

    combined_parts = [str(extracted_text or "").strip(), str(pdf_text or "").strip()]
    combined_text = "\n".join(part for part in combined_parts if part).strip()

    if artifact_type == "html" and len(combined_text) < 48:
        html_text = _decode_html_blob(blob)
        if html_text.strip():
            combined_text = html_text

    if artifact_type == "pdf" and (len(combined_text) < 48 or _pdf_text_looks_unusable(combined_text)):
        ocr_text = _ocr_pdf_text(blob)
        if ocr_text.strip():
            ocr_used = True
            combined_text = "\n".join(part for part in [combined_text, ocr_text.strip()] if part).strip()

    return {
        "combined_text": combined_text[:20000],
        "pdf_forensics": pdf_forensics,
        "ocr_used": ocr_used,
        "ocr_text": ocr_text[:20000],
    }


def analyze_linked_artifact(
    *,
    url: str,
    timeout: float = 8.0,
    max_bytes: int = 2_500_000,
    tenant_id: str | None = None,
    vendor_domain: str | None = None,
    supplier_key: str | None = None,
    known_bank_fingerprint: str | None = None,
) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "linked_artifact_available": False,
        "linked_artifact_type": "unknown",
        "linked_content_type": None,
        "linked_filename": None,
        "linked_sha256": None,
        "linked_attack_hypothesis": "unknown_remote_artifact",
        "linked_decode_path": "safe_passive_link_fetch_only",
        "linked_suggested_next_step": "review",
        "pii_detected": False,
        "pii_type": [],
        "ssn_hits": [],
        "embedded_urls": [],
        "linked_text_excerpt": "",
        "linked_pdf_has_javascript": False,
        "linked_redirect_chain": [],
        "linked_ocr_used": False,
    }
    raw_url = str(url or "").strip()
    if not raw_url:
        out["error"] = "linked_url_missing"
        return out
    host_enrichment = _best_effort_host_enrichment(raw_url=raw_url, timeout=timeout)
    destination_host = str(host_enrichment.get("host") or "").strip().lower()
    supplier_verification = _supplier_and_payment_verification(
        tenant_id=tenant_id,
        supplier_key=supplier_key,
        vendor_domain=vendor_domain,
        destination_host=destination_host,
        linked_bank_fingerprint=None,
        known_bank_fingerprint=known_bank_fingerprint,
    )
    blob = b""
    content_type = ""
    filename = "artifact"
    final_url = raw_url
    use_offline_fixture = False
    resp = None
    fetch_error = None
    fixture = _offline_fixture_for_url(raw_url)
    if fixture:
        try:
            blob = open(fixture["local_path"], "rb").read()
            content_type = str(fixture.get("content_type") or content_type or "").strip().lower()
            filename = str(fixture.get("filename") or filename or "artifact").strip()
            out["linked_offline_fixture"] = True
            out["linked_offline_fixture_tag"] = fixture.get("tag")
            out["linked_final_url"] = raw_url
            out["linked_redirect_chain"] = [raw_url]
            use_offline_fixture = True
        except Exception:
            blob = b""

    if not blob:
        try:
            resp = safe_request("GET", raw_url, timeout=timeout, allow_redirects=True)
        except Exception as exc:
            fetch_error = f"linked_fetch_failed:{exc}"

        if resp is not None:
            final_url = str(getattr(resp, "url", "") or raw_url)
            out["linked_redirect_chain"] = [raw_url] + ([final_url] if final_url and final_url != raw_url else [])
            out["linked_final_url"] = final_url
            out["linked_http_status"] = int(resp.status_code)
            if int(resp.status_code or 0) < 400:
                blob = bytes(resp.content or b"")
                content_type = str(resp.headers.get("content-type") or "").split(";", 1)[0].strip().lower()
                parsed = urlparse(final_url)
                filename = _content_disposition_filename(resp.headers) or parsed.path.rsplit("/", 1)[-1] or "artifact"

    if (not blob) or (len(blob) > max_bytes) or (resp is not None and int(resp.status_code or 0) >= 400):
        fixture = fixture or _offline_fixture_for_url(raw_url) or _offline_fixture_for_url(final_url)
        if fixture:
            try:
                blob = open(fixture["local_path"], "rb").read()
                content_type = str(fixture.get("content_type") or content_type or "").strip().lower()
                filename = str(fixture.get("filename") or filename or "artifact").strip()
                out["linked_offline_fixture"] = True
                out["linked_offline_fixture_tag"] = fixture.get("tag")
                out["linked_final_url"] = raw_url
                out["linked_redirect_chain"] = [raw_url]
                use_offline_fixture = True
            except Exception:
                pass

    if not blob:
        try:
            from src.app.observability.metrics import record_linked_artifact_fetch, record_linked_artifact_unresolved, record_linked_artifact_verdict
            record_linked_artifact_fetch(tenant_id, "unresolved", "live_url")
            record_linked_artifact_unresolved(
                tenant_id,
                _normalize_fetch_metric_reason(fetch_error or (f"http_{int(resp.status_code)}" if resp is not None else "linked_artifact_empty")),
            )
        except Exception:
            pass
        unresolved = _fallback_url_only_assessment(
            raw_url=final_url or raw_url,
            fetch_error=fetch_error or (f"http_{int(resp.status_code)}" if resp is not None else "linked_artifact_empty"),
        )
        unresolved["linked_host_enrichment"] = host_enrichment
        unresolved["linked_supplier_verification"] = supplier_verification
        confidence = _link_confidence_and_state(
            artifact_available=False,
            attack_hypothesis=str(unresolved.get("linked_attack_hypothesis") or "unknown_remote_artifact"),
            pii_types=[],
            ssn_hits=[],
            suggested_next_step=str(unresolved.get("linked_suggested_next_step") or "review"),
            fetch_error=str(unresolved.get("error") or ""),
            host_enrichment=host_enrichment,
            content_type="",
            supplier_verification=supplier_verification,
        )
        unresolved.update(confidence)
        unresolved["linked_user_summary"] = _user_facing_evidence_summary(
            attack_hypothesis=str(unresolved.get("linked_attack_hypothesis") or "unknown_remote_artifact"),
            artifact_available=False,
            reason_summary=str(unresolved.get("linked_reason_summary") or ""),
            policy_action=str(unresolved.get("linked_policy_action") or "review"),
            final_url=str(unresolved.get("linked_final_url") or raw_url),
            pii_types=[],
            ssn_hits=[],
            confidence_band=str(confidence.get("linked_confidence_band") or "low"),
            verdict_label=str(confidence.get("linked_verdict_label") or "Unverified Destination"),
            supplier_verification=supplier_verification,
        )
        try:
            from src.app.observability.metrics import record_linked_artifact_verdict
            record_linked_artifact_verdict(tenant_id, unresolved.get("linked_verdict_label"))
        except Exception:
            pass
        return unresolved
    if len(blob) > max_bytes:
        out["error"] = "linked_artifact_too_large"
        out["linked_size_bytes"] = len(blob)
        out["linked_suggested_next_step"] = "queue_sandbox_detonation"
        return out
    if use_offline_fixture and not content_type:
        content_type = "application/pdf" if filename.lower().endswith(".pdf") else "application/octet-stream"
    try:
        from src.app.observability.metrics import record_linked_artifact_fetch
        record_linked_artifact_fetch(tenant_id, "fixture" if use_offline_fixture else "success", "offline_fixture" if use_offline_fixture else "live_url")
    except Exception:
        pass

    artifact_type = _guess_artifact_type(content_type, filename, blob)
    text_meta = _extract_artifact_text(
        artifact_type=artifact_type,
        blob=blob,
        content_type=content_type,
        filename=filename,
    )
    combined_text = str(text_meta.get("combined_text") or "").strip()
    pdf_forensics = text_meta.get("pdf_forensics") if isinstance(text_meta.get("pdf_forensics"), dict) else {}
    ocr_used = bool(text_meta.get("ocr_used"))
    embedded_urls = sorted(set(_URL_PAT.findall(combined_text)))[:20]

    if artifact_type == "html":
        candidate_urls = _extract_candidate_urls(blob=blob, source_url=final_url)
        out["linked_embedded_candidates"] = candidate_urls[:10]
        follow_url = next(
            (candidate for candidate in candidate_urls if candidate and candidate.rstrip("/") != final_url.rstrip("/")),
            None,
        )
        if follow_url:
            try:
                resp2 = safe_request("GET", follow_url, timeout=timeout, allow_redirects=True)
                final_url_2 = str(getattr(resp2, "url", "") or follow_url)
                blob2 = bytes(resp2.content or b"")
                if resp2.status_code < 400 and blob2 and len(blob2) <= max_bytes:
                    content_type_2 = str(resp2.headers.get("content-type") or "").split(";", 1)[0].strip().lower()
                    parsed_2 = urlparse(final_url_2)
                    filename_2 = _content_disposition_filename(resp2.headers) or parsed_2.path.rsplit("/", 1)[-1] or "artifact"
                    artifact_type_2 = _guess_artifact_type(content_type_2, filename_2, blob2)
                    if artifact_type_2 != "html":
                        out["linked_landing_page_url"] = final_url
                        out["linked_landing_page_excerpt"] = combined_text[:500]
                        final_url = final_url_2
                        content_type = content_type_2
                        filename = filename_2
                        artifact_type = artifact_type_2
                        blob = blob2
                        out["linked_redirect_chain"] = list(dict.fromkeys(out["linked_redirect_chain"] + [follow_url, final_url_2]))
                        text_meta = _extract_artifact_text(
                            artifact_type=artifact_type,
                            blob=blob,
                            content_type=content_type,
                            filename=filename,
                        )
                        combined_text = str(text_meta.get("combined_text") or "").strip()
                        pdf_forensics = text_meta.get("pdf_forensics") if isinstance(text_meta.get("pdf_forensics"), dict) else {}
                        ocr_used = bool(text_meta.get("ocr_used"))
                        embedded_urls = sorted(set(_URL_PAT.findall(combined_text)))[:20]
            except Exception:
                pass

    # SSN detection: try full-pattern first (hyphenated / spaced), then bare 9-digit heuristic
    _ssn_raw = [m for grp in _SSN_PAT.findall(combined_text) for m in (grp if isinstance(grp, tuple) else (grp,)) if m]
    _ssn_glued = _SSN_GLUE_PAT.findall(combined_text)
    _ssn_bare = _SSN_BARE_PAT.findall(combined_text) if not _ssn_raw else []
    ssn_hits = sorted(set(_ssn_raw + _ssn_glued + _ssn_bare))[:20]
    pii_types: List[str] = []
    if ssn_hits:
        pii_types.append("ssn")
    elif "ssn" in combined_text.lower() and _DOB_PAT.search(combined_text):
        pii_types.append("regulated_identity_document")
    if _CC_PAT.search(combined_text):
        pii_types.append("pci")
    linked_bank_fields = _extract_bank_fields(combined_text)
    linked_bank_fingerprint = _bank_fingerprint(linked_bank_fields)
    supplier_verification = _supplier_and_payment_verification(
        tenant_id=tenant_id,
        supplier_key=supplier_key,
        vendor_domain=vendor_domain,
        destination_host=str(urlparse(final_url).hostname or destination_host or "").strip().lower(),
        linked_bank_fingerprint=linked_bank_fingerprint,
        known_bank_fingerprint=known_bank_fingerprint,
    )

    attack_hypothesis = "unknown_remote_artifact"
    decode_path = "safe_passive_link_fetch_only"
    suggested_next_step = "review"
    if artifact_type in {"office_macro_candidate", "xlsx"} and filename.lower().endswith(_MACRO_EXTS):
        attack_hypothesis = "linked_macro_artifact"
        decode_path = "sandbox_required_do_not_execute"
        suggested_next_step = "queue_sandbox_detonation"
    elif artifact_type in {"archive", "zip"}:
        attack_hypothesis = "linked_archive_staging"
        decode_path = "sandbox_required_do_not_execute"
        suggested_next_step = "queue_sandbox_detonation"
    elif pii_types:
        attack_hypothesis = "linked_pii_exposure"
        decode_path = "safe_passive_pii_extract"
        suggested_next_step = "review"
    elif any(p.search(combined_text) for p in _LURE_PATTERNS):
        attack_hypothesis = "linked_payment_fraud"
        decode_path = "safe_passive_link_fetch_only"
        suggested_next_step = "review"

    if any(p.search(blob.decode("latin-1", errors="ignore")) for p in _SCRIPT_PATTERNS):
        out["linked_pdf_has_javascript"] = True
        if attack_hypothesis == "unknown_remote_artifact":
            attack_hypothesis = "linked_active_document"
        decode_path = "sandbox_required_do_not_execute"
        suggested_next_step = "queue_sandbox_detonation"

    linked_reason_summary = "Linked artifact was fetched passively and needs analyst review."
    linked_policy_action = "review"
    if ssn_hits:
        linked_reason_summary = f"Linked artifact exposed SSN-like data ({len(ssn_hits)} hit{'s' if len(ssn_hits) != 1 else ''})."
        linked_policy_action = "privacy_hold"
    elif "pci" in pii_types:
        linked_reason_summary = "Linked artifact exposed PCI-like payment data."
        linked_policy_action = "privacy_hold"
    elif pii_types:
        linked_reason_summary = f"Linked artifact exposed regulated data: {', '.join(pii_types)}."
        linked_policy_action = "privacy_hold"
    elif suggested_next_step == "queue_sandbox_detonation":
        linked_reason_summary = "Linked artifact looks active or executable and should only be opened in sandbox."
        linked_policy_action = "sandbox"
    elif attack_hypothesis == "linked_payment_fraud":
        linked_reason_summary = "Linked artifact contains payment-lure content and should be reviewed before any action."
        linked_policy_action = "review"

    out.update({
        "linked_artifact_available": True,
        "linked_artifact_type": artifact_type,
        "linked_content_type": content_type or None,
        "linked_filename": filename,
        "linked_sha256": hashlib.sha256(blob).hexdigest(),
        "linked_size_bytes": len(blob),
        "linked_final_url": final_url,
        "linked_attack_hypothesis": attack_hypothesis,
        "linked_decode_path": decode_path,
        "linked_suggested_next_step": suggested_next_step,
        "pii_detected": bool(pii_types),
        "pii_type": pii_types,
        "ssn_hits": ssn_hits,
        "embedded_urls": embedded_urls,
        "linked_text_excerpt": combined_text[:500],
        "linked_pdf_forensics": pdf_forensics,
        "linked_ocr_used": ocr_used,
        "linked_reason_summary": linked_reason_summary,
        "linked_policy_action": linked_policy_action,
        "linked_bank_fields": linked_bank_fields,
        "linked_bank_fingerprint": linked_bank_fingerprint,
        "linked_supplier_verification": supplier_verification,
    })
    out["linked_host_enrichment"] = host_enrichment
    out["linked_content_type_validated"] = bool(content_type)
    confidence = _link_confidence_and_state(
        artifact_available=True,
        attack_hypothesis=attack_hypothesis,
        pii_types=pii_types,
        ssn_hits=ssn_hits,
        suggested_next_step=suggested_next_step,
        fetch_error=fetch_error,
        host_enrichment=host_enrichment,
        content_type=content_type,
        supplier_verification=supplier_verification,
    )
    out.update(confidence)
    out["linked_user_summary"] = _user_facing_evidence_summary(
        attack_hypothesis=attack_hypothesis,
        artifact_available=True,
        reason_summary=linked_reason_summary,
        policy_action=linked_policy_action,
        final_url=final_url,
        pii_types=pii_types,
        ssn_hits=ssn_hits,
        confidence_band=str(confidence.get("linked_confidence_band") or "medium"),
        verdict_label=str(confidence.get("linked_verdict_label") or "Needs Review"),
        supplier_verification=supplier_verification,
    )
    try:
        from src.app.observability.metrics import record_linked_artifact_verdict
        record_linked_artifact_verdict(tenant_id, out.get("linked_verdict_label"))
    except Exception:
        pass
    out.update(
        _classify_linked_owner_scope(
            raw_url=raw_url,
            final_url=final_url,
            pii_detected=bool(pii_types),
        )
    )
    return out
