from __future__ import annotations

from typing import Any, Dict, List

from sqlalchemy import text

from src.app.models.db import db_session


def _ensure_table() -> None:
    try:
        with db_session() as db:
            db.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS threat_intel_indicators (
                        id TEXT PRIMARY KEY,
                        tenant_id TEXT,
                        indicator_type TEXT NOT NULL,
                        indicator_value TEXT NOT NULL,
                        verdict TEXT NOT NULL,
                        confidence REAL NOT NULL DEFAULT 0.9,
                        source TEXT,
                        notes TEXT,
                        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                        updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
            )
            db.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS idx_ti_unique ON threat_intel_indicators(tenant_id, indicator_type, indicator_value)"
                )
            )
            db.commit()
    except Exception:
        pass


def upsert_indicator(
    *,
    id: str,
    tenant_id: str | None,
    indicator_type: str,
    indicator_value: str,
    verdict: str,
    confidence: float = 0.9,
    source: str | None = None,
    notes: str | None = None,
) -> bool:
    _ensure_table()
    try:
        with db_session() as db:
            db.execute(
                text(
                    """
                    INSERT INTO threat_intel_indicators
                    (id, tenant_id, indicator_type, indicator_value, verdict, confidence, source, notes, created_at, updated_at)
                    VALUES
                    (:id, :tenant_id, :indicator_type, :indicator_value, :verdict, :confidence, :source, :notes, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    ON CONFLICT(tenant_id, indicator_type, indicator_value)
                    DO UPDATE SET
                        verdict = excluded.verdict,
                        confidence = excluded.confidence,
                        source = excluded.source,
                        notes = excluded.notes,
                        updated_at = CURRENT_TIMESTAMP
                    """
                ),
                {
                    "id": id,
                    "tenant_id": tenant_id,
                    "indicator_type": indicator_type,
                    "indicator_value": indicator_value,
                    "verdict": verdict,
                    "confidence": float(max(0.0, min(1.0, confidence))),
                    "source": source,
                    "notes": notes,
                },
            )
            db.commit()
        return True
    except Exception:
        return False


def list_indicators(*, tenant_id: str | None, limit: int = 200) -> List[Dict[str, Any]]:
    _ensure_table()
    lim = max(1, min(int(limit or 200), 2000))
    try:
        with db_session() as db:
            rows = db.execute(
                text(
                    """
                    SELECT id, tenant_id, indicator_type, indicator_value, verdict, confidence, source, notes, created_at, updated_at
                    FROM threat_intel_indicators
                    WHERE (:tenant_id IS NULL OR tenant_id = :tenant_id)
                    ORDER BY updated_at DESC
                    LIMIT :lim
                    """
                ),
                {"tenant_id": tenant_id, "lim": lim},
            ).fetchall()
    except Exception:
        rows = []
    out: List[Dict[str, Any]] = []
    for r in rows or []:
        out.append(
            {
                "id": r[0],
                "tenant_id": r[1],
                "indicator_type": r[2],
                "indicator_value": r[3],
                "verdict": r[4],
                "confidence": float(r[5] or 0.0),
                "source": r[6],
                "notes": r[7],
                "created_at": r[8],
                "updated_at": r[9],
            }
        )
    return out


def resolve_indicator(*, tenant_id: str | None, indicator_type: str, indicator_value: str) -> Dict[str, Any] | None:
    _ensure_table()
    try:
        with db_session() as db:
            row = db.execute(
                text(
                    """
                    SELECT verdict, confidence, source, notes
                    FROM threat_intel_indicators
                    WHERE indicator_type = :indicator_type
                      AND indicator_value = :indicator_value
                      AND (tenant_id = :tenant_id OR tenant_id IS NULL)
                    ORDER BY CASE WHEN tenant_id = :tenant_id THEN 0 ELSE 1 END, updated_at DESC
                    LIMIT 1
                    """
                ),
                {"tenant_id": tenant_id, "indicator_type": indicator_type, "indicator_value": indicator_value},
            ).fetchone()
    except Exception:
        row = None
    if not row:
        return None
    return {"verdict": row[0], "confidence": float(row[1] or 0.0), "source": row[2], "notes": row[3]}
