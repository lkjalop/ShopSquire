#!/usr/bin/env python3
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

import requests


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
DUMP_EMAIL = ROOT / "dump" / "email"
REPORT = ROOT / "dump" / "EMAIL_LAB_TRAINING_REPORT.md"
API = os.getenv("EMAIL_LAB_BASE_URL", "http://127.0.0.1:8080").rstrip("/")
HEADERS = {"x-api-key": os.getenv("EMAIL_LAB_API_KEY", "local-developer-key"), "Content-Type": "application/json"}
TENANT = os.getenv("EMAIL_LAB_TENANT", "merchant-lab-tenant")


def _extract_between(text: str, start: str, end: str | None = None) -> str:
    i = text.find(start)
    if i < 0:
        return text
    s = text[i + len(start) :]
    if end:
        j = s.find(end)
        if j >= 0:
            return s[:j]
    return s


def _hdr_value(block: str, key: str, default: str = "") -> str:
    m = re.search(rf"(?im)^{re.escape(key)}:\s*(.+)$", block)
    return (m.group(1).strip() if m else default).strip()


def _read_md(name: str) -> str:
    return (DUMP_EMAIL / name).read_text(encoding="utf-8", errors="ignore")


def _pdf_attachment(name: str, content_type: str = "application/pdf") -> Dict[str, Any]:
    p = DUMP_EMAIL / name
    b = p.read_bytes()
    return {
        "name": p.name,
        "content_type": content_type,
        "size_bytes": len(b),
        "content_b64": base64.b64encode(b).decode("ascii"),
    }


