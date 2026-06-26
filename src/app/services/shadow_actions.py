"""Typed shadow actions (agnostic CORE) — David's "propose, don't act" safety layer.

Turns M3 findings into TYPED action proposals (adjust_ranking, suppress_low_stock,
revise_support_copy, ...) that are LOGGED ONLY — never executed. This is the observability bridge
between "the system noticed something" and "the system did something": you can see exactly what the
autonomous layer WOULD do, and for how long, before any of it is allowed to act. A proposal that is
later promoted goes through the experiment gate (reversible, bounded) + policy → escalation → audit;
this module has NO execution path and imports NO ranker/inventory/copy mutator by design.

INVARIANT: status is always 'proposed' (or 'superseded'). There is no 'executed' here. The map from
finding_type → action_type is deterministic and vertical-blind (opaque labels; no product vocabulary).

Table: shadow_action(id, tenant_id, schema_version, action_type, target_ref, source_finding_type,
                     direction, magnitude, confidence, rationale, params_json, status, dedup_key,
                     created_at)
"""
from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import text

SCHEMA_VERSION = 1
DEFAULT_TENANT = "default"

ACTION_ADJUST_RANKING = "adjust_ranking"
ACTION_SUPPRESS_LOW_STOCK = "suppress_low_stock"
ACTION_REVISE_SUPPORT_COPY = "revise_support_copy"

# finding_type → proposed action_type. Deterministic + opaque — no product knowledge.
_FINDING_TO_ACTION: Dict[str, str] = {
    "demand_shift": ACTION_ADJUST_RANKING,            # demand moved → propose re-ranking the entity
    "demand_forecast": ACTION_ADJUST_RANKING,         # PROJECTED demand move → same reversible nudge (gated)
    "conversion_anomaly": ACTION_REVISE_SUPPORT_COPY,  # conversions dropped → propose copy/messaging review
    "inventory_demand_mismatch": ACTION_SUPPRESS_LOW_STOCK,  # demand with no stock → propose demoting it
}
_SEVERITY_WEIGHT = {"info": 0.3, "warn": 0.7, "critical": 1.0}


@dataclass(frozen=True)
class ShadowAction:
    action_type: str
    target_ref: Optional[str]      # entity the action would touch (sku / token / None=global)
    source_finding_type: str
    direction: str                 # boost | demote | review
    magnitude: float               # 0..1 — how strong the proposal is (severity×confidence)
    confidence: float
    rationale: str                 # the finding summary that triggered it
    params: Dict[str, Any] = field(default_factory=dict)
    status: str = "proposed"       # INVARIANT: never 'executed'

    def dedup_key(self, tenant_id: str) -> str:
        raw = "|".join([str(tenant_id), self.action_type, str(self.target_ref or ""), self.source_finding_type])
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def _attr(f: Any, name: str, default: Any = None) -> Any:
    return f.get(name, default) if isinstance(f, dict) else getattr(f, name, default)


def _direction_for(action_type: str, evidence: Dict[str, Any]) -> str:
    """boost/demote/review — derived from the finding, vertical-blind. A demand finding that the
    evidence marks as a slowdown demotes; a spike boosts; everything else is a neutral review."""
    if action_type == ACTION_SUPPRESS_LOW_STOCK:
        return "demote"
    if action_type == ACTION_ADJUST_RANKING:
        d = str((evidence or {}).get("direction") or "").lower()
        if d in ("down", "slowdown", "drop", "decline"):
            return "demote"
        return "boost"
    return "review"


def propose_from_findings(findings: Optional[Iterable[Any]]) -> List[ShadowAction]:
    """Map findings → typed proposals (pure; no I/O, no execution). Unknown finding types are skipped
    (only mapped types yield a proposal). Ordered by magnitude desc (most salient first)."""
    out: List[ShadowAction] = []
    for f in (findings or []):
        ftype = str(_attr(f, "finding_type") or "").strip()
        action_type = _FINDING_TO_ACTION.get(ftype)
        if not action_type:
            continue
        severity = str(_attr(f, "severity") or "info")
        confidence = float(_attr(f, "confidence", 0.0) or 0.0)
        magnitude = round(_SEVERITY_WEIGHT.get(severity, 0.5) * confidence, 3)
        evidence = _attr(f, "evidence", {}) or {}
        direction = _direction_for(action_type, evidence if isinstance(evidence, dict) else {})
        out.append(ShadowAction(
            action_type=action_type,
            target_ref=_attr(f, "entity_ref"),
            source_finding_type=ftype,
            direction=direction,
            magnitude=magnitude,
            confidence=round(confidence, 3),
            rationale=str(_attr(f, "summary") or f"{ftype} ({severity})"),
            params={"direction": direction, "magnitude": magnitude, "severity": severity,
                    "reversible": True, "requires_experiment": True},  # promotion always goes through the gate
        ))
    out.sort(key=lambda a: -a.magnitude)
    return out


