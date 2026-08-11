from __future__ import annotations

from typing import Any, Dict, List
import json
from sqlalchemy import text

from src.app.models.db import db_session


def get_runtime_thresholds(tenant_id: str | None) -> Dict[str, float]:
    tenant = str(tenant_id or "default")
    out: Dict[str, float] = {}
    try:
        with db_session() as db:
            rows = db.execute(
                text(
                    """
                    SELECT threshold_key, threshold_value
                    FROM security_threshold_overrides
                    WHERE tenant_id=:tenant
                    """
                ),
                {"tenant": tenant},
            ).fetchall()
        for r in rows or []:
            out[str(r[0] or "")] = float(r[1] or 0.0)
    except Exception:
        pass
    return out


def _extract_tuning_rows(tenant: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    try:
        with db_session() as db:
            res = db.execute(
                text(
                    """
                    SELECT evidence_json, ground_truth
                    FROM email_security_incidents
                    WHERE tenant_id=:tenant
                      AND ground_truth IN ('true_positive', 'false_positive')
                    ORDER BY created_at DESC
                    LIMIT 500
                    """
                ),
                {"tenant": tenant},
            ).fetchall()
        for r in res or []:
            evidence = {}
            try:
                evidence = json.loads(r[0] or "{}")
            except Exception:
                evidence = {}
            rows.append({"evidence": evidence if isinstance(evidence, dict) else {}, "ground_truth": str(r[1] or "")})
    except Exception:
        pass
    return rows


def recompute_thresholds_from_corrections(tenant_id: str | None) -> Dict[str, Any]:
    tenant = str(tenant_id or "default")
    rows = _extract_tuning_rows(tenant)
    n = len(rows)
    if n < 8:
        return {"updated": False, "reason": "insufficient_samples", "sample_size": n, "tenant_id": tenant_id}

    tp = [x for x in rows if x.get("ground_truth") == "true_positive"]
    fp = [x for x in rows if x.get("ground_truth") == "false_positive"]
    tp_n = len(tp)
    fp_n = len(fp)

    current = get_runtime_thresholds(tenant_id)
    ioc_thr = float(current.get("ioc_fusion_malicious_threshold", 0.7))
    sender_thr = float(current.get("sender_trust_low_threshold", 0.35))

    fp_rate = float(fp_n) / float(max(1, n))
    tp_rate = float(tp_n) / float(max(1, n))
    if fp_rate >= 0.45:
        ioc_thr = min(0.9, ioc_thr + 0.05)
    elif tp_rate >= 0.75:
        ioc_thr = max(0.55, ioc_thr - 0.03)

    def _sender_score(item: Dict[str, Any]) -> float | None:
        try:
            ev = item.get("evidence") or {}
            st = ev.get("sender_trust") or {}
            val = st.get("sender_trust_score")
            return float(val) if val is not None else None
        except Exception:
            return None

    tp_scores = [s for s in (_sender_score(x) for x in tp) if s is not None]
    fp_scores = [s for s in (_sender_score(x) for x in fp) if s is not None]
    if fp_scores and tp_scores:
        fp_avg = sum(fp_scores) / float(len(fp_scores))
        tp_avg = sum(tp_scores) / float(len(tp_scores))
        if fp_avg > tp_avg:
            sender_thr = max(0.2, sender_thr - 0.04)
        elif tp_avg > fp_avg + 0.12:
            sender_thr = min(0.6, sender_thr + 0.03)

    updates = {
        "ioc_fusion_malicious_threshold": round(float(ioc_thr), 4),
        "sender_trust_low_threshold": round(float(sender_thr), 4),
    }
    try:
        with db_session() as db:
            for k, v in updates.items():
                db.execute(
                    text(
                        """
                        INSERT INTO security_threshold_overrides
                        (tenant_id, threshold_key, threshold_value, source, sample_size, updated_at)
                        VALUES (:tenant, :k, :v, :src, :n, CURRENT_TIMESTAMP)
                        ON CONFLICT(tenant_id, threshold_key) DO UPDATE SET
                          threshold_value=:v,
                          source=:src,
                          sample_size=:n,
                          updated_at=CURRENT_TIMESTAMP
                        """
                    ),
                    {"tenant": tenant, "k": k, "v": float(v), "src": "analyst_correction_loop", "n": n},
                )
            db.commit()
    except Exception:
        return {"updated": False, "reason": "db_error", "sample_size": n, "tenant_id": tenant_id}

    return {
        "updated": True,
        "tenant_id": tenant_id,
        "sample_size": n,
        "tp_count": tp_n,
        "fp_count": fp_n,
        "thresholds": updates,
    }