def _build_payloads() -> List[Tuple[str, Dict[str, Any], str]]:
    s1 = _read_md("SAMPLE_01_Homoglyph_Payment_Redirect.md")
    s2 = _read_md("SAMPLE_02_Thread_Hijacking.md")
    s3 = _read_md("SAMPLE_03_CEO_Fraud.md")
    s4 = _read_md("SAMPLE_04_Email_C2_Beaconing.md")

    s1h = _extract_between(s1, "## Email Headers", "---")
    s2h = _extract_between(s2, "## Message 5: COMPROMISED (Attack Vector)", "### Email Body")
    s3h = _extract_between(s3, "## Email Headers", "---")

    out: List[Tuple[str, Dict[str, Any], str]] = []
    out.append(
        (
            "sample_01_homoglyph_payment_redirect",
            {
                "tenant_id": TENANT,
                "message_id": _hdr_value(s1h, "Message-ID", "<sample1@dump.local>"),
                "from_addr": _hdr_value(s1h, "From", "accounts@ingrаmmicro.com.au"),
                "reply_to": _hdr_value(s1h, "Reply-To", "accounts@ingrаmmicro.com.au"),
                "subject": _hdr_value(s1h, "Subject", "Updated Banking Details"),
                "body": s1[:8000],
                "external_sender": True,
                "dmarc_fail": True,
                "spf_result": "fail",
                "dkim_result": "fail",
                "dmarc_result": "fail",
                "dmarc_policy": "reject",
                "vendor_domain": "ingrammicro.com.au",
            },
            "true_positive",
        )
    )
    out.append(
        (
            "sample_02_thread_hijacking",
            {
                "tenant_id": TENANT,
                "message_id": _hdr_value(s2h, "Message-ID", "<sample2@dump.local>"),
                "from_addr": _hdr_value(s2h, "From", "sarah.chen@techsuppliers.com.au"),
                "reply_to": _hdr_value(s2h, "Reply-To", "sarah.chen@techsuppliers.com.au"),
                "subject": _hdr_value(s2h, "Subject", "RE: Q1 Hardware Procurement Discussion"),
                "body": s2[:9000],
                "external_sender": True,
                "dmarc_fail": False,
                "spf_result": "pass",
                "dkim_result": "pass",
                "dmarc_result": "pass",
                "dmarc_policy": "none",
                "vendor_domain": "techsuppliers.com.au",
                "bank_fingerprint": "bank-old-ts",
                "proposed_bank_fingerprint": "bank-new-ts",
                "prior_reply_chain_id": "thread-legit-ts",
                "reply_chain_id": "thread-hijacked-ts",
            },
            "true_positive",
        )
    )
    out.append(
        (
            "sample_03_ceo_fraud",
            {
                "tenant_id": TENANT,
                "message_id": _hdr_value(s3h, "Message-ID", "<sample3@dump.local>"),
                "from_addr": _hdr_value(s3h, "From", "kevin.urgent.request@gmail.com"),
                "reply_to": _hdr_value(s3h, "Reply-To", "k.chen.urgent@protonmail.com"),
                "subject": _hdr_value(s3h, "Subject", "URGENT - Confidential Wire Transfer Required"),
                "body": s3[:9000],
                "external_sender": True,
                "dmarc_fail": False,
                "spf_result": "pass",
                "dkim_result": "pass",
                "dmarc_result": "pass",
                "dmarc_policy": "none",
                "vendor_domain": "cyberstash.com",
            },
            "true_positive",
        )
    )
    out.append(
        (
            "sample_04_email_c2_beaconing",
            {
                "tenant_id": TENANT,
                "message_id": "<sample4@dump.local>",
                "from_addr": "product.sync@shopsquire.com",
                "reply_to": "product.sync@shopsquire.com",
                "subject": "sync_status_0247",
                "body": s4[:10000],
                "external_sender": False,
                "dmarc_fail": False,
                "spf_result": "pass",
                "dkim_result": "pass",
                "dmarc_result": "pass",
                "dmarc_policy": "none",
                "vendor_domain": "shopsquire.com",
            },
            "true_positive",
        )
    )
    out.append(
        (
            "pdf_qr_invoice",
            {
                "tenant_id": TENANT,
                "message_id": "<pdf1@dump.local>",
                "from_addr": "accounts@supplier.com",
                "reply_to": "accounts@supplier.com",
                "subject": "Invoice INV-2026-00847",
                "body": "Please process attached invoice update.",
                "external_sender": True,
                "dmarc_fail": False,
                "spf_result": "pass",
                "dkim_result": "pass",
                "dmarc_result": "pass",
                "dmarc_policy": "reject",
                "attachments": [_pdf_attachment("TEST_PDF_01_QR_Code_Invoice.pdf")],
            },
            "true_positive",
        )
    )
    out.append(
        (
            "pdf_catalogue_suspicious",
            {
                "tenant_id": TENANT,
                "message_id": "<pdf2@dump.local>",
                "from_addr": "catalog@supplier.com",
                "reply_to": "catalog@supplier.com",
                "subject": "Product catalogue refresh",
                "body": "Updated product catalogue attached.",
                "external_sender": True,
                "dmarc_fail": False,
                "spf_result": "pass",
                "dkim_result": "pass",
                "dmarc_result": "pass",
                "dmarc_policy": "reject",
                "attachments": [_pdf_attachment("TEST_PDF_02_Product_Catalogue_Suspicious.pdf")],
            },
            "true_positive",
        )
    )
    out.append(
        (
            "pdf_original_ingram_invoice",
            {
                "tenant_id": TENANT,
                "message_id": "<pdf3@dump.local>",
                "from_addr": "ap@ingrammicro.com.au",
                "reply_to": "ap@ingrammicro.com.au",
                "subject": "Account order request",
                "body": "Attached account order request for processing.",
                "external_sender": True,
                "dmarc_fail": False,
                "spf_result": "neutral",
                "dkim_result": "neutral",
                "dmarc_result": "quarantine",
                "dmarc_policy": "reject",
                "attachments": [_pdf_attachment("2026-02-10_Ingram__Account-Order-Request_.pdf")],
            },
            "true_positive",
        )
    )
    out.append(
        (
            "benign_control",
            {
                "tenant_id": TENANT,
                "message_id": "<benign@dump.local>",
                "from_addr": "ops@trusted-supplier.com",
                "reply_to": "ops@trusted-supplier.com",
                "subject": "Weekly stock ETA update",
                "body": "Weekly stock ETA update. No payment changes. No action required.",
                "external_sender": True,
                "dmarc_fail": False,
                "spf_result": "pass",
                "dkim_result": "pass",
                "dmarc_result": "pass",
                "dmarc_policy": "reject",
            },
            "false_positive",
        )
    )
    return out


def _hash16(v: str | None) -> str | None:
    if not v:
        return None
    return hashlib.sha256(v.encode("utf-8")).hexdigest()[:16]


def _post(path: str, payload: Dict[str, Any]) -> requests.Response:
    return requests.post(f"{API}{path}", headers=HEADERS, json=payload, timeout=40)


def _get(path: str) -> requests.Response:
    return requests.get(f"{API}{path}", headers=HEADERS, timeout=40)


