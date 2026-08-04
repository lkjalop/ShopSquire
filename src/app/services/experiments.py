"""Experiment + rollback framework (Module 6b, agnostic CORE) — the gate before LIVE adaptation.

The deck's non-negotiable: "no customer-facing autonomous adaptation goes live without measurement."
This is pure decision math + a small data layer. It MEASURES and DECIDES; it never changes ranking —
a variant only affects behaviour once an experiment is live AND its terminal decision is keep/scale,
which the caller enforces.

Core guarantees:
  • Deterministic assignment — same (experiment, subject) → same variant (stable control-vs-treatment).
  • Anti-false-positive — uplift is measured control-vs-treatment, so a seasonal bump that lifts BOTH
    arms cancels out (it is not credited to the treatment).
  • Anti-Goodhart — a guardrail (margin / returns / unsubscribe) degrading past the rollback threshold
    forces REVERT even if the target metric improved (no "winning on clicks while hurting profit").
  • Terminal decision is always one of keep / scale / revise / revert (never open-ended).

Vertical-blind: experiments/metrics/variants are opaque labels. Never raises into a caller.
"""
from __future__ import annotations

import hashlib
import json
import statistics
import uuid
from dataclasses import dataclass
from typing import Any, Dict, Optional, Sequence

from sqlalchemy import inspect, text

DECISION_KEEP = "keep"
DECISION_SCALE = "scale"
DECISION_REVISE = "revise"
DECISION_REVERT = "revert"

# started_at = ACTIVATION time (status→live); ended_at = terminal time. Added after the table first
# shipped → applied to pre-existing experiment_run tables on upgrade.
_TERMINAL_STATUSES = ("reverted", "paused", "ended", "completed")


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def ensure_tables(db) -> None:
    """Validate migration-owned schema without mutating it at runtime."""
    required = {
        "experiment_run": {
            "id", "tenant_id", "name", "target_metric", "policy_json",
            "policy_version", "status", "started_at", "ended_at",
        },
        "experiment_assignment": {
            "id", "tenant_id", "experiment_id", "subject_hash", "variant", "assigned_at",
        },
        "experiment_result": {
            "id", "tenant_id", "experiment_id", "variant", "decision",
            "uplift_pct", "evidence_json", "decided_at",
        },
    }
    schema = inspect(db.connection())
    missing: list[str] = []
    for table, columns in required.items():
        if not schema.has_table(table):
            missing.append(table)
            continue
        present = {column["name"] for column in schema.get_columns(table)}
        missing.extend(f"{table}.{column}" for column in sorted(columns - present))
    if missing:
        raise RuntimeError(
            "experiment_schema_migration_required:" + ",".join(missing)
        )


# ── assignment ────────────────────────────────────────────────────────────────
def assign_variant(*, experiment_id: str, subject: str, variants: Sequence[str],
                   weights: Optional[Sequence[float]] = None) -> str:
    """Deterministic, stable variant for a subject. Same inputs → same variant (so a user has a
    consistent experience across turns). Weighted when ``weights`` is supplied."""
    vs = [str(v) for v in (variants or []) if str(v).strip()]
    if not vs:
        return "control"
    h = int(hashlib.sha256(f"{experiment_id}|{subject}".encode("utf-8")).hexdigest()[:8], 16)
    if weights and len(weights) == len(vs) and sum(float(w) for w in weights) > 0:
        total = sum(float(w) for w in weights)
        point = (h % 10000) / 10000.0 * total
        acc = 0.0
        for v, w in zip(vs, weights):
            acc += float(w)
            if point < acc:
                return v
        return vs[-1]
    return vs[h % len(vs)]


# ── uplift ──────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class UpliftResult:
    control_mean: float
    treatment_mean: float
    uplift_pct: float
    n_control: int
    n_treatment: int
    significant: bool


