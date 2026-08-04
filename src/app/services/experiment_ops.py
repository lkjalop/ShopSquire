"""Experiment operationalization (agnostic CORE) — make the autonomous rollback loop OPERABLE.

Builds ON the existing assignment/uplift/rollback (services/experiments + experiment_eval) — it does
NOT reimplement them. It adds the operational safety net the deck demands once experiments run live:

  • broader guardrails   — composite_guardrail + a feedback_rate_guardrail factory (escalations, etc.)
                           so anti-Goodhart isn't just returns; any treatment that raises a bad-signal
                           rate vs control breaches and reverts.
  • worker health        — a heartbeat the eval task stamps; eval_is_stale + pause_live_if_eval_stale
                           FAIL-SAFE: if the safety loop itself stops running, pause live experiments
                           so a nudge can't keep running unsupervised.
  • stale-experiment     — detect_stale_experiments / auto_revert_stale: a 'live' experiment older than
    detection              a max age is a zombie → revert it.
  • forced rollback drill — forced_rollback_drill: a deliberate DR test that force-reverts live
                           experiment(s) and VERIFIES they stopped — proving the kill switch works.

Vertical-blind; best-effort; never raises into a caller.
"""
from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy import inspect, text

from src.app.services.experiments import assign_variant, ensure_tables, is_experiment_live, set_status

GuardrailFn = Callable[[Any, str], Dict[str, float]]


# ── low-risk rollout controls: canary exposure + global kill switch ───────────
def adaptation_killed() -> bool:
    """Global emergency brake. ADAPTATION_KILL_SWITCH=1 forces ALL adaptation OFF (ranking nudge,
    template phrasing, ...) regardless of any experiment's status — independent of the per-experiment
    revert lever, so one env flip stops everything at once."""
    return str(os.getenv("ADAPTATION_KILL_SWITCH", "0")).strip().lower() in ("1", "true", "yes", "on")


def _in_canary(experiment_id: str, subject: str, fraction: float) -> bool:
    """Deterministic, stable membership of the small canary cohort. Same subject → same answer."""
    f = max(0.0, min(1.0, float(fraction)))
    if f >= 1.0:
        return True
    if f <= 0.0:
        return False
    h = int(hashlib.sha256(f"canary|{experiment_id}|{subject}".encode("utf-8")).hexdigest()[:8], 16)
    return (h % 10000) / 10000.0 < f


def canary_assignment(*, experiment_id: str, subject: str, canary_fraction: float = 0.1) -> str:
    """Small-canary exposure: only subjects INSIDE the canary fraction are eligible for treatment;
    everyone else is control. Within the canary, the usual deterministic split applies. So overall
    treatment exposure ≈ canary_fraction × 0.5 — the deck's 'start small' for live adaptation."""
    if not _in_canary(experiment_id, subject, canary_fraction):
        return "control"
    return assign_variant(experiment_id=experiment_id, subject=subject, variants=["control", "treatment"])


def _now(now_iso: Optional[str]) -> datetime:
    if now_iso:
        try:
            return datetime.fromisoformat(str(now_iso).replace("Z", "").replace("T", " "))
        except Exception:
            pass
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _parse(ts: Any) -> Optional[datetime]:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "").replace("T", " "))
    except Exception:
        return None


# ── broader guardrails ────────────────────────────────────────────────────────
def _safe_guard(fn: GuardrailFn, db, eid: str, *, tenant_id: str) -> Dict[str, float]:
    try:
        try:
            return fn(db, eid, tenant_id=tenant_id) or {}
        except TypeError:
            return fn(db, eid) or {}
    except Exception:
        return {}


def composite_guardrail(*fns: GuardrailFn) -> GuardrailFn:
    """Merge several guardrails into one delta dict. decide() already breaches on ANY negative delta,
    so composing returns + escalation + margin makes anti-Goodhart multi-dimensional."""
    def _g(db, eid: str, *, tenant_id: str = "") -> Dict[str, float]:
        merged: Dict[str, float] = {}
        for fn in fns:
            merged.update(_safe_guard(fn, db, eid, tenant_id=tenant_id))
        return merged
    return _g


