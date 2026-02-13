from __future__ import annotations

import json
import os
import re
import unicodedata
from typing import Any, Dict, List, Tuple

from src.app.config import get_settings, load_feature_flags
from src.app.security.email_security_rules import extract_domain


def _thresholds() -> Dict[str, Any]:
    try:
        return (load_feature_flags(get_settings().feature_flags_path) or {}).get("SECURITY_THRESHOLDS", {}) or {}
    except Exception:
        return {}


def _as_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except Exception:
        return default


def _confusable_skeleton(text: str) -> str:
    conf_map = {
        "а": "a",
        "е": "e",
        "о": "o",
        "р": "p",
        "с": "c",
        "у": "y",
        "х": "x",
        "і": "i",
        "ј": "j",
        "ӏ": "l",
        "ԁ": "d",
        "һ": "h",
        "ո": "n",
    }
    norm = unicodedata.normalize("NFKC", text or "")
    return "".join(conf_map.get(ch, ch) for ch in norm)


def normalize_confusable_text(text: str | None) -> str:
    if not text:
        return ""
    low = unicodedata.normalize("NFKC", str(text))
    return _confusable_skeleton(low)


def _extract_structured_fields(text: str) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    t = text or ""
    m_vendor = re.search(r"(?im)^\s*([A-Za-z0-9 .&,'-]{3,80}(?:Pty Ltd|Ltd|LLC|Inc\.?|GmbH))\s*$", t)
    if m_vendor:
        out["vendor_name"] = m_vendor.group(1).strip()
    m_abn = re.search(r"\bABN\s*:\s*([0-9 ]{11,20})", t, re.IGNORECASE)
    if m_abn:
        out["abn"] = re.sub(r"\s+", "", m_abn.group(1))
    m_inv = re.search(r"\b(?:invoice(?:\s+no\.?)?|inv(?:oice)?)[\s:#-]*([A-Z0-9-]{5,40})", t, re.IGNORECASE)
    if m_inv:
        out["invoice_number"] = m_inv.group(1).strip()
    m_due = re.search(r"\bdue\s+date[\s:]*([0-9]{1,2}[/\- ][A-Za-z0-9]{2,9}[/\- ][0-9]{2,4}|[0-9]{4}-[0-9]{2}-[0-9]{2})", t, re.IGNORECASE)
    if m_due:
        out["due_date"] = m_due.group(1).strip()
    m_total = re.search(r"\btotal\s+amount\s+due[\s:]*\$?\s*([0-9][0-9,]*(?:\.[0-9]{2})?)", t, re.IGNORECASE)
    if m_total:
        out["total_amount"] = m_total.group(1).replace(",", "")
    m_bsb = re.search(r"\bBSB[\s:]*([0-9]{3}[- ]?[0-9]{3})", t, re.IGNORECASE)
    if m_bsb:
        out["bsb"] = m_bsb.group(1).replace(" ", "")
    m_acc = re.search(r"\b(?:account\s*(?:no|number)?)[\s:]*([0-9 ]{6,20})", t, re.IGNORECASE)
    if m_acc:
        out["account_number"] = re.sub(r"\s+", "", m_acc.group(1))
    m_swift = re.search(r"\bSWIFT[\s:]*([A-Z0-9]{8,11})\b", t, re.IGNORECASE)
    if m_swift:
        out["swift"] = m_swift.group(1).upper()
    m_po = re.search(r"\bPO[\s#:-]*([A-Z0-9-]{4,40})\b", t, re.IGNORECASE)
    if m_po:
        out["po_number"] = m_po.group(1).strip()
    m_grn = re.search(r"\bGRN[\s#:-]*([A-Z0-9-]{3,40})\b", t, re.IGNORECASE)
    if m_grn:
        out["grn_number"] = m_grn.group(1).strip()
    m_receipt = re.search(r"\b(?:receipt|proof\s+of\s+delivery)[\s#:-]*([A-Z0-9-]{3,40})\b", t, re.IGNORECASE)
    if m_receipt:
        out["receipt_number"] = m_receipt.group(1).strip()
    return out


