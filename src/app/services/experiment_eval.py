"""Experiment evaluation runtime (agnostic CORE) — closes the self-rolling-back loop.

Reads each LIVE experiment's per-subject target metric (revenue-per-assigned-subject, from the
attribution conversion_event joined to experiment_assignment), runs the Module-6b decision math
(compute_uplift → decide with anti-Goodhart), records the result, and AUTO-REVERTS (set_status →
'reverted') on a losing or guardrail-breaching outcome. is_experiment_live() then returns False on the
next request, so the ranking nudge stops globally — the rollback is autonomous and bounded.

Guardrails (margin / returns) are injected via ``guardrail_fn`` so the anti-Goodhart check uses real
data once a returns/margin adapter exists; with none, decide() runs on uplift alone (honest — it can
only revert on no-lift until a guardrail source is wired). Vertical-blind; never raises.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from sqlalchemy import text

from src.app.services.experiments import (
    DECISION_REVERT,
    compute_uplift,
    decide,
    ensure_tables,
    record_result,
    set_status,
)


def _subject_metric_by_variant(db, experiment_id: str) -> Dict[str, List[float]]:
    """Revenue-per-assigned-subject ($), grouped by variant. A subject with no conversion → 0, so the
    metric is revenue-per-visitor (the deck's target), not just converters."""
    rows = db.execute(
        text(
            "SELECT a.variant, a.subject_hash, COALESCE(SUM(c.value_cents), 0) "
            "FROM experiment_assignment a "
            "LEFT JOIN conversion_event c ON c.uid_hash = a.subject_hash "
            "WHERE a.experiment_id = :e "
            "GROUP BY a.variant, a.subject_hash"
        ),
        {"e": str(experiment_id)},
    ).fetchall()
    by_variant: Dict[str, List[float]] = {}
    for variant, _subject, val in rows:
        by_variant.setdefault(str(variant), []).append(float(val or 0) / 100.0)
    return by_variant


def returns_guardrail(db, experiment_id: str) -> Dict[str, float]:
    """The real anti-Goodhart guardrail: return-rate degradation per variant. A treatment that raises
    the return rate (refunded/chargebacked orders among its conversions) yields a NEGATIVE 'returns'
    delta, so decide() REVERTS even if revenue improved (winning on revenue while hurting trust/margin).
    Returns {} when the link can't be computed (then decide runs on uplift alone)."""
    try:
        rows = db.execute(
            text(
                "SELECT a.variant, COUNT(c.order_id) AS conv, "
                "SUM(CASE WHEN o.status IN ('refunded','chargebacked') THEN 1 ELSE 0 END) AS ret "
                "FROM experiment_assignment a "
                "JOIN conversion_event c ON c.uid_hash = a.subject_hash "
                "LEFT JOIN orders o ON o.id = c.order_id "
                "WHERE a.experiment_id = :e GROUP BY a.variant"
            ),
            {"e": str(experiment_id)},
        ).fetchall()
    except Exception:
        return {}
    rate: Dict[str, float] = {}
    for variant, conv, ret in rows:
        c = float(conv or 0)
        rate[str(variant)] = (float(ret or 0) / c) if c > 0 else 0.0
    cr = rate.get("control")
    tr = rate.get("treatment")
    if cr is None or tr is None:
        return {}
    if cr > 0:
        delta_pct = (tr - cr) / cr * 100.0
    else:
        delta_pct = 0.0 if tr == 0 else 100.0
    return {"returns": round(-delta_pct, 3)}  # more returns → negative → breach


def evaluate_experiment(
    db,
    experiment_id: str,
    *,
    guardrail_fn: Optional[Callable[[Any, str], Dict[str, float]]] = None,
    min_samples: int = 30,
    decide_kw: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Evaluate one experiment: uplift → decision → record → auto-revert on REVERT."""
    by_variant = _subject_metric_by_variant(db, experiment_id)
    control = by_variant.get("control", [])
    treatment = by_variant.get("treatment", [])
    up = compute_uplift(control, treatment, min_samples=min_samples)
    guards = (guardrail_fn(db, experiment_id) if guardrail_fn else {}) or {}
    outcome = decide(target_uplift_pct=up.uplift_pct, significant=up.significant,
                     guardrail_deltas_pct=guards, **(decide_kw or {}))
    outcome.update({"uplift_pct": up.uplift_pct, "significant": up.significant,
                    "n_control": up.n_control, "n_treatment": up.n_treatment,
                    "experiment_id": str(experiment_id)})
    record_result(db, experiment_id=experiment_id, variant="treatment", outcome=outcome)
    if outcome.get("decision") == DECISION_REVERT:
        set_status(db, experiment_id=experiment_id, status="reverted")  # AUTONOMOUS ROLLBACK
        outcome["reverted"] = True
    return outcome


def _safe_eval(db, eid: str, **kw) -> Optional[Dict[str, Any]]:
    try:
        return evaluate_experiment(db, eid, **kw)
    except Exception:
        return None


def evaluate_live_experiments(
    db,
    *,
    guardrail_fn: Optional[Callable[[Any, str], Dict[str, float]]] = None,
    min_samples: int = 30,
    decide_kw: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Evaluate every LIVE experiment; auto-revert losers/guardrail-breachers. Returns the outcomes."""
    if db is None:
        return []
    try:
        ensure_tables(db)
        ids = [r[0] for r in db.execute(text("SELECT id FROM experiment_run WHERE status = 'live'")).fetchall()]
    except Exception:
        return []
    out = [r for r in (_safe_eval(db, eid, guardrail_fn=guardrail_fn, min_samples=min_samples, decide_kw=decide_kw)
                       for eid in ids) if r]
    try:
        db.commit()
    except Exception:
        return out
    return out