def feedback_rate_guardrail(feedback_type: str) -> GuardrailFn:
    """Factory: a guardrail that breaches when the treatment raises the per-subject rate of a given
    human_feedback type (e.g. 'escalation') vs control. Returns {<type>_rate: -delta_pct}; {} when the
    link can't be computed (then decide runs on the other guardrails)."""
    key = f"{feedback_type}_rate"

    def _g(db, eid: str, *, tenant_id: str = "") -> Dict[str, float]:
        try:
            rows = db.execute(
                text("SELECT a.variant, COUNT(DISTINCT a.subject_hash) AS assigned, "
                     "COUNT(DISTINCT h.subject_hash) AS flagged "
                     "FROM experiment_assignment a "
                     "LEFT JOIN human_feedback h ON h.subject_hash = a.subject_hash "
                     "AND h.feedback_type = :ft AND h.tenant_id=a.tenant_id "
                     "WHERE a.experiment_id = :e AND a.tenant_id=:t GROUP BY a.variant"),
                {"ft": str(feedback_type), "e": str(eid), "t": str(tenant_id)},
            ).fetchall()
        except Exception:
            return {}
        rate: Dict[str, float] = {}
        for variant, assigned, flagged in rows:
            a = float(assigned or 0)
            rate[str(variant)] = (float(flagged or 0) / a) if a > 0 else 0.0
        cr, tr = rate.get("control"), rate.get("treatment")
        if cr is None or tr is None:
            return {}
        if cr > 0:
            delta = (tr - cr) / cr * 100.0
        else:
            delta = 0.0 if tr == 0 else 100.0
        return {key: round(-delta, 3)}  # treatment raises the bad-signal rate → negative → breach

    return _g


escalation_rate_guardrail = feedback_rate_guardrail("escalation")


# ── worker health (heartbeat) ─────────────────────────────────────────────────
def _ensure_heartbeat(db) -> None:
    schema = inspect(db.connection())
    if not schema.has_table("experiment_ops_heartbeat"):
        raise RuntimeError("experiment_ops_schema_migration_required")
    columns = {column["name"] for column in schema.get_columns("experiment_ops_heartbeat")}
    if not {"name", "beat_at"}.issubset(columns):
        raise RuntimeError("experiment_ops_schema_migration_required")


def record_heartbeat(db, *, name: str = "experiment_eval", now_iso: Optional[str] = None) -> bool:
    """Stamp the safety loop's liveness. The eval task calls this every run. Never raises."""
    if db is None:
        return False
    try:
        _ensure_heartbeat(db)
        ts = _now(now_iso).strftime("%Y-%m-%d %H:%M:%S")
        db.execute(text("DELETE FROM experiment_ops_heartbeat WHERE name=:n"), {"n": name})
        db.execute(text("INSERT INTO experiment_ops_heartbeat (name, beat_at) VALUES (:n,:b)"),
                   {"n": name, "b": ts})
        return True
    except Exception:
        return False


def heartbeat_age_seconds(db, *, name: str = "experiment_eval", now_iso: Optional[str] = None) -> Optional[float]:
    """Seconds since the last heartbeat, or None when there has never been one."""
    if db is None:
        return None
    try:
        _ensure_heartbeat(db)
        row = db.execute(text("SELECT beat_at FROM experiment_ops_heartbeat WHERE name=:n"), {"n": name}).fetchone()
    except Exception:
        return None
    last = _parse(row[0]) if row else None
    if last is None:
        return None
    return max(0.0, (_now(now_iso) - last).total_seconds())


def eval_is_stale(db, *, max_age_seconds: float, name: str = "experiment_eval",
                  now_iso: Optional[str] = None) -> bool:
    """True when the safety loop hasn't beaten within max_age_seconds (or never has). Stale = unsafe."""
    age = heartbeat_age_seconds(db, name=name, now_iso=now_iso)
    return age is None or age > float(max_age_seconds)


def _live_experiment_ids(db, *, tenant_id: str) -> List[str]:
    ensure_tables(db)
    return [r[0] for r in db.execute(
        text("SELECT id FROM experiment_run WHERE tenant_id=:t AND status='live'"),
        {"t": str(tenant_id)},
    ).fetchall()]


