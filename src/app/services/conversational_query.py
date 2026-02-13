from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Dict, Optional, Any

from sqlalchemy import text


class ConversationalQueryService:
    """Natural language interface to ShopSquire analytics (deterministic v1)."""

    QUERY_PATTERNS = {
        "why_rejected": r"why.*(reject|decline|deny)",
        "fraud_patterns": r"fraud.*(pattern|trend|week|month)",
        "approval_rate": r"approval.*(rate|percentage|by tier)",
        "approval_rate_by_agent": r"approval.*(rate|percentage).*(agent|by agent)",
        "top_products": r"(top|best).*(product|item|sku)",
        "top_products_by_tier": r"(top|best).*(product|item|sku).*(by tier|tier)",
        "decision_timeline": r"(show|what).*(decision|history).*(\d+)",
        "high_risk_decisions": r"(high|critical).*(risk).*(decision|decisions|week|last)",
    }

    def __init__(self, db) -> None:
        self.db = db

    def _classify_query(self, natural_query: str) -> Optional[str]:
        q = (natural_query or "").lower()
        for key, pattern in self.QUERY_PATTERNS.items():
            if re.search(pattern, q):
                return key
        return None

    def query(self, natural_query: str, tenant_id: str | None = None) -> Dict[str, Any]:
        query_type = self._classify_query(natural_query)
        handlers = {
            "why_rejected": self._explain_rejection,
            "fraud_patterns": self._fraud_analytics,
            "approval_rate": self._approval_metrics,
            "approval_rate_by_agent": self._approval_rate_by_agent,
            "top_products": self._product_rankings,
            "top_products_by_tier": self._top_products_by_tier,
            "decision_timeline": self._decision_history,
            "high_risk_decisions": self._high_risk_decisions,
        }
        handler = handlers.get(query_type)
        if handler is None:
            return {
                "status": "unhandled",
                "query_type": None,
                "message": "No deterministic handler matched. Escalate to analyst or LLM summary.",
                "handoff": "human",
            }
        return handler(natural_query, tenant_id)

    def _explain_rejection(self, query: str, tenant_id: str | None) -> Dict[str, Any]:
        # Best-effort: look for decision id in query
        m = re.search(r"(dec|decision)[-_ ]?([a-z0-9-]+)", query.lower())
        decision_id = m.group(2) if m else None
        if not decision_id:
            return {"status": "needs_params", "query_type": "why_rejected", "message": "Provide a decision id."}
        row = None
        try:
            row = self.db.execute(
                text("SELECT id, execution_status, policy_version, retrieved_context FROM decision_logs WHERE id = :id LIMIT 1"),
                {"id": decision_id},
            ).fetchone()
        except Exception:
            row = None
        if not row:
            return {"status": "not_found", "query_type": "why_rejected", "decision_id": decision_id}
        return {
            "status": "ok",
            "query_type": "why_rejected",
            "decision_id": row[0],
            "execution_status": row[1],
            "policy_version": row[2],
            "explanation": "Decision was rejected due to policy or risk evaluation. Inspect trace for details.",
        }

    def _fraud_analytics(self, query: str, tenant_id: str | None) -> Dict[str, Any]:
        since_7 = datetime.utcnow() - timedelta(days=7)
        since_14 = datetime.utcnow() - timedelta(days=14)
        try:
            dialect = getattr(self.db.bind.dialect, "name", "")
        except Exception:
            dialect = ""

        breakdown = {}
        by_day = []
        last_week = 0
        prev_week = 0

        if dialect == "postgresql":
            try:
                rows = self.db.execute(
                    text(
                        """
                        SELECT time_bucket('1 day', event_time) AS day, severity, COUNT(*) AS cnt
                        FROM security_events
                        WHERE event_time >= :since
                        GROUP BY day, severity
                        ORDER BY day DESC
                        """
                    ),
                    {"since": since_14},
                ).fetchall()
                for day, severity, cnt in rows:
                    by_day.append({"day": str(day), "severity": severity, "count": int(cnt or 0)})
                    breakdown[severity] = breakdown.get(severity, 0) + int(cnt or 0)
                row2 = self.db.execute(
                    text(
                        """
                        SELECT
                          SUM(CASE WHEN event_time >= :since_7 THEN 1 ELSE 0 END) AS last_week,
                          SUM(CASE WHEN event_time < :since_7 AND event_time >= :since_14 THEN 1 ELSE 0 END) AS prev_week
                        FROM security_events
                        WHERE event_time >= :since_14
                        """
                    ),
                    {"since_7": since_7, "since_14": since_14},
                ).fetchone()
                if row2:
                    last_week = int(row2[0] or 0)
                    prev_week = int(row2[1] or 0)
            except Exception:
                pass
        else:
            try:
                rows = self.db.execute(
                    text(
                        """
                        SELECT DATE(event_time) AS day, severity, COUNT(*) AS cnt
                        FROM security_events
                        WHERE event_time >= :since
                        GROUP BY day, severity
                        ORDER BY day DESC
                        """
                    ),
                    {"since": since_14.isoformat()},
                ).fetchall()
                for day, severity, cnt in rows:
                    by_day.append({"day": str(day), "severity": severity, "count": int(cnt or 0)})
                    breakdown[severity] = breakdown.get(severity, 0) + int(cnt or 0)
                row2 = self.db.execute(
                    text(
                        """
                        SELECT
                          SUM(CASE WHEN event_time >= :since_7 THEN 1 ELSE 0 END) AS last_week,
                          SUM(CASE WHEN event_time < :since_7 AND event_time >= :since_14 THEN 1 ELSE 0 END) AS prev_week
                        FROM security_events
                        WHERE event_time >= :since_14
                        """
                    ),
                    {"since_7": since_7.isoformat(), "since_14": since_14.isoformat()},
                ).fetchone()
                if row2:
                    last_week = int(row2[0] or 0)
                    prev_week = int(row2[1] or 0)
            except Exception:
                pass

        trend = "stable"
        if prev_week > 0:
            pct = round(((last_week - prev_week) / prev_week) * 100.0, 1)
            trend = f"{'up' if pct > 0 else 'down'} {abs(pct)}% vs prior week"
        elif last_week > 0:
            trend = "up vs prior week"

        return {
            "status": "ok",
            "query_type": "fraud_patterns",
            "window_days": 14,
            "summary": f"{last_week} security events in last 7 days",
            "breakdown": breakdown,
            "trend": trend,
            "by_day": by_day[:14],
        }

    def _approval_metrics(self, query: str, tenant_id: str | None) -> Dict[str, Any]:
        since = datetime.utcnow() - timedelta(days=7)
        tiers = []
        try:
            dialect = getattr(self.db.bind.dialect, "name", "")
        except Exception:
            dialect = ""
        try:
            if dialect == "postgresql":
                rows = self.db.execute(
                    text(
                        """
                        SELECT
                          COALESCE(retrieved_context->>'customer_tier', 'unknown') AS tier,
                          COUNT(*) AS total,
                          SUM(CASE WHEN execution_status IN ('approved','executed') THEN 1 ELSE 0 END) AS approved
                        FROM decision_logs
                        WHERE valid_from >= :since
                        GROUP BY tier
                        ORDER BY total DESC
                        """
                    ),
                    {"since": since},
                ).fetchall()
            else:
                rows = self.db.execute(
                    text(
                        """
                        SELECT
                          COALESCE(json_extract(retrieved_context, '$.customer_tier'), 'unknown') AS tier,
                          COUNT(*) AS total,
                          SUM(CASE WHEN execution_status IN ('approved','executed') THEN 1 ELSE 0 END) AS approved
                        FROM decision_logs
                        WHERE valid_from >= :since
                        GROUP BY tier
                        ORDER BY total DESC
                        """
                    ),
                    {"since": since.isoformat()},
                ).fetchall()
            for tier, total, approved in rows:
                total_i = int(total or 0)
                approved_i = int(approved or 0)
                rate = round((approved_i / total_i) * 100.0, 2) if total_i else 0.0
                tiers.append({"tier": tier or "unknown", "total": total_i, "approved": approved_i, "approval_rate": rate})
        except Exception:
            tiers = []

        total_all = sum(t["total"] for t in tiers) if tiers else 0
        approved_all = sum(t["approved"] for t in tiers) if tiers else 0
        overall_rate = round((approved_all / total_all) * 100.0, 2) if total_all else 0.0
        return {
            "status": "ok",
            "query_type": "approval_rate",
            "window_days": 7,
            "total": total_all,
            "approved": approved_all,
            "approval_rate": overall_rate,
            "by_tier": tiers,
            "tier_field": "customer_tier",
        }

    def _product_rankings(self, query: str, tenant_id: str | None) -> Dict[str, Any]:
        since = datetime.utcnow() - timedelta(days=7)
        products = []
        try:
            dialect = getattr(self.db.bind.dialect, "name", "")
        except Exception:
            dialect = ""
        if dialect == "postgresql":
            try:
                rows = self.db.execute(
                    text(
                        """
                        SELECT sku, COUNT(*) AS cnt
                        FROM (
                          SELECT jsonb_array_elements_text((proposed_action::jsonb)->'ranked_skus') AS sku
                          FROM decision_logs
                          WHERE valid_from >= :since
                        ) t
                        GROUP BY sku
                        ORDER BY cnt DESC
                        LIMIT 10
                        """
                    ),
                    {"since": since},
                ).fetchall()
                products = [{"sku": r[0], "count": int(r[1] or 0)} for r in rows]
            except Exception:
                products = []
        else:
            try:
                rows = self.db.execute(
                    text("SELECT proposed_action FROM decision_logs WHERE valid_from >= :since ORDER BY valid_from DESC LIMIT 2000"),
                    {"since": since.isoformat()},
                ).fetchall()
                counts: Dict[str, int] = {}
                for (blob,) in rows:
                    try:
                        import json as _json
                        action = _json.loads(blob or "{}")
                        skus = action.get("ranked_skus") or []
                        for sku in skus:
                            counts[str(sku)] = counts.get(str(sku), 0) + 1
                    except Exception:
                        continue
                products = [{"sku": sku, "count": cnt} for sku, cnt in sorted(counts.items(), key=lambda x: x[1], reverse=True)[:10]]
            except Exception:
                products = []

        return {
            "status": "ok",
            "query_type": "top_products",
            "window_days": 7,
            "products": products,
        }

    def _top_products_by_tier(self, query: str, tenant_id: str | None) -> Dict[str, Any]:
        since = datetime.utcnow() - timedelta(days=7)
        tiers = []
        try:
            dialect = getattr(self.db.bind.dialect, "name", "")
        except Exception:
            dialect = ""
        if dialect == "postgresql":
            try:
                rows = self.db.execute(
                    text(
                        """
                        SELECT customer_tier, sku, SUM(count) AS cnt
                        FROM top_products_by_tier_daily_mv
                        WHERE bucket >= :since
                        GROUP BY customer_tier, sku
                        ORDER BY customer_tier, cnt DESC
                        """
                    ),
                    {"since": since},
                ).fetchall()
                tier_map: Dict[str, list] = {}
                for tier, sku, cnt in rows:
                    tier_map.setdefault(tier or "unknown", []).append({"sku": sku, "count": int(cnt or 0)})
                tiers = [{"tier": t, "products": items[:10]} for t, items in tier_map.items()]
            except Exception:
                tiers = []
        else:
            try:
                rows = self.db.execute(
                    text("SELECT proposed_action, retrieved_context FROM decision_logs WHERE valid_from >= :since ORDER BY valid_from DESC LIMIT 2000"),
                    {"since": since.isoformat()},
                ).fetchall()
                tier_map: Dict[str, Dict[str, int]] = {}
                for action_blob, ctx_blob in rows:
                    try:
                        import json as _json
                        action = _json.loads(action_blob or "{}")
                        ctx = _json.loads(ctx_blob or "{}")
                        tier = ctx.get("customer_tier") or "unknown"
                        for sku in action.get("ranked_skus") or []:
                            tier_map.setdefault(tier, {})
                            tier_map[tier][str(sku)] = tier_map[tier].get(str(sku), 0) + 1
                    except Exception:
                        continue
                tiers = [
                    {"tier": t, "products": [{"sku": sku, "count": cnt} for sku, cnt in sorted(items.items(), key=lambda x: x[1], reverse=True)[:10]]}
                    for t, items in tier_map.items()
                ]
            except Exception:
                tiers = []
        return {
            "status": "ok",
            "query_type": "top_products_by_tier",
            "window_days": 7,
            "by_tier": tiers,
        }

    def _approval_rate_by_agent(self, query: str, tenant_id: str | None) -> Dict[str, Any]:
        since = datetime.utcnow() - timedelta(days=7)
        agents = []
        try:
            dialect = getattr(self.db.bind.dialect, "name", "")
        except Exception:
            dialect = ""
        try:
            if dialect == "postgresql":
                rows = self.db.execute(
                    text(
                        """
                        SELECT agent_name, SUM(total) AS total, SUM(approved) AS approved
                        FROM approvals_by_agent_hourly_mv
                        WHERE bucket >= :since
                        GROUP BY agent_name
                        ORDER BY total DESC
                        """
                    ),
                    {"since": since},
                ).fetchall()
            else:
                rows = self.db.execute(
                    text(
                        """
                        SELECT agent_name, COUNT(*) AS total,
                               SUM(CASE WHEN execution_status IN ('approved','executed') THEN 1 ELSE 0 END) AS approved
                        FROM decision_logs
                        WHERE valid_from >= :since
                        GROUP BY agent_name
                        ORDER BY total DESC
                        """
                    ),
                    {"since": since.isoformat()},
                ).fetchall()
            for agent, total, approved in rows:
                total_i = int(total or 0)
                approved_i = int(approved or 0)
                rate = round((approved_i / total_i) * 100.0, 2) if total_i else 0.0
                agents.append({"agent": agent, "total": total_i, "approved": approved_i, "approval_rate": rate})
        except Exception:
            agents = []
        return {
            "status": "ok",
            "query_type": "approval_rate_by_agent",
            "window_days": 7,
            "by_agent": agents,
        }

    def _decision_history(self, query: str, tenant_id: str | None) -> Dict[str, Any]:
        # Extract numeric id from query for placeholder
        m = re.search(r"(\\d+)", query)
        return {
            "status": "ok",
            "query_type": "decision_timeline",
            "decision_id": m.group(1) if m else None,
            "timeline": [],
        }

    def _high_risk_decisions(self, query: str, tenant_id: str | None) -> Dict[str, Any]:
        since = datetime.utcnow() - timedelta(days=7)
        rows = []
        try:
            dialect = getattr(self.db.bind.dialect, "name", "")
        except Exception:
            dialect = ""
        try:
            if dialect == "sqlite":
                sql = (
                    "SELECT id, valid_from, agent_name, execution_status, retrieved_context "
                    "FROM decision_logs "
                    "WHERE json_extract(retrieved_context, '$.risk_quantification.risk_band') = :band "
                    "AND valid_from >= :since "
                    "ORDER BY valid_from DESC LIMIT 50"
                )
                rows = self.db.execute(text(sql), {"band": "high", "since": since.isoformat()}).fetchall()
            else:
                sql = (
                    "SELECT id, valid_from, agent_name, execution_status, retrieved_context "
                    "FROM decision_logs "
                    "WHERE (retrieved_context->'risk_quantification'->>'risk_band') = :band "
                    "AND valid_from >= :since "
                    "ORDER BY valid_from DESC LIMIT 50"
                )
                rows = self.db.execute(text(sql), {"band": "high", "since": since.isoformat()}).fetchall()
        except Exception:
            rows = []
        return {
            "status": "ok",
            "query_type": "high_risk_decisions",
            "window_days": 7,
            "count": len(rows),
            "decisions": [
                {"decision_id": r[0], "valid_from": str(r[1]), "agent_name": r[2], "execution_status": r[3]}
                for r in rows
            ],
        }
