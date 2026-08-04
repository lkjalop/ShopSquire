"""Exception-queue resolver — the control-plane consumer that GUARANTEES every
non-execute authorization outcome reaches a terminal disposition (1.3 + 1.4).

The Authorization Engine writes one ``exception_queue`` row per non-execute
verdict. Without a consumer those rows sit ``open`` forever — which is exactly
the "no guaranteed terminal outcome" gap the autonomy decks flag. This module is
that consumer.

The mapping below is also the FORMAL EXCEPTION MODEL: every terminal outcome the
engine can emit maps to exactly one disposition, and an *unknown* terminal
fails CLOSED to governance (never silently "resolved"). That property is what the
terminality test asserts — no failure path can fall through to "done" by accident.

Dispositions:
  resolved          the autonomous system has fully handled it (reject/substitute/
                    quarantine/safe_pause/ask-customer) — nothing more to do.
  retry_scheduled   bounded automatic retry will re-attempt it (defer_retry).
  governance_open   routed to GOVERNANCE — the ONE allowed non-autonomous terminal
                    (a governance boundary, NOT a runtime employee gate).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict

_log = logging.getLogger("shopsquire.exception_resolver")

# Disposition statuses (also the values written to exception_queue.status)
DISP_RESOLVED = "resolved"
DISP_RETRY = "retry_scheduled"
DISP_GOVERNANCE = "governance_open"


@dataclass(frozen=True)
class ExceptionResolution:
    autonomous: bool          # resolvable WITHOUT a human in the runtime loop?
    resolution_status: str    # DISP_RESOLVED | DISP_RETRY | DISP_GOVERNANCE
    note: str


# The formal exception model: one row per terminal outcome the engine can emit.
TERMINAL_RESOLUTIONS: Dict[str, ExceptionResolution] = {
    "execute":                   ExceptionResolution(True,  DISP_RESOLVED,   "action executed"),
    "reject_under_policy":       ExceptionResolution(True,  DISP_RESOLVED,   "rejected per policy; requester/customer informed"),
    "request_customer_evidence": ExceptionResolution(True,  DISP_RESOLVED,   "customer asked for evidence; bounded wait, no employee gate"),
    "substitute":                ExceptionResolution(True,  DISP_RESOLVED,   "automatic substitute proposed"),
    "quarantine":                ExceptionResolution(True,  DISP_RESOLVED,   "subject quarantined; security observer notified"),
    "safe_pause":                ExceptionResolution(True,  DISP_RESOLVED,   "paused safely; re-evaluated on next signal"),
    "defer_retry":               ExceptionResolution(True,  DISP_RETRY,      "deferred for bounded automatic retry"),
    "escalate_governance":       ExceptionResolution(False, DISP_GOVERNANCE, "routed to GOVERNANCE (allowed non-runtime boundary)"),
    # ── procurement terminal failures (fulfillment FAILURE_STATES) — domain-blind outcome labels ──
    "no_approved_supplier":        ExceptionResolution(True, DISP_RESOLVED, "paused: no approved supplier; re-evaluated when coverage is added"),
    "recipient_blocked":           ExceptionResolution(True, DISP_RESOLVED, "blocked recipient rejected per allowlist policy"),
    "quote_expired":               ExceptionResolution(True, DISP_RESOLVED, "expired quote: paused; re-request on next cycle"),
    "quote_parse_failed":          ExceptionResolution(True, DISP_RETRY,    "unparseable supplier reply: deferred for re-parse"),
    "supplier_response_quarantined": ExceptionResolution(True, DISP_RESOLVED, "untrusted supplier reply quarantined; observer notified"),
    "delivery_constraint_unmet":   ExceptionResolution(True, DISP_RESOLVED, "delivery constraint unmet: paused for re-options"),
    "policy_blocked":              ExceptionResolution(True, DISP_RESOLVED, "blocked per policy; requester informed"),
    "buyer_declined":              ExceptionResolution(True, DISP_RESOLVED, "buyer declined; case closed safely"),
    # ── market-intel terminal failures ──
    "stale_signal":                ExceptionResolution(True, DISP_RESOLVED, "stale market signal quarantined"),
    "low_confidence_finding":      ExceptionResolution(True, DISP_RESOLVED, "below-confidence finding: no action (safe pause)"),
    "pipeline_error":              ExceptionResolution(True, DISP_RETRY,    "market pipeline error: deferred for bounded retry"),
}

# Canonical exception_queue columns (the schema the resolver + authz + the test agree on). enqueue_exception
# and ensure_exception_table own this so a domain (market/procurement) can queue without knowing the schema.
_EXC_COLUMNS = (
    ("id", "TEXT"), ("tenant_id", "TEXT"), ("domain", "TEXT"), ("ref_id", "TEXT"),
    ("trace_id", "TEXT"), ("action", "TEXT"), ("requester", "TEXT"),
    ("terminal_outcome", "TEXT"), ("reason", "TEXT"), ("subject_id", "TEXT"),
    ("value_usd", "REAL"), ("residual", "TEXT"), ("payload", "TEXT"),
    ("status", "TEXT"), ("resolved_outcome", "TEXT"),
    ("created_at", "TEXT"), ("resolved_at", "TEXT"),
)


def ensure_exception_table(db) -> None:
    """Create exception_queue with the canonical schema IF absent, and idempotently ADD any missing
    canonical column to a pre-existing (possibly divergent) table. This REPAIRS the legacy db.py schema
    that lacked terminal_outcome/resolved_outcome — without it the authz + domain enqueues silently fail."""
    from sqlalchemy import text as _t
    cols = ", ".join(f"{n} {ty}" for n, ty in _EXC_COLUMNS)
    db.execute(_t(f"CREATE TABLE IF NOT EXISTS exception_queue ({cols})"))
    try:
        from sqlalchemy import inspect as _inspect
        have = {c["name"] for c in _inspect(db.connection()).get_columns("exception_queue")}
    except Exception:
        return  # introspection unavailable → the CREATE above already has every column on a fresh table
    for name, ty in _EXC_COLUMNS:
        if name not in have:
            db.execute(_t(f"ALTER TABLE exception_queue ADD COLUMN {name} {ty}"))


def enqueue_exception(*, domain: str, terminal_outcome: str, ref_id=None, reason=None,
                      tenant_id: str = "default", trace_id=None) -> bool:
    """Queue one exception for the resolver — the domain-agnostic writer market-intel + procurement use so
    a terminal failure reaches a governed disposition instead of being silently swallowed. Best-effort;
    returns True on write. Never raises."""
    try:
        import uuid as _uuid
        from sqlalchemy import text as _t
        from src.app.models.db import db_session
        from src.app.security.authorization_engine import _now_iso
        with db_session() as db:
            ensure_exception_table(db)
            db.execute(
                _t("INSERT INTO exception_queue (id, tenant_id, domain, ref_id, terminal_outcome, reason, "
                   "status, created_at) VALUES (:id,:tn,:dm,:rf,:to,:rs,'open',:ts)"),
                {"id": str(_uuid.uuid4()), "tn": str(tenant_id or "default"), "dm": str(domain or ""),
                 "rf": (str(ref_id) if ref_id is not None else None), "to": str(terminal_outcome or ""),
                 "rs": (str(reason) if reason is not None else None), "ts": _now_iso()},
            )
            db.commit()
        return True
    except Exception as exc:
        _log.debug("enqueue_exception failed (%s/%s): %r", domain, terminal_outcome, exc)
        return False


def resolve_terminal(outcome: str) -> ExceptionResolution:
    """Map a terminal outcome to its disposition. Fail CLOSED: an un-modelled
    outcome is NOT silently resolved — it goes to governance so it surfaces."""
    res = TERMINAL_RESOLUTIONS.get(str(outcome or "").strip())
    if res is not None:
        return res
    return ExceptionResolution(False, DISP_GOVERNANCE, f"unknown terminal '{outcome}' — fail-closed to governance")


def resolve_open_exceptions(limit: int = 200) -> Dict[str, int]:
    """Drive every ``open`` exception_queue row to a terminal disposition.

    Best-effort + idempotent: only touches rows with status='open', so re-runs are
    safe. Returns a summary counter. Never raises."""
    summary = {"scanned": 0, DISP_RESOLVED: 0, DISP_RETRY: 0, DISP_GOVERNANCE: 0, "errors": 0}
    try:
        from sqlalchemy import text
        from src.app.models.db import db_session
        from src.app.security.authorization_engine import _now_iso
        with db_session() as db:
            ensure_exception_table(db)  # repair the schema (adds terminal_outcome/resolved_outcome if legacy)
            rows = db.execute(
                text(
                    "SELECT id, terminal_outcome FROM exception_queue "
                    "WHERE status = 'open' ORDER BY created_at ASC LIMIT :lim"
                ),
                {"lim": int(limit)},
            ).fetchall()
            now = _now_iso()
            for row in rows or []:
                rid = row[0]
                res = resolve_terminal(row[1])
                summary["scanned"] += 1
                try:
                    db.execute(
                        text(
                            "UPDATE exception_queue SET status = :st, resolved_outcome = :ro, "
                            "resolved_at = :ts WHERE id = :id AND status = 'open'"
                        ),
                        {"st": res.resolution_status, "ro": res.note, "ts": now, "id": rid},
                    )
                    summary[res.resolution_status] = summary.get(res.resolution_status, 0) + 1
                except Exception as exc:
                    summary["errors"] += 1
                    _log.debug("exception row %s resolve failed: %r", rid, exc)
            try:
                db.commit()
            except Exception as exc:
                _log.debug("exception resolver commit failed: %r", exc)
    except Exception as exc:
        summary["errors"] += 1
        _log.debug("resolve_open_exceptions failed: %r", exc)
    return summary


# Celery task wrapper (best-effort registration; the plain callable above stays
# fully usable + testable without a broker).
try:
    from src.app.workers.celery_app import celery_app

    @celery_app.task(name="src.app.tasks.exception_resolver.resolve_open_exceptions")
    def resolve_open_exceptions_task(limit: int = 200) -> Dict[str, int]:
        return resolve_open_exceptions(limit=limit)
except Exception:  # celery not configured in this context — callable still works
    resolve_open_exceptions_task = None  # type: ignore