def pause_live_if_eval_stale(
    db, *, tenant_id: str, max_age_seconds: float, now_iso: Optional[str] = None
) -> Dict[str, Any]:
    """FAIL-SAFE: if the eval loop is stale (the watchdog that auto-reverts losers isn't running),
    pause every live experiment so no nudge keeps running unsupervised. Returns {stale, paused}."""
    if db is None:
        return {"stale": False, "paused": []}
    if not eval_is_stale(db, max_age_seconds=max_age_seconds, now_iso=now_iso):
        return {"stale": False, "paused": []}
    paused: List[str] = []
    try:
        for eid in _live_experiment_ids(db, tenant_id=tenant_id):
            if set_status(db, tenant_id=tenant_id, experiment_id=eid, status="paused"):
                paused.append(eid)
        db.commit()
    except Exception:
        return {"stale": True, "paused": paused}
    return {"stale": True, "paused": paused}


# ── stale-experiment detection ────────────────────────────────────────────────
def detect_stale_experiments(
    db, *, tenant_id: str, max_age_seconds: float, now_iso: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Live experiments whose created_at is older than max_age_seconds — zombie candidates."""
    if db is None:
        return []
    try:
        ensure_tables(db)
        rows = db.execute(
            text("SELECT id, name, started_at, created_at FROM experiment_run "
                 "WHERE tenant_id=:t AND status='live'"),
            {"t": str(tenant_id)},
        ).fetchall()
    except Exception:
        return []
    now = _now(now_iso)
    out: List[Dict[str, Any]] = []
    for eid, name, started_at, created in rows:
        # age from ACTIVATION (started_at), not creation — an old DRAFT activated today is fresh, not
        # stale. Fall back to created_at only when started_at is absent (legacy rows).
        started = _parse(started_at) or _parse(created)
        age = (now - started).total_seconds() if started else None
        if age is not None and age > float(max_age_seconds):
            out.append({"experiment_id": eid, "name": name, "age_seconds": round(age, 1)})
    return out


def auto_revert_stale(
    db, *, tenant_id: str, max_age_seconds: float, now_iso: Optional[str] = None
) -> List[str]:
    """Revert every stale live experiment (zombie cleanup). Returns the reverted ids."""
    stale = detect_stale_experiments(
        db, tenant_id=tenant_id, max_age_seconds=max_age_seconds, now_iso=now_iso
    )
    reverted: List[str] = []
    for s in stale:
        if set_status(
            db, tenant_id=tenant_id, experiment_id=s["experiment_id"], status="reverted"
        ):
            reverted.append(s["experiment_id"])
    if reverted and db is not None:
        try:
            db.commit()
        except Exception:
            return reverted
    return reverted


# ── forced rollback drill (DR test for the kill switch) ───────────────────────
def forced_rollback_drill(db, *, tenant_id: str, experiment_id: Optional[str] = None,
                          now_iso: Optional[str] = None) -> Dict[str, Any]:
    """Deliberately force-revert one experiment (or ALL live ones) and VERIFY each stopped — a fire
    drill proving the rollback path actually disables the adaptation. Returns a drill report."""
    if db is None:
        return {"targeted": [], "reverted": [], "verified_not_live": True, "failures": []}
    try:
        targets = [experiment_id] if experiment_id else _live_experiment_ids(
            db, tenant_id=tenant_id
        )
    except Exception:
        return {"targeted": [], "reverted": [], "verified_not_live": False, "failures": ["enumerate_failed"]}
    reverted, failures = [], []
    for eid in targets:
        set_status(db, tenant_id=tenant_id, experiment_id=eid, status="reverted")
        try:
            db.commit()
        except Exception:
            pass
        if is_experiment_live(db, eid, tenant_id=tenant_id):
            failures.append(eid)          # the kill switch DID NOT take — critical
        else:
            reverted.append(eid)
    return {"targeted": list(targets), "reverted": reverted,
            "verified_not_live": not failures, "failures": failures}
