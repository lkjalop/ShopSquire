from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Dict, List, Optional

from sqlalchemy import text

from src.app.config import get_settings, load_feature_flags
from src.app.feature_flags import get_flags as _ff_get_flags
from src.app.models.db import db_session
from src.app.observability.metrics import record_ticket
from src.app.services.decision_log import log_decision
from src.app.services.ticketing_connectors import create_jira_issue, create_servicenow_incident

_log = logging.getLogger(__name__)


@dataclass
class Ticket:
    id: str
    external_id: Optional[str]
    title: str
    description: str
    severity: str
    status: str


class TicketingAgent:
    """Persistent ticketing agent.

    Real tickets are DB-primary. In-memory fallback is reserved for rate-limited
    suppression tickets in local/dev-style environments only.
    """

    @staticmethod
    def _strict_persistence_required() -> bool:
        explicit = str(os.getenv("STRICT_TICKETING_PERSISTENCE", "") or "").strip().lower()
        if explicit in ("1", "true", "yes", "on"):
            return True
        if explicit in ("0", "false", "no", "off"):
            return False
        env = str(os.getenv("APP_ENV", "local") or "local").strip().lower()
        return env not in ("local", "dev", "development", "test", "testing")

    @staticmethod
    def _ensure_ticket_tables(db) -> None:
        try:
            if getattr(getattr(db, "bind", None), "dialect", None) is None:
                return
            if db.bind.dialect.name != "sqlite":
                return
            db.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS tickets (
                        id TEXT PRIMARY KEY,
                        external_id TEXT,
                        title TEXT NOT NULL,
                        description TEXT,
                        severity TEXT DEFAULT 'medium',
                        status TEXT DEFAULT 'open',
                        approval_required INTEGER DEFAULT 0,
                        trace_id TEXT,
                        tenant_id TEXT,
                        evidence TEXT,
                        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                        updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
            )
        except Exception:
            pass

    def create_ticket(
        self,
        title: str,
        description: str,
        severity: str,
        tenant_id: str | None = None,
        reason_code: str | None = None,
        trace_id: str | None = None,
        policy_version: str | None = None,
        cv_summary: Dict | None = None,
        customer_tier: str | None = None,
        playbook: Dict | None = None,
        evidence_snapshot: Dict | None = None,
        approval_required: bool = False,
    ) -> Ticket:
        try:
            flags = _ff_get_flags()
            rl = (flags or {}).get("TICKET_RATE_LIMIT", {"enabled": False, "per_min": 5})
            if rl.get("enabled"):
                tenant_key = tenant_id or "default"
                now = time.time()
                window = 60.0
                max_per_min = int(rl.get("per_min") or 5)
                try:
                    store = getattr(TicketingAgent, "_tenant_rl", {})
                except Exception:
                    store = {}
                bucket = store.get(tenant_key)
                if not bucket:
                    bucket = {"start": now, "count": 0}
                    store[tenant_key] = bucket
                if now - float(bucket.get("start", now)) >= window:
                    bucket["start"] = now
                    bucket["count"] = 0
                if int(bucket.get("count", 0)) >= max_per_min:
                    try:
                        from src.app.observability.telemetry import telemetry_emit

                        telemetry_emit(
                            {"type": "ticket_rate_limited", "tenant": tenant_key, "reason": "per_min_limit"},
                            severity="warning",
                            sourcetype="shopsquire:security",
                        )
                    except Exception:
                        pass
                    return Ticket(
                        id=f"RL-{int(time.time() * 1000)}",
                        external_id=None,
                        title=title,
                        description=description,
                        severity=severity,
                        status="rate_limited",
                    )
                bucket["count"] = int(bucket.get("count", 0)) + 1
                try:
                    setattr(TicketingAgent, "_tenant_rl", store)
                except Exception:
                    pass
        except Exception:
            pass

        tid = f"TKT-{int(time.time() * 1000)}"
        status = "pending_approval" if approval_required else "open"
        ticket = Ticket(id=tid, external_id=None, title=title, description=description, severity=severity, status=status)
        strict_persistence = self._strict_persistence_required()

        try:
            with db_session() as db:
                self._ensure_ticket_tables(db)
                db.execute(
                    text(
                        """
                        INSERT INTO tickets (id, external_id, title, description, severity, status, approval_required, trace_id, tenant_id, evidence)
                        VALUES (:id, :external_id, :title, :description, :severity, :status, :approval_required, :trace_id, :tenant_id, :evidence)
                        """
                    ),
                    {
                        "id": tid,
                        "external_id": None,
                        "title": title,
                        "description": description,
                        "severity": severity,
                        "status": status,
                        # The portable migration intentionally uses INTEGER so
                        # SQLite and PostgreSQL share one schema contract.
                        "approval_required": int(bool(approval_required)),
                        "trace_id": trace_id,
                        "tenant_id": tenant_id,
                        "evidence": json.dumps(evidence_snapshot or {}),
                    },
                )
                try:
                    db.commit()
                except Exception:
                    pass
        except Exception as db_exc:
            _log.error("ticketing: DB persist failed for %s (%s): %s", tid, severity, db_exc)
            if strict_persistence:
                raise RuntimeError(f"ticket_persistence_failed:{tid}") from db_exc

        try:
            record_ticket("security", "P1" if severity in ("critical", "high") else "P3")
        except Exception:
            pass

        try:
            ext_id = None
            ext_id = ext_id or create_jira_issue(title, description, severity)
            ext_id = ext_id or create_servicenow_incident(title, description, severity)
            if ext_id:
                try:
                    with db_session() as db:
                        db.execute(text("UPDATE tickets SET external_id = :eid WHERE id = :id"), {"eid": ext_id, "id": tid})
                        db.commit()
                except Exception:
                    pass
        except Exception:
            pass

        try:
            log_decision(
                agent_name="ticketing_agent",
                input_data={
                    "title": title,
                    "severity": severity,
                    "reason_code": reason_code,
                    "trace_id": trace_id,
                    "policy_version": policy_version,
                    "customer_tier": customer_tier,
                },
                retrieved_context={
                    "description": description,
                    "cv_summary": cv_summary or {},
                    "playbook": playbook or {},
                    "evidence_snapshot": evidence_snapshot or {},
                },
                proposed_action={"ticket_id": tid, "status": status},
                agent_reasoning="auto ticket creation",
                policy_version=policy_version or "v1",
                approval_required=approval_required,
                execution_status="executed",
                tenant_id=tenant_id,
            )
        except Exception:
            pass
        return ticket

    def get_ticket(self, ticket_id: str) -> Optional[Ticket]:
        try:
            with db_session() as db:
                self._ensure_ticket_tables(db)
                row = db.execute(
                    text("SELECT id, external_id, title, description, severity, status FROM tickets WHERE id = :id"),
                    {"id": ticket_id},
                ).fetchone()
                if row:
                    return Ticket(id=row[0], external_id=row[1], title=row[2], description=row[3], severity=row[4], status=row[5])
        except Exception:
            if self._strict_persistence_required():
                return None
        try:
            return TicketingAgent._tickets.get(ticket_id)
        except Exception:
            return None

    def list_tickets(self, status: str | None = None) -> List[Ticket]:
        results: List[Ticket] = []
        try:
            with db_session() as db:
                self._ensure_ticket_tables(db)
                if status:
                    rows = db.execute(
                        text("SELECT id, external_id, title, description, severity, status FROM tickets WHERE status = :st ORDER BY created_at DESC LIMIT 100"),
                        {"st": status},
                    ).fetchall()
                else:
                    rows = db.execute(
                        text("SELECT id, external_id, title, description, severity, status FROM tickets ORDER BY created_at DESC LIMIT 200")
                    ).fetchall()
                for row in rows:
                    results.append(Ticket(id=row[0], external_id=row[1], title=row[2], description=row[3], severity=row[4], status=row[5]))
                return results
        except Exception:
            if self._strict_persistence_required():
                return results
            try:
                for ticket in list(getattr(TicketingAgent, "_tickets", {}).values()):
                    if status is None or ticket.status == status:
                        results.append(ticket)
            except Exception:
                pass
        return results

    def approve_ticket(self, ticket_id: str) -> bool:
        try:
            updated = False
            try:
                with db_session() as db:
                    self._ensure_ticket_tables(db)
                    res = db.execute(text("UPDATE tickets SET status = :st WHERE id = :id"), {"st": "approved", "id": ticket_id})
                    try:
                        db.commit()
                    except Exception:
                        pass
                    if getattr(res, "rowcount", None) and res.rowcount > 0:
                        updated = True
            except Exception:
                updated = False

            if not updated and self._strict_persistence_required():
                return False
            if not updated:
                t = TicketingAgent._tickets.get(ticket_id)
                if not t:
                    return False
                t.status = "approved"

            try:
                log_decision(
                    agent_name="ticketing_agent",
                    input_data={"ticket_id": ticket_id, "action": "approve"},
                    retrieved_context={},
                    proposed_action={"ticket_id": ticket_id, "status": "approved"},
                    agent_reasoning="manual_approval",
                    policy_version="v1",
                    approval_required=False,
                    execution_status="executed",
                )
            except Exception:
                pass

            try:
                trace_id = None
                with db_session() as db:
                    self._ensure_ticket_tables(db)
                    row = db.execute(text("SELECT trace_id FROM tickets WHERE id = :id"), {"id": ticket_id}).fetchone()
                    if row:
                        trace_id = row[0]
                if trace_id:
                    try:
                        with db_session() as db:
                            db.execute(
                                text("UPDATE decision_logs SET approved_at = CURRENT_TIMESTAMP, execution_status = 'approved' WHERE id = :id"),
                                {"id": trace_id},
                            )
                            db.commit()
                    except Exception:
                        pass
                    try:
                        import asyncio
                        from src.app.services.trace_broker import publish as publish_trace

                        evt = {
                            "id": f"evt-{int(time.time() * 1000)}",
                            "trace_id": trace_id,
                            "event_type": "ticket_approved",
                            "source_type": "human",
                            "source_id": "admin",
                            "target_type": "decision",
                            "target_id": trace_id,
                            "payload": {"ticket_id": ticket_id, "status": "approved"},
                            "created_at": int(time.time()),
                        }
                        try:
                            loop = asyncio.get_running_loop()
                            loop.create_task(publish_trace(trace_id, evt))
                        except RuntimeError:
                            asyncio.run(publish_trace(trace_id, evt))
                    except Exception as broker_exc:
                        _log.debug("ticketing: broker publish skipped: %s", broker_exc)
            except Exception:
                pass
            return True
        except Exception:
            return False

    def close_ticket(self, ticket_id: str) -> bool:
        try:
            updated = False
            try:
                with db_session() as db:
                    self._ensure_ticket_tables(db)
                    res = db.execute(text("UPDATE tickets SET status = :st WHERE id = :id"), {"st": "closed", "id": ticket_id})
                    try:
                        db.commit()
                    except Exception:
                        pass
                    if getattr(res, "rowcount", None) and res.rowcount > 0:
                        updated = True
            except Exception:
                updated = False

            if not updated and self._strict_persistence_required():
                return False
            if not updated:
                try:
                    t = TicketingAgent._tickets.get(ticket_id)
                    if not t:
                        return False
                    t.status = "closed"
                except Exception:
                    return False

            try:
                log_decision(
                    agent_name="ticketing_agent",
                    input_data={"ticket_id": ticket_id, "action": "close"},
                    retrieved_context={},
                    proposed_action={"ticket_id": ticket_id, "status": "closed"},
                    agent_reasoning="auto_close_on_po",
                    policy_version="v1",
                    approval_required=False,
                    execution_status="executed",
                )
            except Exception:
                pass
            return True
        except Exception:
            return False