def _run_stego_test() -> Dict[str, Any]:
    import io
    import numpy as np
    from PIL import Image
    from src.app.security.steg_detector import detect_steganography

    rng = np.random.default_rng(42)
    # Smooth natural-like gradient cover lowers baseline steg suspicion.
    x = np.linspace(0, 255, 128, dtype=np.uint8)
    y = np.linspace(0, 255, 128, dtype=np.uint8)
    xv, yv = np.meshgrid(x, y)
    cover = np.stack([xv, yv, ((xv // 2) + (yv // 2)).astype(np.uint8)], axis=2)
    steg = cover.copy()
    payload = rng.integers(0, 2, size=128 * 128 * 3 // 3, dtype=np.uint8)
    bits = payload
    flat = steg.reshape(-1)
    n = min(len(bits), len(flat))
    flat[:n] = (flat[:n] & 0xFE) | bits[:n]
    steg = flat.reshape(steg.shape)

    def _to_png(arr: np.ndarray) -> bytes:
        im = Image.fromarray(arr, mode="RGB")
        bio = io.BytesIO()
        im.save(bio, format="PNG")
        return bio.getvalue()

    cover_b = _to_png(cover)
    steg_b = _to_png(steg)
    cover_res = detect_steganography(cover_b)
    steg_res = detect_steganography(steg_b)
    return {
        "cover": {
            "score": float(getattr(cover_res, "steg_score", 0.0)),
            "suspicious": bool(getattr(cover_res, "is_suspicious", False)),
            "indicators": list(getattr(cover_res, "indicators", []) or []),
        },
        "stego": {
            "score": float(getattr(steg_res, "steg_score", 0.0)),
            "suspicious": bool(getattr(steg_res, "is_suspicious", False)),
            "indicators": list(getattr(steg_res, "indicators", []) or []),
        },
        "delta_score": round(float(getattr(steg_res, "steg_score", 0.0)) - float(getattr(cover_res, "steg_score", 0.0)), 4),
    }


def main() -> int:
    payloads = _build_payloads()
    results: List[Dict[str, Any]] = []

    for name, payload, label in payloads:
        r = _post("/api/v1/email_security/evaluate", payload)
        row: Dict[str, Any] = {"name": name, "status": r.status_code, "label_target": label}
        try:
            j = r.json()
        except Exception:
            j = {"error": r.text[:500]}
        row["route"] = j.get("route")
        row["severity"] = j.get("severity")
        row["decision_id"] = j.get("decision_id")
        row["message_id"] = str(payload.get("message_id") or "")
        row["message_id_hash"] = _hash16(row["message_id"])
        mg = j.get("ml_gate") if isinstance(j.get("ml_gate"), dict) else {}
        meta = mg.get("metadata") if isinstance(mg.get("metadata"), dict) else {}
        row["ml_model_source"] = meta.get("model_source")
        row["ml_decision"] = mg.get("decision")
        row["reasons"] = list(j.get("reasons") or [])[:8]
        row["ok"] = r.status_code == 200
        results.append(row)

    # Robust linkage: query DB by hashed message-id to find incident rows + evidence.
    incident_by_message_hash: Dict[str, Dict[str, Any]] = {}
    try:
        from sqlalchemy import text
        from src.app.models.db import db_session

        with db_session() as db:
            rows = db.execute(
                text(
                    """
                    SELECT id, message_id_hash, evidence_json
                    FROM email_security_incidents
                    WHERE tenant_id = :tenant
                    ORDER BY created_at DESC
                    LIMIT 800
                    """
                ),
                {"tenant": TENANT},
            ).fetchall()
        for rr in rows or []:
            ev = {}
            try:
                ev = json.loads(rr[2] or "{}")
            except Exception:
                ev = {}
            incident_by_message_hash[str(rr[1] or "")] = {"incident_id": str(rr[0] or ""), "evidence": ev}
    except Exception:
        incident_by_message_hash = {}

    tp_ids = []
    fp_ids = []
    for r in results:
        mh = str(r.get("message_id_hash") or "")
        meta = incident_by_message_hash.get(mh)
        iid = (meta or {}).get("incident_id") if isinstance(meta, dict) else None
        if not iid:
            continue
        ev = (meta or {}).get("evidence") if isinstance(meta, dict) else {}
        if isinstance(ev, dict):
            mg = ev.get("ml_gate") if isinstance(ev.get("ml_gate"), dict) else {}
            md = mg.get("metadata") if isinstance(mg.get("metadata"), dict) else {}
            if md.get("model_source"):
                r["ml_model_source"] = md.get("model_source")
            if mg.get("decision"):
                r["ml_decision"] = mg.get("decision")
        if r.get("label_target") == "true_positive":
            tp_ids.append(iid)
        else:
            fp_ids.append(iid)

    label_res: Dict[str, Any] = {}
    if tp_ids:
        rr = _post(
            "/api/v1/admin/email_security/feedback/bulk_label",
            {
                "incident_ids": tp_ids,
                "outcome_type": "analyst_review",
                "outcome_value": "true_positive",
                "actor_id": "merchant-email-lab",
                "actor_role": "developer",
                "reason_code": "lab_expected_malicious",
                "note": "dump/email threat corpus training",
            },
        )
        label_res["tp"] = rr.json() if rr.status_code == 200 else {"status": rr.status_code, "text": rr.text[:300]}
    if fp_ids:
        rr = _post(
            "/api/v1/admin/email_security/feedback/bulk_label",
            {
                "incident_ids": fp_ids,
                "outcome_type": "analyst_review",
                "outcome_value": "false_positive",
                "actor_id": "merchant-email-lab",
                "actor_role": "developer",
                "reason_code": "lab_benign_control",
                "note": "dump/email benign control training",
            },
        )
        label_res["fp"] = rr.json() if rr.status_code == 200 else {"status": rr.status_code, "text": rr.text[:300]}

    retrain = _post(
        "/api/v1/admin/email_security/ml_gate/retrain",
        {
            "tenant_id": TENANT,
            "limit": 6000,
            "min_samples": 20,
            "min_tenant_samples": 10,
            "output_path": "config/ml_decision_gate_model.json",
        },
    )
    retrain_json = retrain.json() if retrain.status_code == 200 else {"status": retrain.status_code, "text": retrain.text[:400]}

    shadow = _get(f"/api/v1/admin/email_security/ml_gate/shadow/summary?tenant_id={TENANT}&hours=168")
    drift = _get(f"/api/v1/admin/email_security/ml_gate/drift/alerts?tenant_id={TENANT}&hours=168")
    readiness = _get(f"/api/v1/admin/email_security/ops/readiness?tenant_id={TENANT}&hours=168")
    policy_targets = _get("/api/v1/admin/email_security/ml_gate/policy_targets")

    stego = _run_stego_test()

    lines = []
    lines.append("# Email Lab Training Report")
    lines.append("")
    lines.append(f"- API: `{API}`")
    lines.append(f"- Tenant: `{TENANT}`")
    lines.append(f"- Corpus path: `{DUMP_EMAIL}`")
    lines.append("")
    lines.append("## Evaluation Results")
    lines.append("")
    lines.append("| Sample | HTTP | Severity | Route | ML Decision | Model Source |")
    lines.append("|---|---:|---|---|---|---|")
    for r in results:
        lines.append(
            f"| {r.get('name')} | {r.get('status')} | {r.get('severity')} | {r.get('route')} | {r.get('ml_decision')} | {r.get('ml_model_source')} |"
        )
    lines.append("")
    lines.append("## Labeling + Retrain")
    lines.append("")
    lines.append("```json")
    lines.append(json.dumps({"labeling": label_res, "retrain": retrain_json}, indent=2))
    lines.append("```")
    lines.append("")
    lines.append("## Shadow + Drift + Readiness")
    lines.append("")
    lines.append("```json")
    lines.append(
        json.dumps(
            {
                "shadow": shadow.json() if shadow.status_code == 200 else {"status": shadow.status_code},
                "drift": drift.json() if drift.status_code == 200 else {"status": drift.status_code},
                "readiness": readiness.json() if readiness.status_code == 200 else {"status": readiness.status_code},
                "policy_targets": policy_targets.json() if policy_targets.status_code == 200 else {"status": policy_targets.status_code},
            },
            indent=2,
        )
    )
    lines.append("```")
    lines.append("")
    lines.append("## Steganography Test")
    lines.append("")
    lines.append("```json")
    lines.append(json.dumps(stego, indent=2))
    lines.append("```")
    lines.append("")
    lines.append("## Notes")
    lines.append("- Steganography detection currently validated via `src.app.security.steg_detector.detect_steganography`.")
    lines.append("- If you want stego to directly affect email verdict routing, wire `steg_detector` into the email attachment analysis path.")
    REPORT.write_text("\n".join(lines), encoding="utf-8")

    print(json.dumps({"report": str(REPORT), "evaluated": len(results), "labeled_tp": len(tp_ids), "labeled_fp": len(fp_ids), "retrain_updated": bool((retrain_json or {}).get("updated"))}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
