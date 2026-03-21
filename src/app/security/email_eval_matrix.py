from __future__ import annotations

import base64
import hashlib
import json
from email import message_from_bytes as _message_from_bytes
from email import policy as _email_policy
from pathlib import Path
from typing import Any, Dict, Iterable, List

from src.app.security.email_security import evaluate_email_security


EMAIL2_ARTIFACTS = [
    "BEC-04_macro_invoice_specification.md",
    "EXECUTIVE_SUMMARY.md",
    "generate_adversarial_invoices.py",
    "invoice_adv_dct.png",
    "invoice_adv_fgsm.png",
    "invoice_adv_FULL_COMBO.png",
    "invoice_adv_logo.png",
    "invoice_adv_subtle.png",
    "invoice_baseline.png",
    "shopsquire_invoice_test_scenarios.md",
    "shopsquire_testing_guide_comprehensive.md",
    "supply_chain_dread_pasta_matrix.json",
    "supply_chain_framework_matrix.json",
]

AGENTS = [
    "sender_auth_agent",
    "attachment_forensics_agent",
    "baseline_agent",
    "correlation_agent",
    "explanation_agent",
    "playbook_agent",
]

THREAT_VECTORS = {
    "payment_diversion": {"finding_types": {"bank_detail_change", "payment_change_request"}},
    "baseline_drift": {"finding_types": {"baseline_mismatch", "baseline_drift", "attachment_visual_drift"}},
    "embedded_url_or_redirect": {"finding_types": {"attachment_url_exposure", "qr_redirect_risk"}},
    "sender_identity": {"finding_types": {"auth_failure_dmarc_alignment", "reply_drift", "infrastructure_anomaly"}},
    "campaign_overlap": {"finding_types": {"related_incident_overlap"}},
    "prompt_or_policy": {"reason_tokens": {"prompt", "llm_policy_gate_denied", "ocr_prompt_instruction"}},
}


def _parse_eml_to_email_dict(content: bytes) -> Dict[str, Any]:
    msg = _message_from_bytes(content, policy=_email_policy.compat32)
    from_addr = str(msg.get("From") or "")
    reply_to = str(msg.get("Reply-To") or "") or None
    subject = str(msg.get("Subject") or "")
    message_id = str(msg.get("Message-ID") or "") or None
    x_originating_ip = str(msg.get("X-Originating-IP") or "").strip("[]") or None
    headers: Dict[str, Any] = {}
    for key in msg.keys():
        val = msg.get(key)
        if val:
            headers[key] = str(val)
    body_parts: List[str] = []
    attachments: List[Dict[str, Any]] = []
    if msg.is_multipart():
        for part in msg.walk():
            ctype = str(part.get_content_type() or "")
            if part.get_filename():
                raw = part.get_payload(decode=True) or b""
                attachments.append(
                    {
                        "name": str(part.get_filename() or "attachment"),
                        "content_type": ctype,
                        "content_b64": base64.b64encode(raw).decode("ascii"),
                    }
                )
                continue
            if ctype.startswith("text/"):
                raw = part.get_payload(decode=True) or b""
                body_parts.append(raw.decode(part.get_content_charset() or "utf-8", errors="ignore"))
    else:
        raw = msg.get_payload(decode=True) or b""
        body_parts.append(raw.decode(msg.get_content_charset() or "utf-8", errors="ignore"))
    return {
        "from_addr": from_addr,
        "reply_to": reply_to,
        "subject": subject,
        "message_id": message_id,
        "body": "\n".join([p for p in body_parts if p]).strip(),
        "headers": headers,
        "x_originating_ip": x_originating_ip,
        "attachments": attachments,
    }


def _load_attachment(path: Path) -> Dict[str, Any]:
    blob = path.read_bytes()
    ctype = "application/octet-stream"
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        ctype = "application/pdf"
    elif suffix in {".png"}:
        ctype = "image/png"
    elif suffix in {".jpg", ".jpeg"}:
        ctype = "image/jpeg"
    elif suffix in {".md", ".txt", ".json", ".py"}:
        ctype = "text/plain"
    return {
        "name": path.name,
        "content_type": ctype,
        "content_b64": base64.b64encode(blob).decode("ascii"),
        "sha256": hashlib.sha256(blob).hexdigest(),
        "size_bytes": len(blob),
    }


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _default_fixture_paths() -> Dict[str, Path]:
    root = _repo_root()
    return {
        "email2_dir": root / "dump" / "email-2" / "files",
        "ingram_fake_pdf": root / "dump" / "IngramFake_March2026_Catalog.pdf",
        "ingram_real_pdf": root / "dump" / "IngramTech_March_Catalog.pdf",
    }


