"""Email forensics snapshots (extracted from email_security.py, session 2).

Four PURE builders over the email dict — no orchestrator state, no back-reference to email_security:
  * _attachment_forensics_snapshot   — per-attachment material class + evidence excerpts + risk;
  * _sender_infrastructure_snapshot  — sender/reply/vendor domain + reputation rollup;
  * _attachment_baseline_diff_snapshot — vendor-baseline drift on attachments;
  * _attachment_visual_diff_snapshot — pixel/visual diff overlay (PIL, lazy-imported).

Nested helpers stay nested (self-contained). External deps: extract_domain (rules), 
validate_agent_action (maestro). Best-effort; never raises. Vertical-blind.
"""
from __future__ import annotations

import base64
import io
import json
import os
import re
from difflib import SequenceMatcher
from typing import Any, Dict

from src.app.security.email_security_rules import extract_domain
from src.app.security.maestro_boundaries import validate_agent_action


def _attachment_forensics_snapshot(
    email: Dict[str, Any],
    artifact_intel: Dict[str, Any] | None,
) -> list[dict[str, Any]]:
    attachments = [dict(a or {}) for a in (email.get("attachments") or []) if isinstance(a, dict)]
    parsed_fields = ((artifact_intel or {}).get("parsed_fields") if isinstance(artifact_intel, dict) else {}) or {}
    baseline_checks = ((artifact_intel or {}).get("baseline_checks") if isinstance(artifact_intel, dict) else {}) or {}
    forensics_details = ((artifact_intel or {}).get("forensics_details") if isinstance(artifact_intel, dict) else {}) or {}
    summary: list[dict[str, Any]] = []
    vendor_name = str(parsed_fields.get("vendor_name") or "").strip()
    sender_domain = str(baseline_checks.get("sender_domain") or "").strip().lower()
    vendor_domain = str(baseline_checks.get("vendor_domain") or "").strip().lower()
    reply_domain = str(baseline_checks.get("reply_domain") or "").strip().lower()
    known_bank_fp = str(baseline_checks.get("known_bank_fingerprint") or baseline_checks.get("bank_fingerprint") or "").strip()

    def _attachment_material_class(name: str, extracted_text: str, urls: list[str], suspicious_instructions: list[str]) -> str:
        lowered = str(name or "").strip().lower()
        text = str(extracted_text or "").strip().lower()
        ext = os.path.splitext(lowered)[1]
        if ext in {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".pdf", ".msg", ".eml"}:
            if suspicious_instructions or urls:
                return "active_payment_lure"
            return "observed_supplier_artifact"
        if ext in {".md", ".txt", ".json"}:
            if any(tok in lowered for tok in ("guide", "scenario", "summary", "matrix", "taxonomy", "playbook", "spec", "report")):
                return "reference_spec_material"
            return "contextual_test_artifact"
        if ext in {".py", ".ps1", ".sh"}:
            if any(tok in text for tok in ("image.new", "generate", "simulat", "shopsquire", "invoice")):
                return "contextual_test_artifact"
        if ext in {".bas", ".vba", ".xlsm", ".xlam", ".vbs"}:
            _vba_exec_toks = (
                "sub auto_open()", "sub workbook_open()", "sub document_open()",
                "wscript.shell", "createobject(", "shell(", "mshta ", "certutil",
                "bitsadmin", "powershell",
            )
            if any(tok in text for tok in _vba_exec_toks):
                return "active_payment_lure"
            return "contextual_test_artifact"
        if suspicious_instructions or urls:
            return "active_payment_lure"
        return "contextual_test_artifact"

    def _text_summary(text: str) -> str:
        cleaned = re.sub(r"\s+", " ", str(text or "")).strip()
        if not cleaned:
            return ""
        if len(cleaned) <= 220:
            return cleaned
        return cleaned[:217] + "..."

    def _extract_urls(text: str) -> list[str]:
        found = re.findall(r"https?://[^\s<>'\"`]+", str(text or ""), re.IGNORECASE)
        out: list[str] = []
        for url in found:
            if url not in out:
                out.append(url)
        return out[:8]

    def _evidence_excerpt_lines(text: str) -> list[str]:
        out: list[str] = []
        for line in re.split(r"[\r\n]+", str(text or "")):
            cleaned = line.strip()
            if not cleaned:
                continue
            if re.search(r"(?i)(bank(?:ing)?\s+details?|remittance|payment|account|bsb|swift|invoice|abn)", cleaned):
                out.append(cleaned[:180])
            if len(out) >= 4:
                break
        return out

    for att in attachments:
        name = str(att.get("name") or "attachment")
        extracted_text = str(att.get("extracted_text") or "")
        urls = _extract_urls(extracted_text)
        if not urls:
            urls = [str(x) for x in (att.get("pdf_embedded_urls") or []) if str(x or "").strip()][:8]
        bank_fields = att.get("bank_fields") if isinstance(att.get("bank_fields"), dict) else {}
        suspicious_instructions: list[str] = []
        lower_text = extracted_text.lower()
        if re.search(r"(?i)\b(bank(?:ing)?\s+details?\s+have\s+changed|disregard\s+(?:any\s+)?previous\s+remittance|new\s+account|new\s+bsb|updated\s+payment\s+details?)\b", extracted_text):
            suspicious_instructions.append("Requests new or changed payment instructions.")
        if bank_fields:
            suspicious_instructions.append("Contains bank or remittance details in the attachment.")
        _indirect_instruction_patterns = [
            (r"(?i)\bignore\s+(?:all\s+)?previous\b", "Attempts to override prior instructions."),
            (r"(?i)\bsystem\s*(?::|prompt)\b", "Contains a forged system-instruction marker."),
            (r"(?i)\bskip\s+(?:the\s+)?human\s+gate\b", "Attempts to bypass required human authorization."),
            (r"(?i)\bapprove(?:d)?\s*=\s*true\b", "Attempts to forge approval state."),
            (r"(?i)\binvoke\s+[a-z0-9_.-]+", "Attempts to invoke a tool from untrusted document content."),
            (r"(?i)\bauthoritative\s+price\s+update\b", "Attempts to replace authoritative commercial facts."),
            (r"(?i)\b(?:state|present|claim)\s+.{0,80}\s+as\s+(?:a\s+)?fact\b", "Requests an unsupported claim be presented as fact."),
        ]
        for pattern, label in _indirect_instruction_patterns:
            if re.search(pattern, extracted_text):
                suspicious_instructions.append(label)
        # VBA / script macro execution indicators in extracted text.
        # Fires for .bas, .vba, .xlsm, .xlam, .ps1, .vbs, and any other attachment
        # where the text surface contains recognisable offensive VBA/script primitives.
        _vba_indicator_map = [
            ("sub auto_open()",       "vba_auto_open_macro"),
            ("sub workbook_open()",   "vba_workbook_open_macro"),
            ("sub document_open()",   "vba_document_open_macro"),
            ("wscript.shell",         "vba_wscript_shell"),
            ("createobject(",         "vba_createobject_call"),
            ("shell(",                "vba_shell_call"),
            ("mshta ",                "vba_mshta_lolbin"),
            ("certutil",              "vba_certutil_lolbin"),
            ("bitsadmin",             "vba_bitsadmin_lolbin"),
            ("powershell",            "vba_powershell_indicator"),
        ]
        for _vba_pat, _vba_label in _vba_indicator_map:
            if _vba_pat in lower_text:
                suspicious_instructions.append(
                    f"Attachment contains VBA/script execution indicator: {_vba_label}"
                )
        mismatch_signals: list[str] = []
        if name in list(forensics_details.get("template_drift") or []):
            mismatch_signals.append("Template differs from the trusted vendor baseline.")
        if name in list(forensics_details.get("logo_layout") or []):
            mismatch_signals.append("Logo or layout does not match the trusted baseline.")
        if sender_domain and vendor_domain and sender_domain != vendor_domain:
            mismatch_signals.append(f"Sender domain {sender_domain} does not match expected vendor domain {vendor_domain}.")
        if reply_domain and vendor_domain and reply_domain != vendor_domain:
            mismatch_signals.append(f"Reply-to domain {reply_domain} differs from expected vendor domain {vendor_domain}.")
        if vendor_name and not re.search(re.escape(vendor_name), extracted_text, re.IGNORECASE):
            mismatch_signals.append("Attachment content does not clearly reinforce the claimed vendor name.")
        if parsed_fields.get("abn_placeholder"):
            mismatch_signals.append("Document appears to contain a leftover template placeholder.")
        support_state = "neutral"
        if suspicious_instructions or mismatch_signals:
            support_state = "contradicts_sender_claim"
        elif vendor_name and re.search(re.escape(vendor_name), extracted_text, re.IGNORECASE):
            support_state = "supports_sender_claim"
        attachment_class = _attachment_material_class(name, extracted_text, urls, suspicious_instructions)
        summary.append(
            {
                "file_name": name,
                "file_type": str(att.get("content_type") or "unknown"),
                "sha256": str(att.get("sha256") or ""),
                "size_bytes": int(att.get("size_bytes") or 0),
                "text_summary": _text_summary(extracted_text),
                "analysis_text_sample": extracted_text[:4000] if extracted_text else "",
                "evidence_excerpt_lines": _evidence_excerpt_lines(extracted_text),
                "ocr_hit_count": len(re.findall(r"[A-Za-z0-9]", extracted_text)),
                "embedded_urls": urls,
                "qr_code_detected": bool(att.get("qr_code_detected")),
                "qr_external_url_detected": bool(att.get("qr_external_url_detected")),
                "qr_redirect_findings": list(att.get("qr_redirect_findings") or []) if isinstance(att.get("qr_redirect_findings"), list) else [],
                "qr_payloads": list(att.get("qr_payloads") or []) if isinstance(att.get("qr_payloads"), list) else [],
                "qr_assessments": list(att.get("qr_assessments") or []) if isinstance(att.get("qr_assessments"), list) else [],
                "suspicious_instructions": suspicious_instructions,
                "brand_supplier_mismatch_signals": mismatch_signals,
                "baseline_similarity": {
                    "template_aligned": name not in list(forensics_details.get("template_drift") or []),
                    "logo_layout_aligned": name not in list(forensics_details.get("logo_layout") or []),
                    "vendor_domain_matches": bool(vendor_domain and sender_domain and vendor_domain == sender_domain),
                    "known_good_template_hash": str(att.get("expected_template_hash") or ""),
                    "known_good_logo_hash": str(att.get("expected_logo_hash") or ""),
                    "known_good_layout_hash": str(att.get("expected_layout_hash") or ""),
                    "known_good_bank_fingerprint": known_bank_fp,
                },
                "supports_sender_claim": support_state,
                "attachment_class": attachment_class,
                "authority_level": "primary" if attachment_class in {"active_payment_lure", "observed_supplier_artifact"} else "contextual",
                "bank_fields_present": bool(bank_fields),
                "bank_fields": bank_fields,
                "pdf_forensics": {
                    "producer": att.get("pdf_producer"),
                    "creator": att.get("pdf_creator"),
                    "embedded_files_count": int(att.get("embedded_files_count") or 0),
                    "object_stream_count": int(att.get("pdf_objstm_count") or 0),
                    "xref_stream_present": bool(att.get("pdf_xrefstm_present")),
                    "actions": dict(att.get("pdf_actions") or {}) if isinstance(att.get("pdf_actions"), dict) else {},
                },
                "office_forensics": {
                    "external_relationships": list(att.get("office_external_relationships") or []),
                    "macro_member_count": int(att.get("office_macro_member_count") or 0),
                    "embedded_object_count": int(att.get("office_embedded_object_count") or 0),
                },
                "document_hashes": {
                    "template_hash": att.get("template_hash"),
                    "logo_hash": att.get("logo_hash"),
                    "layout_hash": att.get("layout_hash"),
                    "extracted_bank_fingerprint": att.get("extracted_bank_fingerprint"),
                },
                "parse_errors": list(att.get("parse_errors") or []) if isinstance(att.get("parse_errors"), list) else [],
                "ssn_detected": bool(att.get("ssn_detected")),
                "pii_detected": bool(att.get("pii_detected")),
                "pii_type": list(att.get("pii_type") or []) if isinstance(att.get("pii_type"), list) else [],
                "ssn_count": int(att.get("ssn_count") or 0),
                "linked_artifact": dict(att.get("linked_artifact") or {}) if isinstance(att.get("linked_artifact"), dict) else {},
                "linked_reason_summary": str(((att.get("linked_artifact") or {}).get("linked_reason_summary") if isinstance(att.get("linked_artifact"), dict) else "") or ""),
                "linked_policy_action": str(((att.get("linked_artifact") or {}).get("linked_policy_action") if isinstance(att.get("linked_artifact"), dict) else "") or ""),
                "linked_verdict_label": str(((att.get("linked_artifact") or {}).get("linked_verdict_label") if isinstance(att.get("linked_artifact"), dict) else "") or ""),
                "linked_confidence_band": str(((att.get("linked_artifact") or {}).get("linked_confidence_band") if isinstance(att.get("linked_artifact"), dict) else "") or ""),
                "linked_user_summary": dict(((att.get("linked_artifact") or {}).get("linked_user_summary") if isinstance(att.get("linked_artifact"), dict) else {}) or {}),
                "linked_host_enrichment": dict(((att.get("linked_artifact") or {}).get("linked_host_enrichment") if isinstance(att.get("linked_artifact"), dict) else {}) or {}),
                "linked_supplier_verification": dict(((att.get("linked_artifact") or {}).get("linked_supplier_verification") if isinstance(att.get("linked_artifact"), dict) else {}) or {}),
                "steg": {
                    "score": att.get("steg_score"),
                    "suspicious": bool(att.get("steg_suspicious")),
                    "source": att.get("steg_source"),
                },
                "steg_explanations": list(att.get("steg_explanations") or []) if isinstance(att.get("steg_explanations"), list) else [],
                "steg_details": dict(att.get("steg_details") or {}) if isinstance(att.get("steg_details"), dict) else {},
            }
        )
        # MAESTRO SC-04B per-attachment boundary check for attachment_forensics_agent.
        # Each attachment processed is a discrete boundary enforcement point.
        # Maps to OWASP Agentic AI AA03 (trust boundary violation) and AA05 (prompt injection
        # via content channels — OCR/QR surfaces in attachments can carry injections).
        try:
            _att_tools_used = []
            if extracted_text:
                _att_tools_used.append("ocr_attachment")
            if str(att.get("content_type") or "").lower().endswith("pdf") or name.lower().endswith(".pdf"):
                _att_tools_used.append("parse_pdf")
            if att.get("qr_code_detected"):
                _att_tools_used.append("scan_qr")
            if bank_fields:
                _att_tools_used.append("extract_bank_fields")
            if not _att_tools_used:
                _att_tools_used.append("extract_text")
            _att_violations = []
            for _tool in _att_tools_used:
                for _v in validate_agent_action(agent_name="attachment_forensics_agent", tool_name=_tool):
                    _att_violations.append({"violation_type": _v.violation_type, "detail": _v.detail, "severity": _v.severity})
            for _v in validate_agent_action(agent_name="attachment_forensics_agent", data_scope="attachments"):
                _att_violations.append({"violation_type": _v.violation_type, "detail": _v.detail, "severity": _v.severity})
            # AA05: flag if attachment carries active injection indicators via OCR/QR channel.
            _aa05_signals = []
            if att.get("qr_prompt_injection") or (att.get("steg_suspicious") and extracted_text):
                _aa05_signals.append("qr_or_steg_injection_channel_active")
            if re.search(r"(?i)(ignore\s+previous|system\s*prompt|developer\s+mode|do\s+not\s+follow)", extracted_text):
                _aa05_signals.append("ocr_text_prompt_injection_pattern")
            summary[-1]["maestro_boundary_check"] = {
                "agent": "attachment_forensics_agent",
                "tools_validated": _att_tools_used,
                "scope_enforced": len(_att_violations) == 0,
                "scope_violations": _att_violations,
                "owasp_agentic": ["AA03"] + (["AA05"] if _aa05_signals else []),
                "aa05_signals": _aa05_signals,
                "maestro_control": "SC-04B",
            }
        except Exception:
            pass
    return summary