def compute_uplift(control: Sequence[float], treatment: Sequence[float], *,
                   min_samples: int = 30, min_effect_pct: float = 2.0) -> UpliftResult:
    """Relative uplift of treatment vs control + a Welch-style significance flag (no scipy dep).
    Significant requires enough samples on both arms AND an effect beyond noise (|z|>=1.96) AND a
    minimum relative effect. Control-vs-treatment isolation is the anti-false-positive mechanism."""
    c = [float(x) for x in (control or [])]
    t = [float(x) for x in (treatment or [])]
    cm = sum(c) / len(c) if c else 0.0
    tm = sum(t) / len(t) if t else 0.0
    if cm:
        uplift = (tm - cm) / abs(cm) * 100.0
    else:
        uplift = 0.0 if tm == 0 else 100.0
    significant = False
    # HARD FLOOR of 2 samples per arm — a single observation gives se=0 → z=inf → spurious "significance"
    # (a coin-flip would then scale or auto-revert the live experiment). This floor holds even if a caller
    # passes min_samples=1. With n>=2, zero sample-variance with separated means is genuine separation.
    if len(c) >= max(2, min_samples) and len(t) >= max(2, min_samples):
        try:
            vc = statistics.pvariance(c)
            vt = statistics.pvariance(t)
            se = ((vc / len(c)) + (vt / len(t))) ** 0.5
            z = (abs(tm - cm) / se) if se > 0 else (float("inf") if tm != cm else 0.0)
            significant = z >= 1.96 and abs(uplift) >= float(min_effect_pct)
        except Exception:
            significant = False
    return UpliftResult(round(cm, 4), round(tm, 4), round(uplift, 2), len(c), len(t), significant)


# ── terminal decision (anti-Goodhart) ────────────────────────────────────────
def decide(*, target_uplift_pct: float, significant: bool,
           guardrail_deltas_pct: Optional[Dict[str, float]] = None,
           min_uplift_pct: float = 2.0, scale_uplift_pct: float = 10.0,
           rollback_threshold_pct: float = 2.0) -> Dict[str, Any]:
    """keep / scale / revise / revert. A guardrail degrading past the rollback threshold REVERTS even
    when the target improved (anti-Goodhart). Inconclusive → revise. No lift → revert."""
    guards = guardrail_deltas_pct or {}
    breached = {k: round(float(v), 3) for k, v in guards.items() if float(v) <= -abs(float(rollback_threshold_pct))}
    if breached:
        return {"decision": DECISION_REVERT, "reason": "guardrail_breach", "breached": breached}
    if not significant:
        return {"decision": DECISION_REVISE, "reason": "inconclusive"}
    if target_uplift_pct >= float(scale_uplift_pct):
        return {"decision": DECISION_SCALE, "reason": "strong_uplift"}
    if target_uplift_pct >= float(min_uplift_pct):
        return {"decision": DECISION_KEEP, "reason": "positive_uplift"}
    return {"decision": DECISION_REVERT, "reason": "no_uplift"}


def evaluate_experiment(*, control: Sequence[float], treatment: Sequence[float],
                        guardrail_deltas_pct: Optional[Dict[str, float]] = None,
                        **decide_kw: Any) -> Dict[str, Any]:
    """One-shot: compute uplift then the terminal decision. Returns {uplift, decision, reason, ...}."""
    up = compute_uplift(control, treatment)
    out = decide(target_uplift_pct=up.uplift_pct, significant=up.significant,
                 guardrail_deltas_pct=guardrail_deltas_pct, **decide_kw)
    out["uplift_pct"] = up.uplift_pct
    out["significant"] = up.significant
    out["n_control"] = up.n_control
    out["n_treatment"] = up.n_treatment
    return out


# ── minimal data layer ────────────────────────────────────────────────────────
def _tenant(value: Optional[str]) -> Optional[str]:
    tenant_id = str(value or "").strip()
    return tenant_id or None