def _vendor_baselines() -> Dict[str, Any]:
    thr = _thresholds()
    raw = thr.get("TRUSTED_VENDOR_BASELINES")
    if isinstance(raw, dict):
        return raw
    env_raw = os.getenv("EMAIL_VENDOR_BASELINES_JSON")
    if env_raw:
        try:
            parsed = json.loads(env_raw)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass
    return {}


def _cross_check(
    email: Dict[str, Any],
    fields: Dict[str, Any],
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    indicators: List[Dict[str, Any]] = []
    checks: Dict[str, Any] = {}
    baselines = _vendor_baselines()
    vendor_domain = str(email.get("vendor_domain") or "").strip().lower()
    sender = str(extract_domain(email.get("from_addr")) or "").strip().lower()
    reply = str(extract_domain(email.get("reply_to")) or "").strip().lower()
    baseline = baselines.get(vendor_domain) if vendor_domain else None
    if vendor_domain and not baseline:
        indicators.append(
            {
                "type": "vendor_baseline_missing",
                "value": vendor_domain,
                "reason": "Vendor baseline record missing for cross-check",
            }
        )
    if baseline:
        approved_contacts = [str(x).lower() for x in (baseline.get("approved_contacts") or [])]
        known_bank_fp = str(baseline.get("bank_fingerprint") or "").strip()
        known_bank_fp_sha256 = str(baseline.get("bank_fingerprint_sha256") or "").strip().lower()
        known_abn = re.sub(r"\s+", "", str(baseline.get("abn") or ""))
        approved_pos = set(str(x) for x in (baseline.get("approved_pos") or []))
        approved_grns = set(str(x) for x in (baseline.get("approved_grns") or []))
        approved_receipts = set(str(x) for x in (baseline.get("approved_receipts") or []))
        if sender and vendor_domain and sender != vendor_domain:
            indicators.append(
                {
                    "type": "vendor_master_mismatch",
                    "value": {"expected": vendor_domain, "observed": sender},
                    "reason": "Sender domain does not match vendor master",
                }
            )
        if approved_contacts and not any((sender in c or reply in c) for c in approved_contacts):
            indicators.append(
                {
                    "type": "approved_contact_mismatch",
                    "value": {"sender": sender, "reply_to": reply},
                    "reason": "Sender/reply contact not in approved vendor callback contacts",
                }
            )
        proposed_fp = str(email.get("proposed_bank_fingerprint") or "").strip()
        if known_bank_fp and proposed_fp and known_bank_fp != proposed_fp:
            indicators.append(
                {
                    "type": "bank_fingerprint_baseline_mismatch",
                    "value": {"expected": known_bank_fp, "observed": proposed_fp},
                    "reason": "Proposed bank fingerprint differs from trusted baseline",
                }
            )
        # Attachment-derived bank fingerprint (sha256) can be compared to baseline when available.
        if known_bank_fp_sha256 and len(known_bank_fp_sha256) == 64:
            try:
                for a in (email.get("attachments") or []):
                    fp = str((a or {}).get("extracted_bank_fingerprint") or "").strip().lower()
                    if fp and fp != known_bank_fp_sha256:
                        indicators.append(
                            {
                                "type": "bank_fingerprint_extracted_mismatch",
                                "value": {"expected_prefix": known_bank_fp_sha256[:12], "observed_prefix": fp[:12]},
                                "reason": "Attachment-derived bank fingerprint differs from vendor baseline sha256 fingerprint",
                            }
                        )
                        break
            except Exception:
                pass
        if known_abn and fields.get("abn") and known_abn != str(fields.get("abn")):
            indicators.append(
                {
                    "type": "abn_mismatch",
                    "value": {"expected": known_abn, "observed": fields.get("abn")},
                    "reason": "ABN mismatch against vendor master",
                }
            )
        if approved_pos:
            po = str(fields.get("po_number") or "")
            if po and po not in approved_pos:
                indicators.append(
                    {
                        "type": "po_reference_unapproved",
                        "value": po,
                        "reason": "PO reference not in approved records",
                    }
                )
        if approved_grns:
            grn = str(fields.get("grn_number") or "")
            if grn and grn not in approved_grns:
                indicators.append(
                    {
                        "type": "grn_reference_unapproved",
                        "value": grn,
                        "reason": "GRN reference not in approved records",
                    }
                )
        if approved_receipts:
            receipt = str(fields.get("receipt_number") or "")
            if receipt and receipt not in approved_receipts:
                indicators.append(
                    {
                        "type": "receipt_reference_unapproved",
                        "value": receipt,
                        "reason": "Receipt reference not in approved records",
                    }
                )
        checks = {
            "vendor_domain": vendor_domain,
            "sender_domain": sender,
            "reply_domain": reply,
            "approved_contacts_count": len(approved_contacts),
            "approved_pos_count": len(approved_pos),
            "approved_grns_count": len(approved_grns),
            "approved_receipts_count": len(approved_receipts),
            "baseline_bank_fp_sha256_present": bool(known_bank_fp_sha256),
        }
    return indicators, checks


def _forensics_from_attachments(attachments: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    indicators: List[Dict[str, Any]] = []
    details: Dict[str, Any] = {"template_drift": [], "logo_layout": [], "edit_compression": []}
    for a in attachments or []:
        name = str(a.get("name") or "")
        template_hash = str(a.get("template_hash") or "")
        logo_hash = str(a.get("logo_hash") or "")
        layout_hash = str(a.get("layout_hash") or "")
        edited_regions = int(a.get("edited_regions") or 0)
        compression_score = _as_float(a.get("compression_artifact_score"), 0.0)
        expected_template = str(a.get("expected_template_hash") or "")
        expected_logo = str(a.get("expected_logo_hash") or "")
        expected_layout = str(a.get("expected_layout_hash") or "")
        if expected_template and template_hash and expected_template != template_hash:
            indicators.append(
                {
                    "type": "template_drift",
                    "value": {"attachment": name, "expected": expected_template, "observed": template_hash},
                    "reason": "Template hash drift from trusted baseline",
                }
            )
            details["template_drift"].append(name)
        if (expected_logo and logo_hash and expected_logo != logo_hash) or (expected_layout and layout_hash and expected_layout != layout_hash):
            indicators.append(
                {
                    "type": "logo_layout_mismatch",
                    "value": {"attachment": name, "logo_hash": logo_hash, "layout_hash": layout_hash},
                    "reason": "Logo/layout mismatch against baseline",
                }
            )
            details["logo_layout"].append(name)
        if edited_regions >= 2:
            indicators.append(
                {
                    "type": "edited_region_artifact",
                    "value": {"attachment": name, "edited_regions": edited_regions},
                    "reason": "Potential edited-region artifacts detected",
                }
            )
            details["edit_compression"].append(name)
        if compression_score >= 0.6:
            indicators.append(
                {
                    "type": "compression_artifact_high",
                    "value": {"attachment": name, "score": compression_score},
                    "reason": "High compression artifact score",
                }
            )
            details["edit_compression"].append(name)
        # PDF forensics (attachment parser populates these when bytes provided).
        try:
            emb = int(a.get("embedded_files_count") or 0)
            if emb > 0:
                indicators.append(
                    {
                        "type": "pdf_embedded_files",
                        "value": {"attachment": name, "count": emb},
                        "reason": "PDF contains embedded files/file specs",
                    }
                )
        except Exception:
            pass
        try:
            objstm = int(a.get("pdf_objstm_count") or 0)
            if objstm >= 3:
                indicators.append(
                    {
                        "type": "pdf_object_stream_heavy",
                        "value": {"attachment": name, "objstm_count": objstm},
                        "reason": "PDF uses many object streams (often used by malware packers)",
                    }
                )
        except Exception:
            pass
    return indicators, details


def _signal_weight(ind_type: str) -> float:
    weights = {
        "vendor_homoglyph_impersonation": 35.0,
        "confusable_homoglyph_domain": 20.0,
        "vendor_master_mismatch": 18.0,
        "approved_contact_mismatch": 15.0,
        "bank_fingerprint_baseline_mismatch": 30.0,
        "abn_mismatch": 20.0,
        "po_reference_unapproved": 12.0,
        "grn_reference_unapproved": 10.0,
        "receipt_reference_unapproved": 10.0,
        "template_drift": 16.0,
        "logo_layout_mismatch": 14.0,
        "edited_region_artifact": 18.0,
        "compression_artifact_high": 12.0,
        "pdf_embedded_files": 28.0,
        "pdf_object_stream_heavy": 12.0,
        "bank_fingerprint_extracted_mismatch": 30.0,
        "bank_fields_present_in_attachment": 10.0,
    }
    return float(weights.get(ind_type, 8.0))


def compute_signal_scores(indicators: List[Dict[str, Any]]) -> Dict[str, Any]:
    rows = []
    total = 0.0
    for ind in indicators or []:
        t = str(ind.get("type") or "")
        w = _signal_weight(t)
        rows.append({"type": t, "weight": round(w, 3), "reason": ind.get("reason")})
        total += w
    total = min(100.0, total)
    band = "auto-allow"
    if total >= 70.0:
        band = "block"
    elif total >= 40.0:
        band = "review"
    return {"total": round(total, 3), "band": band, "contributions": rows}


def analyze_email_artifacts(email: Dict[str, Any]) -> Dict[str, Any]:
    attachments = list(email.get("attachments") or [])
    text_parts = [str(email.get("subject") or ""), str(email.get("body") or "")]
    for a in attachments:
        et = str(a.get("extracted_text") or "")
        if et:
            text_parts.append(et)
    raw_text = "\n".join([x for x in text_parts if x])
    normalized_text = normalize_confusable_text(raw_text)
    fields = _extract_structured_fields(normalized_text)

    indicators: List[Dict[str, Any]] = []
    if normalized_text and normalized_text != raw_text:
        indicators.append(
            {
                "type": "unicode_confusable_text_normalized",
                "value": True,
                "reason": "Unicode confusable normalization changed extracted text",
            }
        )
    baseline_ind, baseline_checks = _cross_check(email, fields)
    forensics_ind, forensics_details = _forensics_from_attachments(attachments)
    indicators.extend(baseline_ind)
    indicators.extend(forensics_ind)

    # Evidence fusion: if attachment parsing extracted bank details, compare derived fingerprint vs trusted baseline
    # when baseline is a real fingerprint (64-hex).
    try:
        baseline_fp = str(email.get("bank_fingerprint") or "").strip().lower()
        for a in attachments:
            fp = str(a.get("extracted_bank_fingerprint") or "").strip().lower()
            if not fp:
                continue
            indicators.append(
                {
                    "type": "bank_fields_present_in_attachment",
                    "value": {"attachment": str(a.get("name") or ""), "fingerprint_prefix": fp[:12]},
                    "reason": "Bank fields parsed from attachment bytes/text",
                }
            )
            if baseline_fp and len(baseline_fp) == 64 and all(ch in "0123456789abcdef" for ch in baseline_fp):
                if fp != baseline_fp:
                    indicators.append(
                        {
                            "type": "bank_fingerprint_extracted_mismatch",
                            "value": {"expected_prefix": baseline_fp[:12], "observed_prefix": fp[:12]},
                            "reason": "Extracted bank fingerprint differs from vendor baseline fingerprint",
                        }
                    )
    except Exception:
        pass

    signal_scores = compute_signal_scores(indicators)
    return {
        "parsed_fields": fields,
        "normalized_text_excerpt": normalized_text[:1200],
        "indicators": indicators,
        "baseline_checks": baseline_checks,
        "forensics_details": forensics_details,
        "signal_scores": signal_scores,
    }