def _sender_infrastructure_snapshot(
    email: Dict[str, Any],
    header_forensics: Dict[str, Any] | None,
) -> Dict[str, Any]:
    hdr = header_forensics if isinstance(header_forensics, dict) else {}
    from_addr = str(email.get("from_addr") or "").strip()
    reply_to = str(email.get("reply_to") or "").strip()
    sender_domain = str(extract_domain(from_addr) or "").strip().lower()
    reply_domain = str(extract_domain(reply_to) or "").strip().lower()
    originating_ip = str(hdr.get("originating_ip") or "").strip()
    geo = hdr.get("originating_ip_geo") if isinstance(hdr.get("originating_ip_geo"), dict) else {}
    geo_risk = float(geo.get("risk") or 0.0) if isinstance(geo, dict) else 0.0
    reputation_flags: list[str] = []
    if geo_risk >= 0.85:
        reputation_flags.append("high_geo_risk")
    elif geo_risk >= 0.65:
        reputation_flags.append("elevated_geo_risk")
    if bool(geo.get("is_tor")):
        reputation_flags.append("tor_exit_node")
    if bool(geo.get("is_vpn")):
        reputation_flags.append("vpn_or_proxy")
    if bool(geo.get("is_hosting")):
        reputation_flags.append("hosting_provider_origin")
    if bool(hdr.get("message_id_domain_mismatch")):
        reputation_flags.append("message_id_domain_mismatch")
    if bool(hdr.get("message_id_reuse")):
        reputation_flags.append("message_id_reuse")
    if bool(hdr.get("relay_count_anomaly")):
        reputation_flags.append("relay_chain_anomaly")
    if bool(hdr.get("timing_anomaly")):
        reputation_flags.append("header_timing_anomaly")
    related: Dict[str, Any] = {"count": 0, "matches": []}
    try:
        from sqlalchemy import text
        from src.app.models.db import db_session

        with db_session() as db:
            rows = db.execute(
                text(
                    """
                    SELECT id, severity, evidence_json
                    FROM email_security_incidents
                    ORDER BY created_at DESC
                    LIMIT 200
                    """
                )
            ).fetchall()
        matches: list[dict[str, Any]] = []
        seen: set[str] = set()
        for row in rows or []:
            incident_id = str(row[0] or "")
            severity = str(row[1] or "")
            try:
                evidence = json.loads(str(row[2] or "{}"))
            except Exception:
                evidence = {}
            sender = evidence.get("sender_infrastructure") if isinstance(evidence.get("sender_infrastructure"), dict) else {}
            hf = evidence.get("header_forensics") if isinstance(evidence.get("header_forensics"), dict) else {}
            sender_match = sender_domain and sender_domain == str(sender.get("sender_domain") or "").strip().lower()
            reply_match = reply_domain and reply_domain == str(sender.get("reply_domain") or "").strip().lower()
            ip_match = originating_ip and originating_ip == str((sender.get("originating_ip") or hf.get("originating_ip") or "")).strip()
            if sender_match or reply_match or ip_match:
                key = incident_id
                if key in seen:
                    continue
                seen.add(key)
                reason = []
                if sender_match:
                    reason.append("sender_domain")
                if reply_match:
                    reason.append("reply_domain")
                if ip_match:
                    reason.append("originating_ip")
                matches.append(
                    {
                        "incident_id": incident_id,
                        "severity": severity,
                        "match_on": reason,
                    }
                )
            if len(matches) >= 5:
                break
        related = {"count": len(matches), "matches": matches}
    except Exception:
        related = {"count": 0, "matches": []}

    return {
        "sender_address": from_addr or None,
        "reply_to": reply_to or None,
        "sender_domain": sender_domain or None,
        "reply_domain": reply_domain or None,
        "reply_domain_mismatch": bool(sender_domain and reply_domain and sender_domain != reply_domain),
        "originating_ip": originating_ip or None,
        "originating_geo": geo or {},
        "message_id_domain_mismatch": bool(hdr.get("message_id_domain_mismatch")),
        "message_id_reuse": bool(hdr.get("message_id_reuse")),
        "mailer_fingerprint": hdr.get("mailer_fingerprint"),
        "mailer_is_bulk": bool(hdr.get("mailer_is_bulk")),
        "reputation": {
            "risk_score": round(geo_risk, 4),
            "flags": reputation_flags,
            "known_bad": bool(any(flag in reputation_flags for flag in ("high_geo_risk", "tor_exit_node"))),
        },
        "related_incidents": related,
    }