def _sealed_policy(
    *,
    baseline: Optional[Dict[str, Any]],
    eligibility: Optional[Dict[str, Any]],
    min_samples: Optional[int],
    min_window_seconds: Optional[int],
    rollback_threshold_pct: Optional[float],
    guardrails: Optional[Dict[str, Any]],
    terminal_policy: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    try:
        if not isinstance(baseline, dict) or not baseline:
            return None
        if not isinstance(eligibility, dict) or not eligibility:
            return None
        if int(min_samples or 0) < 2 or int(min_window_seconds or 0) <= 0:
            return None
        if float(rollback_threshold_pct or 0) <= 0:
            return None
        allowed = list((terminal_policy or {}).get("allowed") or [])
        if not allowed or not set(allowed).issubset(
            {DECISION_KEEP, DECISION_SCALE, DECISION_REVISE, DECISION_REVERT}
        ):
            return None
        return {
            "baseline": baseline,
            "eligibility": eligibility,
            "min_samples": int(min_samples),
            "min_window_seconds": int(min_window_seconds),
            "rollback_threshold_pct": float(rollback_threshold_pct),
            "guardrails": guardrails or {},
            "terminal_policy": terminal_policy,
        }
    except (TypeError, ValueError):
        return None


def create_experiment(
    db,
    *,
    tenant_id: str,
    name: str,
    target_metric: str,
    baseline: Optional[Dict[str, Any]] = None,
    eligibility: Optional[Dict[str, Any]] = None,
    min_samples: Optional[int] = None,
    min_window_seconds: Optional[int] = None,
    rollback_threshold_pct: Optional[float] = None,
    guardrails: Optional[Dict[str, Any]] = None,
    terminal_policy: Optional[Dict[str, Any]] = None,
    status: str = "draft",
) -> Optional[str]:
    if db is None:
        return None
    tid = _tenant(tenant_id)
    policy = _sealed_policy(
        baseline=baseline, eligibility=eligibility, min_samples=min_samples,
        min_window_seconds=min_window_seconds, rollback_threshold_pct=rollback_threshold_pct,
        guardrails=guardrails, terminal_policy=terminal_policy,
    )
    if tid is None or policy is None:
        return None
    try:
        ensure_tables(db)
        eid = str(uuid.uuid4())
        # an experiment created already-live records its activation time now (started_at).
        started = _now_iso() if str(status).strip().lower() == "live" else None
        db.execute(text(
            "INSERT INTO experiment_run "
            "(id, tenant_id, name, target_metric, policy_json, policy_version, status, started_at) "
            "VALUES (:i,:t,:n,:m,:p,'experiment-policy.v1',:s,:st)"
        ), {"i": eid, "t": tid, "n": name, "m": target_metric,
            "p": json.dumps(policy, sort_keys=True, separators=(",", ":")),
            "s": status, "st": started})
        return eid
    except Exception:
        return None


def _resolve_experiment_id(db, *, tenant_id: str, experiment_id: str) -> Optional[str]:
    row = db.execute(
        text("SELECT id FROM experiment_run "
             "WHERE tenant_id=:t AND (id=:i OR name=:i) LIMIT 1"),
        {"t": tenant_id, "i": str(experiment_id)},
    ).fetchone()
    return str(row[0]) if row else None


def load_policy(db, *, tenant_id: str, experiment_id: str) -> Optional[Dict[str, Any]]:
    tid = _tenant(tenant_id)
    if db is None or tid is None:
        return None
    try:
        ensure_tables(db)
        row = db.execute(
            text("SELECT policy_json FROM experiment_run "
                 "WHERE tenant_id=:t AND (id=:i OR name=:i) LIMIT 1"),
            {"t": tid, "i": str(experiment_id)},
        ).fetchone()
        return json.loads(row[0]) if row and row[0] else None
    except Exception:
        return None


def update_policy(db, *, tenant_id: str, experiment_id: str, policy: Dict[str, Any]) -> bool:
    """Experiment policy is intentionally immutable; supersede with a new experiment."""
    return False


def record_assignment(db, *, tenant_id: str, experiment_id: str, subject_hash: str, variant: str,
                      assigned_at: Optional[str] = None) -> bool:
    """Idempotent per (experiment, subject) — the UNIQUE index closes the assignment race. ``assigned_at``
    overrides the default CURRENT_TIMESTAMP (used by tests to place assignment BEFORE a conversion so
    the post-assignment attribution window is exercised deterministically)."""
    tid = _tenant(tenant_id)
    if db is None or tid is None:
        return False
    try:
        ensure_tables(db)
        eid = _resolve_experiment_id(db, tenant_id=tid, experiment_id=experiment_id)
        if eid is None:
            return False
        existing = db.execute(
            text("SELECT 1 FROM experiment_assignment "
                 "WHERE tenant_id=:t AND experiment_id=:e AND subject_hash=:s LIMIT 1"),
            {"t": tid, "e": eid, "s": subject_hash},
        ).fetchone()
        if existing:
            return False
        if assigned_at is None:
            db.execute(text("INSERT INTO experiment_assignment "
                            "(id, tenant_id, experiment_id, subject_hash, variant) "
                            "VALUES (:i,:t,:e,:s,:v)"),
                       {"i": str(uuid.uuid4()), "t": tid, "e": eid, "s": subject_hash, "v": variant})
        else:
            db.execute(text("INSERT INTO experiment_assignment "
                            "(id, tenant_id, experiment_id, subject_hash, variant, assigned_at) "
                            "VALUES (:i,:t,:e,:s,:v,:a)"),
                       {"i": str(uuid.uuid4()), "t": tid, "e": eid, "s": subject_hash, "v": variant,
                        "a": str(assigned_at)})
        return True
    except Exception:
        return False


def is_experiment_live(db, experiment_id: str, *, tenant_id: str) -> bool:
    """True only when the experiment's status is 'live'. The nudge gate reads this every request, so a
    batch/human flipping status to 'reverted' (anti-Goodhart) stops the adaptation globally."""
    tid = _tenant(tenant_id)
    if db is None or not experiment_id or tid is None:
        return False
    try:
        ensure_tables(db)
        row = db.execute(
            text("SELECT status FROM experiment_run "
                 "WHERE tenant_id=:t AND (id = :i OR name = :i) LIMIT 1"),
            {"t": tid, "i": str(experiment_id)},
        ).fetchone()
        return bool(row) and str(row[0] or "").strip().lower() == "live"
    except Exception:
        return False


def set_status(db, *, tenant_id: str, experiment_id: str, status: str) -> bool:
    """Flip an experiment's status (e.g. draft→live, live→reverted). The reversibility lever. Stamps
    started_at on the FIRST activation (status→live) and ended_at on a terminal status, so experiment
    age + the attribution window are measured from real activation, not creation."""
    tid = _tenant(tenant_id)
    if db is None or not experiment_id or tid is None:
        return False
    try:
        ensure_tables(db)
        s = str(status).strip().lower()
        now = _now_iso()
        if s == "live":
            result = db.execute(
                text("UPDATE experiment_run SET status=:s, started_at=COALESCE(started_at, :now) "
                     "WHERE tenant_id=:t AND (id=:i OR name=:i)"),
                {"s": status, "now": now, "t": tid, "i": str(experiment_id)},
            )
        elif s in _TERMINAL_STATUSES:
            result = db.execute(
                text("UPDATE experiment_run SET status=:s, ended_at=:now "
                     "WHERE tenant_id=:t AND (id=:i OR name=:i)"),
                {"s": status, "now": now, "t": tid, "i": str(experiment_id)},
            )
        else:
            result = db.execute(
                text("UPDATE experiment_run SET status=:s "
                     "WHERE tenant_id=:t AND (id=:i OR name=:i)"),
                {"s": status, "t": tid, "i": str(experiment_id)},
            )
        return bool(result.rowcount)
    except Exception:
        return False


def record_result(
    db, *, tenant_id: str, experiment_id: str, variant: str, outcome: Dict[str, Any]
) -> Optional[str]:
    tid = _tenant(tenant_id)
    if db is None or tid is None:
        return None
    try:
        ensure_tables(db)
        eid = _resolve_experiment_id(db, tenant_id=tid, experiment_id=experiment_id)
        if eid is None:
            return None
        rid = str(uuid.uuid4())
        db.execute(text("INSERT INTO experiment_result "
                        "(id, tenant_id, experiment_id, variant, decision, uplift_pct, evidence_json) "
                        "VALUES (:i,:t,:e,:v,:d,:u,:j)"),
                   {"i": rid, "t": tid, "e": eid, "v": variant,
                    "d": str(outcome.get("decision") or ""), "u": float(outcome.get("uplift_pct") or 0.0),
                    "j": json.dumps(outcome, default=str)})
        return rid
    except Exception:
        return None