# ── persistence (log-only) ────────────────────────────────────────────────────
_DDL = """
CREATE TABLE IF NOT EXISTS shadow_action (
    id TEXT PRIMARY KEY,
    tenant_id TEXT DEFAULT 'default',
    schema_version INTEGER DEFAULT 1,
    action_type TEXT,
    target_ref TEXT,
    source_finding_type TEXT,
    direction TEXT,
    magnitude REAL,
    confidence REAL,
    rationale TEXT,
    params_json TEXT,
    status TEXT DEFAULT 'proposed',
    dedup_key TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
)
"""
_INDEXES = (
    "CREATE INDEX IF NOT EXISTS ix_shadow_action_type ON shadow_action(action_type)",
    "CREATE INDEX IF NOT EXISTS ix_shadow_action_dedup ON shadow_action(tenant_id, dedup_key, status)",
)


def ensure_table(db) -> None:
    db.execute(text(_DDL))
    for stmt in _INDEXES:
        db.execute(text(stmt))


def persist_proposals(db, actions: List[ShadowAction], *, tenant_id: str = DEFAULT_TENANT) -> int:
    """Write proposals, SUPERSEDING the prior proposed one per (tenant, action_type, target). LOG-ONLY:
    rows are inserted with status='proposed' and NEVER executed. Returns the count written. Never raises."""
    if db is None or not actions:
        return 0
    try:
        ensure_table(db)
        tid = str(tenant_id).strip() or DEFAULT_TENANT
        n = 0
        for a in actions:
            dk = a.dedup_key(tid)
            new_id = str(uuid.uuid4())
            db.execute(
                text("UPDATE shadow_action SET status='superseded' "
                     "WHERE tenant_id=:t AND dedup_key=:dk AND status='proposed'"),
                {"t": tid, "dk": dk},
            )
            db.execute(
                text("INSERT INTO shadow_action (id, tenant_id, schema_version, action_type, target_ref, "
                     "source_finding_type, direction, magnitude, confidence, rationale, params_json, "
                     "status, dedup_key) VALUES (:i,:tn,:sv,:at,:tr,:sf,:di,:mg,:cf,:ra,:pj,'proposed',:dk)"),
                {"i": new_id, "tn": tid, "sv": int(SCHEMA_VERSION), "at": a.action_type, "tr": a.target_ref,
                 "sf": a.source_finding_type, "di": a.direction, "mg": float(a.magnitude),
                 "cf": float(a.confidence), "ra": a.rationale, "pj": json.dumps(a.params, default=str), "dk": dk},
            )
            n += 1
        return n
    except Exception:
        return 0


def load_recent_proposals(db, *, limit: int = 100, tenant_id: str = DEFAULT_TENANT) -> List[Dict[str, Any]]:
    """Recent ACTIVE proposals (tenant-scoped). Best-effort."""
    if db is None:
        return []
    try:
        ensure_table(db)
        rows = db.execute(
            text("SELECT action_type, target_ref, source_finding_type, direction, magnitude, confidence, "
                 "rationale, params_json, status FROM shadow_action "
                 "WHERE status='proposed' AND COALESCE(tenant_id,'default')=:t "
                 "ORDER BY created_at DESC LIMIT :lim"),
            {"lim": int(limit), "t": str(tenant_id).strip() or DEFAULT_TENANT},
        ).fetchall()
    except Exception:
        return []
    out = []
    for r in rows:
        try:
            params = json.loads(r[7]) if r[7] else {}
        except Exception:
            params = {}
        out.append({"action_type": r[0], "target_ref": r[1], "source_finding_type": r[2], "direction": r[3],
                    "magnitude": float(r[4] or 0.0), "confidence": float(r[5] or 0.0), "rationale": r[6],
                    "params": params if isinstance(params, dict) else {}, "status": r[8]})
    return out


def generate_shadow_actions(db, *, tenant_id: str = DEFAULT_TENANT, max_findings: int = 200) -> Dict[str, Any]:
    """Read persisted findings → propose typed actions → LOG them (persist + trace). NEVER executes.
    Returns {proposed, by_action}. The batch entry point. Best-effort; never raises."""
    if db is None:
        return {"proposed": 0, "by_action": {}}
    try:
        from src.app.services.market_analysis import load_recent_findings
        findings = load_recent_findings(db, limit=int(max_findings), tenant_id=tenant_id)
        actions = propose_from_findings(findings)
        written = persist_proposals(db, actions, tenant_id=tenant_id)
        by_action: Dict[str, int] = {}
        for a in actions:
            by_action[a.action_type] = by_action.get(a.action_type, 0) + 1
        try:
            from src.app.services.decision_log import log_trace_event
            log_trace_event(trace_id=None, event_type="shadow_actions_proposed", source_type="agent",
                            source_id="ShadowActionPlanner", target_type="proposal", target_id=None,
                            payload={"proposed": written, "by_action": by_action, "executed": 0})
        except Exception:
            pass
        return {"proposed": written, "by_action": by_action}
    except Exception:
        return {"proposed": 0, "by_action": {}}