def _attachment_baseline_diff_snapshot(email: Dict[str, Any]) -> Dict[str, Any]:
    attachments = [dict(a or {}) for a in (email.get("attachments") or []) if isinstance(a, dict)]
    pdfs = [a for a in attachments if "pdf" in str(a.get("content_type") or "").lower() or str(a.get("name") or "").lower().endswith(".pdf")]
    if len(pdfs) < 2:
        return {"baseline_file": None, "comparisons": []}

    def _risk_score(att: Dict[str, Any]) -> float:
        text = str(att.get("extracted_text") or "")
        name = str(att.get("name") or "").lower()
        score = 0.0
        if "fake" in name:
            score += 3.0
        if re.search(r"(?i)(bank(?:ing)?\s+details?\s+have\s+changed|disregard\s+(?:any\s+)?previous\s+remittance|new\s+account|updated\s+payment)", text):
            score += 3.0
        if int(att.get("embedded_files_count") or 0) > 0:
            score += 1.0
        if int(att.get("pdf_objstm_count") or 0) >= 3:
            score += 1.0
        return score

    baseline = sorted(pdfs, key=lambda a: (_risk_score(a), len(str(a.get("name") or ""))))[0]
    baseline_name = str(baseline.get("name") or "baseline.pdf")
    baseline_text = str(baseline.get("extracted_text") or "")
    baseline_bank = baseline.get("bank_fields") if isinstance(baseline.get("bank_fields"), dict) else {}
    baseline_urls = sorted(set(re.findall(r"https?://[^\s<>'\"`]+", baseline_text, re.IGNORECASE)))

    def _load_preview_b64(att: Dict[str, Any]) -> str:
        return str(att.get("preview_png_b64") or "").strip()

    def _build_pdf_visual_overlay(base_b64: str, cand_b64: str) -> Dict[str, Any]:
        if not base_b64 or not cand_b64:
            return {}
        try:
            from PIL import Image, ImageChops, ImageOps, ImageStat  # type: ignore

            b = Image.open(io.BytesIO(base64.b64decode(base_b64))).convert("RGB")
            c = Image.open(io.BytesIO(base64.b64decode(cand_b64))).convert("RGB").resize(b.size)
            overlay = Image.blend(b, c, 0.5)
            diff = ImageChops.difference(b, c)
            gray = ImageOps.grayscale(diff)
            bbox = gray.point(lambda p: 255 if p > 16 else 0).getbbox()
            heat = ImageOps.colorize(gray, black="#0f172a", white="#ff6a00")
            ov = io.BytesIO()
            hm = io.BytesIO()
            overlay.save(ov, format="PNG")
            heat.save(hm, format="PNG")
            stat = ImageStat.Stat(gray)
            return {
                "baseline_preview_b64": base_b64,
                "candidate_preview_b64": cand_b64,
                "overlay_preview_b64": base64.b64encode(ov.getvalue()).decode("ascii"),
                "heatmap_preview_b64": base64.b64encode(hm.getvalue()).decode("ascii"),
                "mean_pixel_diff": round(float(stat.mean[0] if stat.mean else 0.0), 3),
                "drift_bbox": [int(v) for v in bbox] if bbox else [],
                "drift_detected": bool(bbox),
            }
        except Exception:
            return {}

    comparisons: list[dict[str, Any]] = []
    for att in pdfs:
        if att is baseline:
            continue
        text = str(att.get("extracted_text") or "")
        bank = att.get("bank_fields") if isinstance(att.get("bank_fields"), dict) else {}
        urls = sorted(set(re.findall(r"https?://[^\s<>'\"`]+", text, re.IGNORECASE)))
        similarity = round(SequenceMatcher(a=baseline_text[:5000], b=text[:5000]).ratio(), 4) if (baseline_text or text) else 0.0
        differences: list[str] = []
        if str(att.get("template_hash") or "") != str(baseline.get("template_hash") or ""):
            differences.append("Template hash differs from the baseline PDF.")
        if str(att.get("layout_hash") or "") != str(baseline.get("layout_hash") or ""):
            differences.append("Layout hash differs from the baseline PDF.")
        if str(att.get("logo_hash") or "") != str(baseline.get("logo_hash") or ""):
            differences.append("Logo hash differs from the baseline PDF.")
        if bank != baseline_bank:
            differences.append("Bank or remittance fields differ from the baseline PDF.")
        if urls != baseline_urls:
            differences.append("Embedded URLs differ from the baseline PDF.")
        if str(att.get("pdf_producer") or "") != str(baseline.get("pdf_producer") or ""):
            differences.append("PDF producer metadata differs from the baseline PDF.")
        visual = _build_pdf_visual_overlay(_load_preview_b64(baseline), _load_preview_b64(att))
        comparisons.append(
            {
                "baseline_file": baseline_name,
                "candidate_file": str(att.get("name") or ""),
                "text_similarity": similarity,
                "baseline_bank_fields": baseline_bank,
                "candidate_bank_fields": bank,
                "baseline_urls": baseline_urls[:8],
                "candidate_urls": urls[:8],
                "differences": differences,
                **visual,
            }
        )
    return {"baseline_file": baseline_name, "comparisons": comparisons}


