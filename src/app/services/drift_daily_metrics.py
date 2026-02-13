from __future__ import annotations

import hashlib
import json
import math
from datetime import date, timedelta
from typing import Any, Dict, Iterable, List, Optional, Tuple

from sqlalchemy import text as sql_text

from src.app.models.db import db_session


def _labels_hash(labels: Dict[str, Any]) -> Tuple[str, str]:
    try:
        payload = json.dumps(labels or {}, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    except Exception:
        payload = "{}"
    h = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return payload, h


def _dialect_name(db) -> str:
    try:
        bind = getattr(db, "get_bind", lambda: None)()
        return str(getattr(getattr(bind, "dialect", None), "name", "") or "").lower()
    except Exception:
        return ""


def _upsert_metric(
    *,
    db,
    tenant_id: Optional[str],
    day: str,
    domain: str,
    metric_key: str,
    metric_value: float,
    labels: Dict[str, Any],
) -> None:
    labels_json, labels_hash = _labels_hash(labels)
    metric_id = f"drift-{hashlib.sha1(f'{tenant_id}|{day}|{domain}|{metric_key}|{labels_hash}'.encode('utf-8')).hexdigest()[:20]}"
    dialect = _dialect_name(db)
    if dialect == "postgresql":
        db.execute(
            sql_text(
                """
                INSERT INTO drift_daily_metrics
                  (id, tenant_id, day, domain, metric_key, metric_value, labels_json, labels_hash, created_at, updated_at)
                VALUES
                  (:id, :tenant_id, :day, :domain, :metric_key, :metric_value, :labels_json, :labels_hash, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                ON CONFLICT (tenant_id, day, domain, metric_key, labels_hash)
                DO UPDATE SET
                  metric_value = EXCLUDED.metric_value,
                  labels_json = EXCLUDED.labels_json,
                  updated_at = CURRENT_TIMESTAMP
                """
            ),
            {
                "id": metric_id,
                "tenant_id": tenant_id,
                "day": day,
                "domain": domain,
                "metric_key": metric_key,
                "metric_value": float(metric_value),
                "labels_json": labels_json,
                "labels_hash": labels_hash,
            },
        )
        return

    # SQLite / other: best-effort insert or replace.
    try:
        db.execute(
            sql_text(
                """
                INSERT OR REPLACE INTO drift_daily_metrics
                  (id, tenant_id, day, domain, metric_key, metric_value, labels_json, labels_hash, created_at, updated_at)
                VALUES
                  (:id, :tenant_id, :day, :domain, :metric_key, :metric_value, :labels_json, :labels_hash, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """
            ),
            {
                "id": metric_id,
                "tenant_id": tenant_id,
                "day": day,
                "domain": domain,
                "metric_key": metric_key,
                "metric_value": float(metric_value),
                "labels_json": labels_json,
                "labels_hash": labels_hash,
            },
        )
    except Exception:
        # Fallback plain insert (may violate unique constraints in some DBs)
        db.execute(
            sql_text(
                """
                INSERT INTO drift_daily_metrics
                  (id, tenant_id, day, domain, metric_key, metric_value, labels_json, labels_hash, created_at, updated_at)
                VALUES
                  (:id, :tenant_id, :day, :domain, :metric_key, :metric_value, :labels_json, :labels_hash, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """
            ),
            {
                "id": metric_id,
                "tenant_id": tenant_id,
                "day": day,
                "domain": domain,
                "metric_key": metric_key,
                "metric_value": float(metric_value),
                "labels_json": labels_json,
                "labels_hash": labels_hash,
            },
        )


def recompute_daily_metrics(*, days: int = 30, tenant_id: Optional[str] = None) -> Dict[str, Any]:
    """Compute and persist daily aggregates for core demo domains.

    Domains covered (minimal MVP):
      - email_security: incidents by severity + playbook id
      - cv: evidence bundle counts + basic OCR field coverage
    """
    days = max(1, min(int(days or 30), 365))
    cutoff = (date.today() - timedelta(days=days)).isoformat()

    written = 0
    with db_session() as db:
        # 1) Email Security incidents: counts by day+severity and playbook
        try:
            rows = db.execute(
                sql_text(
                    """
                    SELECT substr(created_at, 1, 10) AS day, severity, playbook_id, COUNT(*) AS cnt
                    FROM email_security_incidents
                    WHERE substr(created_at, 1, 10) >= :cutoff
                    GROUP BY substr(created_at, 1, 10), severity, playbook_id
                    """
                ),
                {"cutoff": cutoff},
            ).fetchall()
        except Exception:
            rows = []
        for r in rows or []:
            try:
                day, severity, playbook_id, cnt = r[0], r[1], r[2], r[3]
                _upsert_metric(
                    db=db,
                    tenant_id=tenant_id,
                    day=str(day),
                    domain="email_security",
                    metric_key="incidents_total",
                    metric_value=float(cnt or 0),
                    labels={"severity": severity or "unknown", "playbook_id": playbook_id or None},
                )
                written += 1
            except Exception:
                continue

        # 2) CV evidence bundles: daily counts + OCR field coverage (from `cv_pipeline`)
        try:
            ev_rows = db.execute(
                sql_text(
                    """
                    SELECT substr(created_at, 1, 10) AS day, bundle_json
                    FROM evidence_bundles
                    WHERE substr(created_at, 1, 10) >= :cutoff
                    ORDER BY created_at DESC
                    LIMIT 5000
                    """
                ),
                {"cutoff": cutoff},
            ).fetchall()
        except Exception:
            ev_rows = []

        cv_counts: Dict[Tuple[str, str], int] = {}
        cv_coverage: Dict[Tuple[str, str, str], int] = {}
        cv_manip_buckets: Dict[Tuple[str, str, str], int] = {}
        for r in ev_rows or []:
            try:
                day = str(r[0] or "")[:10]
                bundle = json.loads(r[1] or "{}") if isinstance(r[1], str) else (r[1] or {})
                if not isinstance(bundle, dict):
                    continue
                cv = bundle.get("cv") or {}
                if not isinstance(cv, dict):
                    continue
                pack_id = str(cv.get("pack_id") or "unknown")
                cv_counts[(day, pack_id)] = cv_counts.get((day, pack_id), 0) + 1
                fields = cv.get("fields") or {}
                if isinstance(fields, dict):
                    for k in ("order_id", "serial"):
                        if fields.get(k):
                            cv_coverage[(day, pack_id, k)] = cv_coverage.get((day, pack_id, k), 0) + 1
                # Optional Tier2 forensics bucketization (when present in evidence JSON).
                mscore = None
                try:
                    t2 = bundle.get("cv_tier2") or {}
                    if isinstance(t2, dict):
                        imgs = t2.get("images") or []
                        if isinstance(imgs, list) and imgs:
                            f0 = (imgs[0].get("forensics") or {}) if isinstance(imgs[0], dict) else {}
                            if isinstance(f0, dict):
                                mscore = f0.get("manipulation_score")
                except Exception:
                    mscore = None
                try:
                    if mscore is not None:
                        v = float(mscore)
                        if v < 0.2:
                            bkt = "0.0-0.2"
                        elif v < 0.4:
                            bkt = "0.2-0.4"
                        elif v < 0.6:
                            bkt = "0.4-0.6"
                        elif v < 0.8:
                            bkt = "0.6-0.8"
                        else:
                            bkt = "0.8-1.0"
                        cv_manip_buckets[(day, pack_id, bkt)] = cv_manip_buckets.get((day, pack_id, bkt), 0) + 1
                except Exception:
                    pass
            except Exception:
                continue

        for (day, pack_id), cnt in cv_counts.items():
            _upsert_metric(
                db=db,
                tenant_id=tenant_id,
                day=day,
                domain="cv",
                metric_key="evidence_with_cv_total",
                metric_value=float(cnt),
                labels={"pack_id": pack_id},
            )
            written += 1
        for (day, pack_id, field), cnt in cv_coverage.items():
            _upsert_metric(
                db=db,
                tenant_id=tenant_id,
                day=day,
                domain="cv",
                metric_key="cv_field_present_total",
                metric_value=float(cnt),
                labels={"pack_id": pack_id, "field": field},
            )
            written += 1
        for (day, pack_id, bucket), cnt in cv_manip_buckets.items():
            _upsert_metric(
                db=db,
                tenant_id=tenant_id,
                day=day,
                domain="cv",
                metric_key="manipulation_score_bucket_total",
                metric_value=float(cnt),
                labels={"pack_id": pack_id, "bucket": bucket},
            )
            written += 1

        try:
            db.commit()
        except Exception:
            pass

    # Optional calibration snapshots in the same job run.
    try:
        cal = recompute_calibration_snapshots(days=days, tenant_id=tenant_id)
        written += int(cal.get("written") or 0)
    except Exception:
        pass
    return {"status": "ok", "days": days, "cutoff": cutoff, "written": written}


def query_daily_metrics(*, domain: Optional[str] = None, days: int = 30, tenant_id: Optional[str] = None) -> Dict[str, Any]:
    days = max(1, min(int(days or 30), 365))
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    with db_session() as db:
        params: Dict[str, Any] = {"cutoff": cutoff}
        where = ["day >= :cutoff"]
        if domain:
            where.append("domain = :domain")
            params["domain"] = domain
        if tenant_id is not None:
            where.append("tenant_id = :tenant_id")
            params["tenant_id"] = tenant_id
        else:
            where.append("tenant_id IS NULL")

        sql = (
            "SELECT day, domain, metric_key, metric_value, labels_json "
            "FROM drift_daily_metrics "
            f"WHERE {' AND '.join(where)} "
            "ORDER BY day ASC"
        )
        try:
            rows = db.execute(sql_text(sql), params).fetchall()
        except Exception:
            rows = []

    items: List[Dict[str, Any]] = []
    for r in rows or []:
        try:
            labels = json.loads(r[4] or "{}") if isinstance(r[4], str) else (r[4] or {})
        except Exception:
            labels = {}
        items.append(
            {
                "day": r[0],
                "domain": r[1],
                "metric_key": r[2],
                "metric_value": float(r[3] or 0.0),
                "labels": labels if isinstance(labels, dict) else {},
            }
        )
    return {"status": "ok", "days": days, "domain": domain, "items": items}


def _ece_from_samples(samples: List[Tuple[float, float]], bins: int = 10) -> float:
    if not samples:
        return 0.0
    bins = max(2, min(int(bins or 10), 25))
    bucketed: Dict[int, List[Tuple[float, float]]] = {}
    for conf, acc in samples:
        c = max(0.0, min(1.0, float(conf)))
        b = min(bins - 1, int(c * bins))
        bucketed.setdefault(b, []).append((c, float(acc)))
    n = float(len(samples))
    ece = 0.0
    for _, vals in bucketed.items():
        if not vals:
            continue
        conf_avg = sum(v[0] for v in vals) / float(len(vals))
        acc_avg = sum(v[1] for v in vals) / float(len(vals))
        ece += (len(vals) / n) * abs(acc_avg - conf_avg)
    return float(ece)


def recompute_calibration_snapshots(*, days: int = 30, tenant_id: Optional[str] = None) -> Dict[str, Any]:
    """Compute calibration snapshots (ECE proxies) for intent/CV/anomaly/recommendation."""
    days = max(1, min(int(days or 30), 365))
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    written = 0
    samples_by_domain: Dict[str, List[Tuple[float, float]]] = {
        "intent": [],
        "cv": [],
        "anomaly": [],
        "recommendation": [],
    }
    with db_session() as db:
        try:
            rows = db.execute(
                sql_text(
                    """
                    SELECT valid_from, agent_name, proposed_action, retrieved_context
                    FROM decision_logs
                    WHERE substr(valid_from, 1, 10) >= :cutoff
                    ORDER BY valid_from DESC
                    LIMIT 5000
                    """
                ),
                {"cutoff": cutoff},
            ).fetchall()
        except Exception:
            rows = []

    for r in rows or []:
        try:
            agent = str(r[1] or "").lower()
            pa = json.loads(r[2] or "{}") if isinstance(r[2], str) else (r[2] or {})
            rc = json.loads(r[3] or "{}") if isinstance(r[3], str) else (r[3] or {})
            conf = None
            acc = None
            dom = None
            if "recommend" in agent:
                dom = "recommendation"
                conf = float((pa.get("confidence") or 0.0))
                # Proxy accuracy: top result in stock.
                ranked = pa.get("ranked_skus") or []
                evidence = pa.get("evidence") or []
                if ranked and evidence and isinstance(evidence, list):
                    first = evidence[0] if isinstance(evidence[0], dict) else {}
                    acc = 1.0 if int(first.get("stock", 1) or 1) > 0 else 0.0
                else:
                    acc = 0.5
            elif "cv" in agent:
                dom = "cv"
                conf = float((pa.get("confidence") or rc.get("confidence") or 0.0))
                sev = str(pa.get("severity") or pa.get("verdict") or "").lower()
                acc = 1.0 if sev in ("valid", "approve", "accepted", "low_risk") else 0.0 if sev in ("deny", "fraud", "rejected") else 0.5
            elif "fraud" in agent or "inventory" in agent:
                dom = "anomaly"
                conf = float(pa.get("score") or pa.get("confidence") or rc.get("score") or 0.0)
                label = str(pa.get("label") or rc.get("label") or "").lower()
                acc = 1.0 if label in ("low", "normal", "ok") else 0.0 if label in ("high", "critical", "fraud") else 0.5
            elif "orchestrator" in agent:
                dom = "intent"
                conf = float(pa.get("intent_confidence") or rc.get("intent_confidence") or 0.0)
                acc = 1.0 if conf >= 0.7 else 0.0
            if dom and conf is not None and acc is not None:
                samples_by_domain.setdefault(dom, []).append((max(0.0, min(1.0, conf)), float(acc)))
        except Exception:
            continue

    today = date.today().isoformat()
    with db_session() as db:
        for dom, samples in samples_by_domain.items():
            if not samples:
                continue
            ece = _ece_from_samples(samples, bins=10)
            _upsert_metric(
                db=db,
                tenant_id=tenant_id,
                day=today,
                domain=dom,
                metric_key="calibration_ece",
                metric_value=float(ece),
                labels={"samples": len(samples)},
            )
            written += 1
        try:
            db.commit()
        except Exception:
            pass
    return {"status": "ok", "written": written, "days": days}
