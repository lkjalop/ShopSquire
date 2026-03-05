"""DREAD historical calibration — logs predicted vs actual damage on incident closure.

After enough incidents are closed with ``actual_damage`` scores, the
calibration data can be analysed to produce per-signal-type correction
factors (Bayesian update) that adjust ``dread_scorer`` base rates.
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Dict, Optional

_log = logging.getLogger("shopsquire.dread_calibration")


def _ensure_table() -> None:
    try:
        from src.app.models.db import db_session
        from sqlalchemy import text
        with db_session() as db:
            db.execute(text(
                "CREATE TABLE IF NOT EXISTS dread_calibration_log ("
                "  id TEXT PRIMARY KEY,"
                "  incident_id TEXT,"
                "  trace_id TEXT,"
                "  predicted_damage REAL,"
                "  predicted_reproducibility REAL,"
                "  predicted_exploitability REAL,"
                "  predicted_affected_users REAL,"
                "  predicted_discoverability REAL,"
                "  predicted_weighted_avg REAL,"
                "  predicted_kill_chain_stage TEXT,"
                "  actual_damage REAL,"
                "  actual_impact_notes TEXT,"
                "  signal_types TEXT,"
                "  closed_by TEXT,"
                "  created_at TEXT DEFAULT CURRENT_TIMESTAMP"
                ")"
            ))
            db.commit()
    except Exception:
        pass


def log_calibration(
    *,
    incident_id: str,
    trace_id: str | None = None,
    dread: Dict[str, Any] | None = None,
    actual_damage: float | None = None,
    actual_impact_notes: str | None = None,
    signal_types: list[str] | None = None,
    closed_by: str | None = None,
) -> Optional[str]:
    """Record a calibration entry when an incident is closed/resolved."""
    _ensure_table()
    dread = dread or {}
    entry_id = f"dcal-{uuid.uuid4().hex[:12]}"
    try:
        from src.app.models.db import db_session
        from sqlalchemy import text
        with db_session() as db:
            db.execute(text(
                "INSERT INTO dread_calibration_log "
                "(id, incident_id, trace_id, "
                " predicted_damage, predicted_reproducibility, predicted_exploitability, "
                " predicted_affected_users, predicted_discoverability, predicted_weighted_avg, "
                " predicted_kill_chain_stage, actual_damage, actual_impact_notes, signal_types, closed_by) "
                "VALUES "
                "(:id, :iid, :tid, :pd, :pr, :pe, :pa, :pdisc, :pw, :pkc, :ad, :notes, :sigs, :cb)"
            ), {
                "id": entry_id,
                "iid": incident_id,
                "tid": trace_id,
                "pd": float(dread.get("damage") or 0),
                "pr": float(dread.get("reproducibility") or 0),
                "pe": float(dread.get("exploitability") or 0),
                "pa": float(dread.get("affected_users") or 0),
                "pdisc": float(dread.get("discoverability") or 0),
                "pw": float(dread.get("weighted_avg") or dread.get("avg") or 0),
                "pkc": str(dread.get("kill_chain_stage") or ""),
                "ad": float(actual_damage) if actual_damage is not None else None,
                "notes": str(actual_impact_notes or "")[:1000],
                "sigs": json.dumps(signal_types[:50] if signal_types else []),
                "cb": str(closed_by or "")[:120],
            })
            db.commit()
        return entry_id
    except Exception:
        _log.debug("failed to log dread calibration", exc_info=True)
        return None


def get_calibration_summary(days: int = 90) -> Dict[str, Any]:
    """Return aggregate predicted vs actual damage stats for calibration review."""
    _ensure_table()
    try:
        from src.app.models.db import db_session
        from sqlalchemy import text
        with db_session() as db:
            rows = db.execute(text(
                "SELECT predicted_damage, predicted_weighted_avg, actual_damage, "
                "  predicted_kill_chain_stage, signal_types "
                "FROM dread_calibration_log "
                "WHERE actual_damage IS NOT NULL "
                "AND created_at >= datetime('now', :window) "
                "ORDER BY created_at DESC LIMIT 500"
            ), {"window": f"-{days} days"}).fetchall()
        if not rows:
            return {"entries": 0, "message": "No calibration data with actual damage scores yet."}
        import json as _json
        total_pred = 0.0
        total_actual = 0.0
        per_stage: Dict[str, list] = {}
        for r in rows:
            pd, pw, ad, stage, sigs_raw = float(r[0] or 0), float(r[1] or 0), float(r[2] or 0), str(r[3] or ""), r[4]
            total_pred += pd
            total_actual += ad
            per_stage.setdefault(stage, []).append({"predicted": pd, "actual": ad})
        n = len(rows)
        return {
            "entries": n,
            "avg_predicted_damage": round(total_pred / n, 2),
            "avg_actual_damage": round(total_actual / n, 2),
            "calibration_ratio": round(total_actual / total_pred, 3) if total_pred > 0 else None,
            "per_stage": {
                stage: {
                    "count": len(items),
                    "avg_predicted": round(sum(i["predicted"] for i in items) / len(items), 2),
                    "avg_actual": round(sum(i["actual"] for i in items) / len(items), 2),
                }
                for stage, items in per_stage.items()
            },
        }
    except Exception:
        _log.debug("calibration summary failed", exc_info=True)
        return {"entries": 0, "error": "query_failed"}