def _build_email2_case(base_dir: Path) -> Dict[str, Any]:
    eml_path = base_dir / "BEC-02_compromised_supplier_email.eml"
    email = _parse_eml_to_email_dict(eml_path.read_bytes())
    email["vendor_domain"] = "ingramfake.com.au"
    email["reply_to"] = email.get("reply_to") or "accounts@ingramfake.com.au"
    attachments = [a for a in (email.get("attachments") or []) if isinstance(a, dict)]
    for name in EMAIL2_ARTIFACTS:
        p = base_dir / name
        if p.exists():
            attachments.append(_load_attachment(p))
    email["attachments"] = attachments
    return email


def _build_pdf_pair_case(real_pdf: Path, fake_pdf: Path, *, ip: str | None = None) -> Dict[str, Any]:
    return {
        "from_addr": "accounts@ingramfake.com.au",
        "reply_to": "accounts@ingramfake.com.au",
        "subject": "[Accounts] New laptop stock | Ingram Fake",
        "body": "Please see the attached supplier catalogues and updated invoice details.",
        "vendor_domain": "ingramfake.com.au",
        "x_originating_ip": ip,
        "attachments": [_load_attachment(real_pdf), _load_attachment(fake_pdf)],
    }


def _vector_result(verdict: Dict[str, Any], vector_name: str, config: Dict[str, Any]) -> Dict[str, Any]:
    evidence = verdict.get("evidence_snapshot") if isinstance(verdict.get("evidence_snapshot"), dict) else {}
    findings = [f for f in (evidence.get("structured_findings") or []) if isinstance(f, dict)]
    reasons = {str(r or "") for r in (verdict.get("reasons") or [])}
    finding_types = {str(f.get("finding_type") or "") for f in findings}
    matched_findings = []
    if config.get("finding_types"):
        matched_findings.extend([f for f in findings if str(f.get("finding_type") or "") in set(config.get("finding_types") or set())])
    if config.get("reason_tokens"):
        tokens = set(config.get("reason_tokens") or set())
        for f in findings:
            blob = " ".join(
                [
                    str(f.get("finding_type") or ""),
                    str(f.get("summary") or ""),
                    " ".join([str(x) for x in (f.get("evidence") or [])]),
                    " ".join([str(x) for x in (f.get("policy_mapping") or [])]),
                ]
            ).lower()
            if any(tok.lower() in blob for tok in tokens):
                matched_findings.append(f)
    if not matched_findings and config.get("reason_tokens"):
        if any(any(tok.lower() in r.lower() for tok in (config.get("reason_tokens") or set())) for r in reasons):
            matched_findings = [{"finding_id": "reason_match", "summary": "Matched verdict reason token"}]
    return {
        "vector": vector_name,
        "detected": bool(matched_findings),
        "status": "pass" if matched_findings else "fail",
        "supporting_findings": [
            {
                "finding_id": str(f.get("finding_id") or ""),
                "finding_type": str(f.get("finding_type") or ""),
                "summary": str(f.get("summary") or ""),
            }
            for f in matched_findings[:5]
        ],
    }


def _agent_result(verdict: Dict[str, Any], agent_name: str) -> Dict[str, Any]:
    evidence = verdict.get("evidence_snapshot") if isinstance(verdict.get("evidence_snapshot"), dict) else {}
    findings = [f for f in (evidence.get("structured_findings") or []) if isinstance(f, dict)]
    agent_findings = [f for f in findings if str(f.get("agent_origin") or "") == agent_name]
    runs = [r for r in (evidence.get("agent_runs") or []) if isinstance(r, dict) and str(r.get("agent_name") or "") == agent_name]
    return {
        "agent": agent_name,
        "status": "pass" if agent_findings or runs else "fail",
        "finding_count": len(agent_findings),
        "run_count": len(runs),
        "top_summaries": [str(f.get("summary") or "") for f in agent_findings[:3]],
    }


