from __future__ import annotations

import json
import uuid
from typing import Any, Dict, Optional

from sqlalchemy import text

from src.app.models.db import db_session
from src.app.deps import redact_for_trace, security_sanitize
from src.app.services.playbook_engine import complete_playbook_run, link_posthoc_to_run
from src.app.observability.metrics import record_email_security_false_positive


def ensure_posthoc_table() -> None:
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
                    CREATE TABLE IF NOT EXISTS posthoc_outcomes (
                        id TEXT PRIMARY KEY,
                        decision_id TEXT,
                        outcome_type TEXT,
                        outcome_value TEXT,
                        evidence_json TEXT,
                        valid_from TEXT,
                        valid_to TEXT,
                        system_from TEXT,
                        system_to TEXT,
                        actor_id TEXT,
                        actor_role TEXT
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


def record_outcome(
    *,
    decision_id: str,
    outcome_type: str,
    outcome_value: str,
    evidence: Dict[str, Any] | None = None,
    actor_id: str | None = None,
    actor_role: str | None = None,
    playbook_run_id: str | None = None,
) -> Optional[str]:
    ensure_posthoc_table()
    now_ts = __import__("datetime").datetime.utcnow().isoformat()
    out_id = str(uuid.uuid4())
    safe_evidence = redact_for_trace(security_sanitize(evidence or {}))
    payload = {
        "id": out_id,
        "decision_id": decision_id,
        "outcome_type": outcome_type,
        "outcome_value": outcome_value,
        "evidence_json": json.dumps(safe_evidence, ensure_ascii=False),
        "valid_from": now_ts,
        "valid_to": "infinity",
        "system_from": now_ts,
        "system_to": "infinity",
        "actor_id": actor_id or "",
        "actor_role": actor_role or "",
    }
    try:
        with db_session() as db:
            db.execute(
                text(
                    """
                    INSERT INTO posthoc_outcomes (
                        id, decision_id, outcome_type, outcome_value, evidence_json,
                        valid_from, valid_to, system_from, system_to, actor_id, actor_role
                    ) VALUES (
                        :id, :decision_id, :outcome_type, :outcome_value, :evidence_json,
                        :valid_from, :valid_to, :system_from, :system_to, :actor_id, :actor_role
                    )
                    """
                ),
                payload,
            )
            try:
                db.commit()
            except Exception:
                pass
        try:
            link_posthoc_to_run(decision_id=decision_id, posthoc_outcome_id=out_id, outcome_value=outcome_value)
        except Exception:
            pass
        try:
            if playbook_run_id:
                complete_playbook_run(
                    run_id=str(playbook_run_id),
                    status="completed",
                    outcome=str(outcome_value),
                    posthoc_outcome_id=out_id,
                )
        except Exception:
            pass
        try:
            ov = str(outcome_value or "").strip().lower()
            if ov in ("false_positive", "incorrect"):
                tenant_id = None
                if isinstance(safe_evidence, dict):
                    tenant_id = safe_evidence.get("tenant_id")
                record_email_security_false_positive(str(tenant_id or "global"), ov)
        except Exception:
            pass
        return out_id
    except Exception:
        return None


def get_latest_outcome(decision_id: str) -> Optional[Dict[str, Any]]:
    try:
        with db_session() as db:
            row = db.execute(
                text(
                    """
                    SELECT id, decision_id, outcome_type, outcome_value, evidence_json, valid_from, actor_id, actor_role
                    FROM posthoc_outcomes
                    WHERE decision_id = :did
                    ORDER BY system_from DESC
                    LIMIT 1
                    """
                ),
                {"did": decision_id},
            ).fetchone()
        if not row:
            return None
        try:
            evidence = json.loads(row[4] or "{}")
        except Exception:
            evidence = {}
        return {
            "id": row[0],
            "decision_id": row[1],
            "outcome_type": row[2],
            "outcome_value": row[3],
            "evidence": evidence,
            "valid_from": row[5],
            "actor_id": row[6],
            "actor_role": row[7],
        }
    except Exception:
        return None