def _attachment_visual_diff_snapshot(email: Dict[str, Any]) -> Dict[str, Any]:
    attachments = [dict(a or {}) for a in (email.get("attachments") or []) if isinstance(a, dict)]
    images = [
        a for a in attachments
        if str(a.get("preview_png_b64") or "").strip()
        and (
            str(a.get("content_type") or "").lower().startswith("image/")
            or str(a.get("name") or "").lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"))
        )
    ]
    if len(images) < 2:
        return {"baseline_file": None, "comparisons": []}
    try:
        from PIL import Image, ImageChops, ImageOps, ImageStat  # type: ignore
    except Exception:
        return {"baseline_file": None, "comparisons": []}

    def _load_preview(att: Dict[str, Any]):
        raw = str(att.get("preview_png_b64") or "").strip()
        if not raw:
            return None
        try:
            return Image.open(io.BytesIO(base64.b64decode(raw))).convert("RGB")
        except Exception:
            return None

    def _risk_score(att: Dict[str, Any]) -> float:
        name = str(att.get("name") or "").lower()
        text = str(att.get("extracted_text") or "")
        score = 0.0
        if "baseline" in name:
            score -= 10.0
        if "adv" in name or "fake" in name:
            score += 2.0
        if re.search(r"(?i)(payment|account|bsb|bank(?:ing)?\s+details?)", text):
            score += 2.0
        return score

    baseline = sorted(images, key=lambda a: (_risk_score(a), len(str(a.get("name") or ""))))[0]
    baseline_img = _load_preview(baseline)
    if baseline_img is None:
        return {"baseline_file": None, "comparisons": []}

    comparisons: list[dict[str, Any]] = []
    for att in images:
        if att is baseline:
            continue
        cand_img = _load_preview(att)
        if cand_img is None:
            continue
        try:
            b = baseline_img.copy()
            c = cand_img.copy().resize(b.size)
            diff = ImageChops.difference(b, c)
            gray = ImageOps.grayscale(diff)
            stat = ImageStat.Stat(gray)
            mean_diff = float(stat.mean[0] if stat.mean else 0.0)
            bbox = gray.point(lambda p: 255 if p > 18 else 0).getbbox()
            heat = ImageOps.colorize(gray, black="#0f172a", white="#ff6a00")
            out = io.BytesIO()
            heat.save(out, format="PNG")
            comparisons.append(
                {
                    "baseline_file": str(baseline.get("name") or ""),
                    "candidate_file": str(att.get("name") or ""),
                    "baseline_preview_b64": str(baseline.get("preview_png_b64") or ""),
                    "candidate_preview_b64": str(att.get("preview_png_b64") or ""),
                    "diff_preview_b64": base64.b64encode(out.getvalue()).decode("ascii"),
                    "mean_pixel_diff": round(mean_diff, 3),
                    "drift_bbox": [int(v) for v in bbox] if bbox else [],
                    "drift_detected": bool(bbox),
                }
            )
        except Exception:
            continue
    return {"baseline_file": str(baseline.get("name") or ""), "comparisons": comparisons}
