"""Human-correction learning (agnostic CORE) — David's human-in-the-loop feedback as graph signal.

A single envelope for every human judgement that should teach the system: an approval, a rejected
recommendation, an NQE correction, an escalation, a return. Each becomes a SIGNED learning signal —
positive lifts an entity's recall prior, negative suppresses it — so the hippograph's recall reflects
what humans actually accepted or rejected, not just what converted.

Two ways in:
  • record_feedback(db, type, entity_ref=, subject_hash=)  — the EVENT hook any call site fires
    (approval granted, recommendation rejected, NQE answer corrected, escalation opened).
  • backfill_from_db(db)                                    — BATCH derivation from tables that
    already hold the judgement: returns (refunded/chargebacked orders → their attributed SKUs) and
    human-corrected market findings (market_finding.status='corrected').

VERTICAL-BLIND: feedback_type/source are opaque labels; entity_ref is an opaque id. Idempotent
(dedup_key), tenant-scoped, never raises. READ side projects into the graph (project_human_feedback);
a signal that later drives an action still re-enters policy → escalation → audit.

Table: human_feedback(id, tenant_id, schema_version, feedback_type, subject_hash, entity_ref,
                      polarity, weight, source, dedup_key, occurred_at, created_at)
"""
from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import text

SCHEMA_VERSION = 1
DEFAULT_TENANT = "default"

# feedback_type → default polarity (the SIGN of the learning signal). An explicit polarity overrides.
# Positive = humans favoured this entity; negative = humans pushed back on it.
_DEFAULT_POLARITY: Dict[str, float] = {
    "approval": 1.0,                  # a human approved the proposal/draft
    "recommendation_accepted": 1.0,   # the user acted on the pick
    "nqe_correction": 1.0,            # the human taught us the right attribute → reinforce it
    "rejection": -1.0,
    "recommendation_rejected": -1.0,  # the user dismissed the pick
    "escalation": -1.0,               # a human had to step in → the autonomous pick under-served
    "return": -1.0,                   # refunded/chargebacked → trust damage
    "finding_correction": -1.0,       # a human marked a finding wrong → distrust that finding/entity
}

_DDL = """
CREATE TABLE IF NOT EXISTS human_feedback (
    id TEXT PRIMARY KEY,
    tenant_id TEXT DEFAULT 'default',
    schema_version INTEGER DEFAULT 1,
    feedback_type TEXT,
    subject_hash TEXT,
    entity_ref TEXT,
    polarity REAL,
    weight REAL,
    source TEXT,
    dedup_key TEXT,
    occurred_at TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
)
"""
_INDEXES = (
    "CREATE UNIQUE INDEX IF NOT EXISTS ix_human_feedback_dedup ON human_feedback(tenant_id, dedup_key)",
    "CREATE INDEX IF NOT EXISTS ix_human_feedback_type ON human_feedback(feedback_type)",
    "CREATE INDEX IF NOT EXISTS ix_human_feedback_entity ON human_feedback(entity_ref)",
)


@dataclass(frozen=True)
class HumanFeedback:
    feedback_type: str
    subject_hash: Optional[str]
    entity_ref: Optional[str]
    polarity: float       # sign of the learning signal (+/-)
    weight: float         # magnitude in [0,1]
    source: str
    dedup_key: str
    tenant_id: str = DEFAULT_TENANT
    schema_version: int = SCHEMA_VERSION

    @property
    def signed(self) -> float:
        return float(self.polarity) * float(self.weight)


def ensure_table(db) -> None:
    db.execute(text(_DDL))
    for stmt in _INDEXES:
        db.execute(text(stmt))


def _dedup_key(feedback_type: str, subject_hash: Any, entity_ref: Any, source: str,
               dedup_fields: Optional[Dict[str, Any]]) -> str:
    parts = [str(feedback_type), str(source)]
    if dedup_fields:
        for k in sorted(dedup_fields):
            parts.append(f"{k}={dedup_fields[k]!r}")
    else:
        parts.append(f"subject={subject_hash!r}")
        parts.append(f"entity={entity_ref!r}")
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:32]


def normalize(
    feedback_type: Any,
    *,
    subject_hash: Any = None,
    entity_ref: Any = None,
    polarity: Any = None,
    weight: Any = 1.0,
    source: Any = "",
    dedup_fields: Optional[Dict[str, Any]] = None,
    tenant_id: Any = DEFAULT_TENANT,
) -> Optional[HumanFeedback]:
    """Validate + normalize a human judgement. Returns None when feedback_type is missing OR there is
    nothing to attach it to (no subject and no entity). Polarity defaults by type; weight clamps [0,1]."""
    ft = str(feedback_type or "").strip()
    subj = str(subject_hash).strip() if subject_hash else None
    ent = str(entity_ref).strip() if entity_ref else None
    if not ft or (not subj and not ent):
        return None
    pol = _DEFAULT_POLARITY.get(ft, 1.0) if polarity is None else float(polarity)
    try:
        w = max(0.0, min(1.0, float(weight if weight is not None else 1.0)))
    except Exception:
        w = 1.0
    # occurred_at is stored by ingest(), not a dataclass field — it doesn't affect identity/dedup.
    return HumanFeedback(
        feedback_type=ft, subject_hash=subj, entity_ref=ent, polarity=float(pol), weight=w,
        source=str(source or ""), dedup_key=_dedup_key(ft, subj, ent, str(source or ""), dedup_fields),
        tenant_id=(str(tenant_id).strip() or DEFAULT_TENANT),
    )


