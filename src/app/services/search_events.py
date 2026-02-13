from __future__ import annotations

import json
import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy import text

from src.app.models.db import db_session
from src.app.deps import redact_for_trace, security_sanitize, hash_uid, scrub_pii


def ensure_search_events_table() -> None:
    try:
        from src.app.models.db import get_engine

        eng = get_engine()
        try:
            if getattr(eng, "dialect", None) is not None and eng.dialect.name != "sqlite":
                return
        except Exception:
            pass
        with db_session() as db:
            db.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS search_events (
                        id TEXT PRIMARY KEY,
                        event_time TEXT DEFAULT CURRENT_TIMESTAMP,
                        uid_hash TEXT,
                        query TEXT,
                        filters_json TEXT,
                        result_skus_json TEXT,
                        result_count INTEGER,
                        view_mode TEXT,
                        trace_id TEXT,
                        session_id TEXT
                    )
                    """
                )
            )
            try:
                db.commit()
            except Exception:
                pass
    except Exception:
        pass


def log_search_event(
    *,
    uid: str,
    query: str,
    filters: Dict[str, Any] | None,
    result_skus: List[str] | None,
    view_mode: str | None,
    trace_id: str | None,
    session_id: str | None = None,
) -> Optional[str]:
    ensure_search_events_table()
    event_id = str(uuid.uuid4())
    safe_query = scrub_pii(query or "")
    safe_filters = redact_for_trace(security_sanitize(filters or {}))
    safe_skus = [str(s) for s in (result_skus or []) if s]
    payload = {
        "id": event_id,
        "uid_hash": hash_uid(uid),
        "query": safe_query,
        "filters_json": json.dumps(safe_filters, ensure_ascii=False),
        "result_skus_json": json.dumps(safe_skus, ensure_ascii=False),
        "result_count": len(safe_skus),
        "view_mode": view_mode or "",
        "trace_id": trace_id or "",
        "session_id": session_id or "",
    }
    try:
        with db_session() as db:
            db.execute(
                text(
                    """
                    INSERT INTO search_events (
                        id, uid_hash, query, filters_json, result_skus_json,
                        result_count, view_mode, trace_id, session_id
                    ) VALUES (
                        :id, :uid_hash, :query, :filters_json, :result_skus_json,
                        :result_count, :view_mode, :trace_id, :session_id
                    )
                    """
                ),
                payload,
            )
            try:
                db.commit()
            except Exception:
                pass
        return event_id
    except Exception:
        return None
