"""Attribution backbone (agnostic CORE).

Closes the measurement loop: it records a recommendation DECISION (trace_id / decision_id +
the SKUs it proposed) and, later, links the ORDER that resulted — so the platform can say
"this recommendation drove this purchase" and feed a real reward to the bandit (whose reward
signal is otherwise undefined).

VERTICAL-BLIND: speaks only decision_id / trace_id / sku / uid_hash / value_cents / window —
no product vocabulary. STRUCTURED data only. NEVER raises into the request path (returns a
status object instead) so it can be a fire-and-forget capture stage wrapped by safe_stage.

Tables (CREATE IF NOT EXISTS, SQLite + Postgres portable):
  recommendation_decision(id, trace_id, decision_id, uid_hash, surface, arm, variant,
                          skus_json, context_json, created_at)
  conversion_event(id, decision_id, order_id, uid_hash, attributed_skus_json,
                   value_cents, window_s, attribution_model, converted_at, created_at)

SCOPE (v1 capture): attribution matches by trace_id (the cart carries it end-to-end) with a
most-recent-per-uid fallback, and is idempotent per order_id. Strict time-window enforcement,
settled-order gating and the bandit reward feed land with E3 (default-OFF until bench-validated)
— this module is the measurement substrate they build on.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from sqlalchemy import text

_DECISION_DDL = """
CREATE TABLE IF NOT EXISTS recommendation_decision (
    id TEXT PRIMARY KEY,
    trace_id TEXT,
    decision_id TEXT,
    uid_hash TEXT,
    surface TEXT,
    arm TEXT,
    variant TEXT,
    skus_json TEXT,
    context_json TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
)
"""

_CONVERSION_DDL = """
CREATE TABLE IF NOT EXISTS conversion_event (
    id TEXT PRIMARY KEY,
    decision_id TEXT,
    order_id TEXT,
    uid_hash TEXT,
    attributed_skus_json TEXT,
    value_cents INTEGER,
    window_s INTEGER,
    attribution_model TEXT,
    converted_at TEXT,
    rewarded_at TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
)
"""


@dataclass
class AttributionResult:
    """Outcome of attribute_order(); reward_from_outcome() turns this into a bandit reward."""
    attributed: bool
    decision_id: Optional[str] = None
    order_id: Optional[str] = None
    value_cents: int = 0
    attributed_skus: List[str] = field(default_factory=list)
    reason: str = ""


def ensure_tables(db) -> None:
    """Create the attribution tables if absent. Idempotent; safe to call per request."""
    db.execute(text(_DECISION_DDL))
    db.execute(text(_CONVERSION_DDL))


def _dumps(value: Any) -> str:
    try:
        return json.dumps(value, separators=(",", ":"), default=str)
    except Exception:
        return "null"


def _loads_list(raw: Any) -> List[str]:
    if not raw:
        return []
    try:
        out = json.loads(raw) if isinstance(raw, str) else raw
        return [str(x) for x in out] if isinstance(out, list) else []
    except Exception:
        return []


def record_decision(
    db,
    *,
    trace_id: Optional[str],
    decision_id: Optional[str],
    uid_hash: Optional[str],
    skus: Optional[List[str]] = None,
    surface: str = "recommend",
    arm: Optional[str] = None,
    variant: Optional[str] = None,
    context: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """Persist the decision a recommendation turn made (which SKUs it proposed, under which
    arm/variant). Returns the row id, or None on failure — never raises into the caller."""
    if db is None or not (trace_id or decision_id):
        return None
    try:
        ensure_tables(db)
        row_id = str(uuid.uuid4())
        db.execute(
            text(
                "INSERT INTO recommendation_decision "
                "(id, trace_id, decision_id, uid_hash, surface, arm, variant, skus_json, context_json) "
                "VALUES (:id,:t,:d,:u,:s,:a,:v,:sk,:c)"
            ),
            {
                "id": row_id,
                "t": trace_id,
                "d": decision_id or trace_id,
                "u": uid_hash,
                "s": surface,
                "a": arm,
                "v": variant,
                "sk": _dumps([str(x) for x in (skus or [])]),
                "c": _dumps(context or {}),
            },
        )
        return row_id
    except Exception:
        return None


def _find_decision(db, *, trace_id: Optional[str], uid_hash: Optional[str]) -> Optional[Dict[str, Any]]:
    """Find the decision an order should be credited to: exact trace_id match first (the cart
    carries it), else the most recent decision for this uid_hash."""
    if trace_id:
        row = db.execute(
            text(
                "SELECT decision_id, skus_json FROM recommendation_decision "
                "WHERE trace_id = :t ORDER BY created_at DESC LIMIT 1"
            ),
            {"t": trace_id},
        ).fetchone()
        if row:
            return {"decision_id": row[0], "skus": _loads_list(row[1])}
    if uid_hash:
        row = db.execute(
            text(
                "SELECT decision_id, skus_json FROM recommendation_decision "
                "WHERE uid_hash = :u ORDER BY created_at DESC LIMIT 1"
            ),
            {"u": uid_hash},
        ).fetchone()
        if row:
            return {"decision_id": row[0], "skus": _loads_list(row[1])}
    return None


def attribute_order(
    db,
    *,
    order_id: str,
    trace_id: Optional[str] = None,
    uid_hash: Optional[str] = None,
    value_cents: int = 0,
    line_skus: Optional[List[str]] = None,
    window_s: int = 0,
    attribution_model: str = "trace_or_recent",
    converted_at: Optional[str] = None,
) -> AttributionResult:
    """Link an order back to the decision that produced it. Idempotent per order_id; never
    raises. Returns an AttributionResult that reward_from_outcome() can score."""
    if db is None or not order_id:
        return AttributionResult(attributed=False, order_id=order_id, reason="missing_db_or_order")
    try:
        ensure_tables(db)
        # Idempotency: an order is attributed at most once.
        existing = db.execute(
            text("SELECT decision_id FROM conversion_event WHERE order_id = :o LIMIT 1"),
            {"o": order_id},
        ).fetchone()
        if existing:
            return AttributionResult(
                attributed=False, order_id=order_id, decision_id=existing[0],
                reason="already_attributed",
            )
        match = _find_decision(db, trace_id=trace_id, uid_hash=uid_hash)
        if not match:
            return AttributionResult(attributed=False, order_id=order_id, reason="no_matching_decision")
        ordered = [str(x) for x in (line_skus or [])]
        decided = match.get("skus") or []
        attributed_skus = [s for s in ordered if s in decided] or ordered
        db.execute(
            text(
                "INSERT INTO conversion_event "
                "(id, decision_id, order_id, uid_hash, attributed_skus_json, value_cents, "
                " window_s, attribution_model, converted_at) "
                "VALUES (:id,:d,:o,:u,:sk,:v,:w,:m,:ts)"
            ),
            {
                "id": str(uuid.uuid4()),
                "d": match["decision_id"],
                "o": order_id,
                "u": uid_hash,
                "sk": _dumps(attributed_skus),
                "v": int(value_cents or 0),
                "w": int(window_s or 0),
                "m": attribution_model,
                "ts": converted_at,
            },
        )
        return AttributionResult(
            attributed=True, decision_id=match["decision_id"], order_id=order_id,
            value_cents=int(value_cents or 0), attributed_skus=attributed_skus, reason="ok",
        )
    except Exception as exc:
        return AttributionResult(attributed=False, order_id=order_id, reason=f"error:{type(exc).__name__}")


def _mark_rewarded(db, conversion_event_id: str) -> None:
    db.execute(
        text("UPDATE conversion_event SET rewarded_at = CURRENT_TIMESTAMP WHERE id = :id"),
        {"id": conversion_event_id},
    )


def run_reward_feed(
    db,
    *,
    settle_cutoff_iso: str,
    per_uid_cap: int = 50,
    batch_limit: int = 500,
    bandit_reward_fn=None,
    reward_fn=None,
) -> Dict[str, int]:
    """E3 — turn SETTLED, un-rewarded conversions into bandit rewards.

    Quarantine controls (anti-poison): only conversions whose converted_at (fallback created_at)
    is at/older than ``settle_cutoff_iso`` are processed (settled-order gate, past the return
    window); each conversion is rewarded at most once (``rewarded_at`` marker → idempotent); and a
    per-uid cap bounds a single uid's influence per batch (anti-self-attribution; over-cap
    conversions are consumed but NOT rewarded). The reward is bounded [0,1] via reward_from_outcome.

    ``bandit_reward_fn``/``reward_fn`` are injectable for testing; defaults wire the real bandit.
    Does not swallow errors — the Celery task wrapper logs and isolates failures.
    """
    if db is None:
        return {"processed": 0, "rewarded": 0, "skipped_no_decision": 0, "skipped_cap": 0}
    if bandit_reward_fn is None:
        from src.app.services.recommendation_bandit import record_bandit_reward as bandit_reward_fn
    if reward_fn is None:
        reward_fn = reward_from_outcome
    ensure_tables(db)
    rows = db.execute(
        text(
            "SELECT ce.id, ce.decision_id, ce.uid_hash, ce.attributed_skus_json, rd.arm "
            "FROM conversion_event ce "
            "LEFT JOIN recommendation_decision rd ON rd.decision_id = ce.decision_id "
            "WHERE ce.rewarded_at IS NULL "
            "  AND COALESCE(ce.converted_at, ce.created_at) <= :cut "
            "ORDER BY ce.created_at ASC LIMIT :lim"
        ),
        {"cut": settle_cutoff_iso, "lim": int(batch_limit)},
    ).fetchall()
    summary = {"processed": 0, "rewarded": 0, "skipped_no_decision": 0, "skipped_cap": 0}
    uid_counts: Dict[str, int] = {}
    for r in rows:
        ce_id, decision_id, uid_hash, skus_json, arm = r[0], r[1], r[2], r[3], r[4]
        summary["processed"] += 1
        if not decision_id or arm is None:
            _mark_rewarded(db, ce_id)  # consume so it isn't reprocessed every batch
            summary["skipped_no_decision"] += 1
            continue
        uid_counts[uid_hash] = uid_counts.get(uid_hash, 0) + 1
        if uid_counts[uid_hash] > int(per_uid_cap):
            _mark_rewarded(db, ce_id)  # quarantine: consume but do NOT reward
            summary["skipped_cap"] += 1
            continue
        reward = float(reward_fn(AttributionResult(attributed=True)))
        for sku in _loads_list(skus_json):
            bandit_reward_fn(db, uid_hash=uid_hash, sku=sku, arm=arm, reward=reward, context={})
        _mark_rewarded(db, ce_id)
        summary["rewarded"] += 1
    db.commit()
    return summary


def arm_for_trace(db, trace_id: Optional[str]) -> str:
    """The bandit arm recorded for a trace's decision (E0), or 'balanced' as a safe default.

    Lets the feedback/interaction path reward the arm that ACTUALLY ranked the results — the
    feedback endpoint runs in a separate request, so it can't read the request-scoped ContextVar;
    it must look the arm up by trace_id. Never raises."""
    if db is None or not trace_id:
        return "balanced"
    try:
        ensure_tables(db)
        row = db.execute(
            text(
                "SELECT arm FROM recommendation_decision WHERE trace_id = :t "
                "ORDER BY created_at DESC LIMIT 1"
            ),
            {"t": str(trace_id)},
        ).fetchone()
        if row and row[0]:
            return str(row[0])
    except Exception:
        return "balanced"
    return "balanced"


def reward_from_outcome(result: AttributionResult) -> float:
    """Map an attribution outcome to a bounded [0,1] bandit reward.

    v1: 1.0 for an attributed conversion, else 0.0. Value-scaling, settled-order gating and
    anti-poison quarantine arrive with the E3 reward feed (default-OFF) — keeping this
    deterministic and bounded means a burst of fake conversions can move the signal by at most
    one unit per (idempotent) order.
    """
    if not isinstance(result, AttributionResult):
        return 0.0
    return 1.0 if result.attributed else 0.0