def ingest(db, fb: Optional[HumanFeedback], *, occurred_at: Any = None) -> bool:
    """Idempotent insert (skips a duplicate dedup_key within the tenant). Returns True on a new row."""
    if db is None or fb is None:
        return False
    try:
        ensure_table(db)
        if db.execute(text("SELECT 1 FROM human_feedback WHERE tenant_id=:t AND dedup_key=:k LIMIT 1"),
                      {"t": fb.tenant_id, "k": fb.dedup_key}).fetchone():
            return False
        db.execute(
            text("INSERT INTO human_feedback (id, tenant_id, schema_version, feedback_type, subject_hash, "
                 "entity_ref, polarity, weight, source, dedup_key, occurred_at) "
                 "VALUES (:i,:tn,:sv,:ft,:sh,:er,:po,:we,:so,:dk,:oc)"),
            {"i": str(uuid.uuid4()), "tn": fb.tenant_id, "sv": int(fb.schema_version), "ft": fb.feedback_type,
             "sh": fb.subject_hash, "er": fb.entity_ref, "po": float(fb.polarity), "we": float(fb.weight),
             "so": fb.source, "dk": fb.dedup_key, "oc": None if occurred_at is None else str(occurred_at)},
        )
        return True
    except Exception:
        return False


def record_feedback(db, feedback_type: str, *, commit: bool = True, **kw) -> bool:
    """The EVENT hook — normalize + ingest one human judgement in a single call. Fire it where the
    event happens (approval granted, recommendation rejected, NQE answer corrected, escalation opened).
    Best-effort; never raises into the caller."""
    try:
        occurred_at = kw.pop("occurred_at", None)
        fb = normalize(feedback_type, **kw)
        ok = ingest(db, fb, occurred_at=occurred_at)
        if ok and commit:
            try:
                db.commit()
            except Exception:
                return ok
        return ok
    except Exception:
        return False


def load_recent(db, *, limit: int = 500, tenant_id: str = DEFAULT_TENANT) -> List[Dict[str, Any]]:
    """Recent feedback rows (the read side for projection), tenant-scoped. Best-effort."""
    if db is None:
        return []
    try:
        ensure_table(db)
        rows = db.execute(
            text("SELECT feedback_type, subject_hash, entity_ref, polarity, weight, source "
                 "FROM human_feedback WHERE COALESCE(tenant_id,'default')=:t "
                 "ORDER BY created_at DESC LIMIT :lim"),
            {"lim": int(limit), "t": str(tenant_id).strip() or DEFAULT_TENANT},
        ).fetchall()
    except Exception:
        return []
    return [{"feedback_type": r[0], "subject_hash": r[1], "entity_ref": r[2],
             "polarity": float(r[3] or 0.0), "weight": float(r[4] or 0.0), "source": r[5]} for r in rows]


# ── batch derivation from tables that already hold the judgement ──────────────
def _backfill_returns(db, *, limit: int, tenant_id: str) -> int:
    """Refunded/chargebacked orders → negative feedback on each attributed SKU (trust damage)."""
    n = 0
    try:
        rows = db.execute(
            text("SELECT o.id, c.attributed_skus_json, c.uid_hash FROM orders o "
                 "JOIN conversion_event c ON c.order_id = o.id "
                 "WHERE o.status IN ('refunded','chargebacked') "
                 "ORDER BY o.id DESC LIMIT :lim"),
            {"lim": int(limit)},
        ).fetchall()
    except Exception:
        return 0
    import json
    for oid, skus_json, uid_hash in rows:
        try:
            skus = json.loads(skus_json) if skus_json else []
        except Exception:
            skus = []
        for sku in (skus if isinstance(skus, list) else []):
            fb = normalize("return", subject_hash=uid_hash, entity_ref=sku, source="orders",
                           dedup_fields={"order_id": oid, "sku": sku}, tenant_id=tenant_id)
            if ingest(db, fb):
                n += 1
    return n


def _backfill_finding_corrections(db, *, limit: int, tenant_id: str) -> int:
    """Human-corrected market findings → negative feedback on the named entity (distrust)."""
    n = 0
    try:
        rows = db.execute(
            text("SELECT id, entity_ref FROM market_finding WHERE status='corrected' "
                 "ORDER BY detected_at DESC LIMIT :lim"),
            {"lim": int(limit)},
        ).fetchall()
    except Exception:
        return 0
    for fid, entity_ref in rows:
        if not entity_ref:
            continue  # a global finding has no entity to down-weight
        fb = normalize("finding_correction", entity_ref=entity_ref, source="market_finding",
                       dedup_fields={"finding_id": fid}, tenant_id=tenant_id)
        if ingest(db, fb):
            n += 1
    return n


def backfill_from_db(db, *, limit: int = 1000, tenant_id: str = DEFAULT_TENANT,
                     commit: bool = True) -> Dict[str, int]:
    """Derive feedback from existing tables (returns, finding corrections). Idempotent. The
    event-driven types (approval / rejection / nqe_correction / escalation) arrive via
    record_feedback() at their call sites. Returns {source: count}."""
    if db is None:
        return {}
    ensure_table(db)
    tid = str(tenant_id).strip() or DEFAULT_TENANT
    counts = {
        "returns": _backfill_returns(db, limit=limit, tenant_id=tid),
        "finding_corrections": _backfill_finding_corrections(db, limit=limit, tenant_id=tid),
    }
    if commit:
        try:
            db.commit()
        except Exception:
            return counts
    return counts