def _file_result(verdict: Dict[str, Any], file_name: str) -> Dict[str, Any]:
    evidence = verdict.get("evidence_snapshot") if isinstance(verdict.get("evidence_snapshot"), dict) else {}
    findings = [f for f in (evidence.get("structured_findings") or []) if isinstance(f, dict)]
    per_file = [
        f for f in findings
        if str(((f.get("artifact_ref") or {}).get("file_name") or "")).lower() == file_name.lower()
    ]
    categories = sorted({str(f.get("finding_category") or "") for f in per_file if str(f.get("finding_category") or "").strip()})
    return {
        "file_name": file_name,
        "status": "pass" if per_file else "fail",
        "finding_count": len(per_file),
        "categories": categories,
        "top_findings": [str(f.get("finding_type") or "") for f in per_file[:5]],
    }


def _case_report(case_id: str, verdict: Dict[str, Any], files: Iterable[str]) -> Dict[str, Any]:
    evidence = verdict.get("evidence_snapshot") if isinstance(verdict.get("evidence_snapshot"), dict) else {}
    return {
        "case_id": case_id,
        "severity": str(verdict.get("severity") or ""),
        "route": str(verdict.get("route") or ""),
        "verdict_action": str(verdict.get("verdict_action") or ""),
        "action_lane": str(((verdict.get("action_policy") or {}).get("lane") or "")),
        "top_ranked_findings": [
            {
                "finding_type": str(f.get("finding_type") or ""),
                "artifact": str(((f.get("artifact_ref") or {}).get("file_name") or "")),
                "confidence": float(f.get("confidence_score") or 0.0),
                "category": str(f.get("finding_category") or ""),
            }
            for f in (evidence.get("top_ranked_findings") or [])[:3]
            if isinstance(f, dict)
        ],
        "agent_matrix": [_agent_result(verdict, agent) for agent in AGENTS],
        "threat_vector_matrix": [_vector_result(verdict, name, cfg) for name, cfg in THREAT_VECTORS.items()],
        "file_matrix": [_file_result(verdict, name) for name in files],
    }


def build_evaluation_report() -> Dict[str, Any]:
    paths = _default_fixture_paths()
    email2_dir = paths["email2_dir"]
    ingram_real = paths["ingram_real_pdf"]
    ingram_fake = paths["ingram_fake_pdf"]
    cases: List[Dict[str, Any]] = []

    if email2_dir.exists():
        email2 = _build_email2_case(email2_dir)
        email2_verdict = evaluate_email_security(email2, tenant_id="tenant-eval-email2")
        cases.append(_case_report("email2_full_pack", email2_verdict, ["BEC-02_compromised_supplier_email.eml", *EMAIL2_ARTIFACTS]))

    if ingram_real.exists() and ingram_fake.exists():
        pair = _build_pdf_pair_case(ingram_real, ingram_fake)
        pair_verdict = evaluate_email_security(pair, tenant_id="tenant-eval-ingram")
        cases.append(_case_report("ingram_pdf_pair", pair_verdict, [ingram_real.name, ingram_fake.name]))
        for ip in ("8.8.8.8", "185.220.101.1", "45.95.147.236", "1.1.1.1"):
            geo_case = _build_pdf_pair_case(ingram_real, ingram_fake, ip=ip)
            geo_verdict = evaluate_email_security(geo_case, tenant_id="tenant-eval-geo")
            cases.append(_case_report(f"ingram_pdf_pair_geo_{ip.replace('.', '_')}", geo_verdict, [ingram_real.name, ingram_fake.name]))

    summary = {
        "case_count": len(cases),
        "cases_with_errors": sum(1 for c in cases if c.get("severity") == "error"),
        "cases_with_payment_diversion": sum(
            1
            for c in cases
            if any(v.get("vector") == "payment_diversion" and v.get("status") == "pass" for v in (c.get("threat_vector_matrix") or []))
        ),
    }
    return {"summary": summary, "cases": cases}


def write_evaluation_report(report: Dict[str, Any], out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return out_path
