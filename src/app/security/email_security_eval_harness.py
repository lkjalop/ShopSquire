from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from src.app.security.email_security import evaluate_email_security


def default_redteam_corpus() -> List[Dict[str, Any]]:
    return [
        {
            "id": "rt-001-bec-wire",
            "label_malicious": True,
            "email": {
                "message_id": "<rt-001@x>",
                "from_addr": "ceo@micros0ft.com",
                "reply_to": "finance@evil-payments.example",
                "subject": "Urgent wire transfer",
                "body": "urgent wire transfer to updated beneficiary and do not call to verify",
                "dmarc_fail": True,
            },
        },
        {
            "id": "rt-002-lolbin",
            "label_malicious": True,
            "email": {
                "message_id": "<rt-002@x>",
                "from_addr": "alerts@vendor.example",
                "reply_to": "alerts@vendor.example",
                "subject": "security patch",
                "body": "powershell -EncodedCommand SQBFAFgA and certutil -decode payload.b64 payload.exe",
                "dmarc_fail": False,
            },
        },
        {
            "id": "rt-003-ransom",
            "label_malicious": True,
            "email": {
                "message_id": "<rt-003@x>",
                "from_addr": "ops@vendor.example",
                "reply_to": "ops@vendor.example",
                "subject": "production outage note",
                "body": "your files are encrypted and vssadmin delete shadows /all /quiet",
                "dmarc_fail": False,
            },
        },
        {
            "id": "rt-004-semantic-evasive",
            "label_malicious": True,
            "email": {
                "message_id": "<rt-004@x>",
                "from_addr": "ap@supplier.example",
                "reply_to": "ap@supplier.example",
                "subject": "Settlement alignment",
                "body": "use the new settlement account and route this transfer to the revised payee. skip voice confirmation.",
                "dmarc_fail": False,
            },
        },
        {
            "id": "rt-005-benign-order",
            "label_malicious": False,
            "email": {
                "message_id": "<rt-005@x>",
                "from_addr": "orders@trustedvendor.com",
                "reply_to": "orders@trustedvendor.com",
                "subject": "Order confirmation",
                "body": "standard order update for purchase order 1129 with normal terms",
                "dmarc_fail": False,
            },
        },
        {
            "id": "rt-006-benign-support",
            "label_malicious": False,
            "email": {
                "message_id": "<rt-006@x>",
                "from_addr": "support@partner.example",
                "reply_to": "support@partner.example",
                "subject": "Ticket update",
                "body": "your support ticket was updated and no action is required",
                "dmarc_fail": False,
            },
        },
    ]


def _predicted_positive(result: Dict[str, Any]) -> bool:
    route = str(result.get("route") or "")
    return route in ("human_review", "security_review")


def run_p0_eval(corpus: List[Dict[str, Any]] | None = None, *, tenant_id: str = "eval-p0") -> Dict[str, Any]:
    rows = corpus or default_redteam_corpus()
    tp = fp = tn = fn = 0
    per_case: List[Dict[str, Any]] = []
    for row in rows:
        case_id = str(row.get("id") or "unknown")
        label = bool(row.get("label_malicious"))
        out = evaluate_email_security(dict(row.get("email") or {}), tenant_id=tenant_id)
        pred = _predicted_positive(out)
        if label and pred:
            tp += 1
        elif (not label) and pred:
            fp += 1
        elif (not label) and (not pred):
            tn += 1
        else:
            fn += 1
        per_case.append(
            {
                "id": case_id,
                "label_malicious": label,
                "predicted_positive": pred,
                "route": out.get("route"),
                "severity": out.get("severity"),
                "reasons": out.get("reasons") or [],
                "semantic_bec_score": out.get("semantic_bec_score"),
                "yara_match_count": int((((out.get("evidence_snapshot") or {}).get("yara") or {}).get("match_count") or 0)),
            }
        )

    precision = float(tp / (tp + fp)) if (tp + fp) else 0.0
    recall = float(tp / (tp + fn)) if (tp + fn) else 0.0
    fpr = float(fp / (fp + tn)) if (fp + tn) else 0.0
    return {
        "summary": {
            "total": len(rows),
            "tp": tp,
            "fp": fp,
            "tn": tn,
            "fn": fn,
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "fpr": round(fpr, 4),
        },
        "cases": per_case,
    }


def write_p0_report(path: str | Path, report: Dict[str, Any]) -> str:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return str(p)
