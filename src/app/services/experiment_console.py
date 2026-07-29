"""Ranking-experiment operator console (agnostic CORE) — promote / observe / evaluate / revert.

The live-adaptation closed loop is already built + scheduled (recommend_intelligence_stage._nudge applies
a bounded reversible nudge for TREATMENT users only when RANKING_NUDGE_EXPERIMENT_ENABLED *and* the
experiment is live, behind the adaptive_action_gate; experiment_tasks.evaluate_experiments auto-reverts
on no-lift). The one missing piece is OPERATOR control: a way to make the experiment live, watch its
assignments + last decision, evaluate on demand, and pull the revert lever.

This console only flips experiment STATUS and READS state — it adds no adaptation logic and cannot make
the nudge fire (that still needs the feature flag + a live experiment + treatment + the gate). The
experiment NAME is the canonical id ("ranking_nudge_v1", matching the nudge); experiments match by
id OR name throughout. Vertical-blind; never raises.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from sqlalchemy import text

logger = logging.getLogger(__name__)
DEFAULT_EXPERIMENT_ID = "ranking_nudge_v1"


def state(db, *, tenant_id: str, experiment_id: str = DEFAULT_EXPERIMENT_ID) -> Dict[str, Any]:
    """Operator view: status · live · per-variant assignment counts · last decision/uplift · kill switch."""
    out: Dict[str, Any] = {"experiment_id": experiment_id, "status": "absent", "live": False,
                           "assignments": {}, "last_decision": None, "last_uplift_pct": None,
                           "adaptation_killed": False}
    if db is None:
        return out
    try:
        from src.app.services.experiment_ops import adaptation_killed
        from src.app.services.experiments import ensure_tables, is_experiment_live
        ensure_tables(db)
        row = db.execute(text("SELECT id, status FROM experiment_run "
                              "WHERE tenant_id=:t AND (id=:i OR name=:i) LIMIT 1"),
                         {"t": tenant_id, "i": experiment_id}).fetchone()
        if row:
            resolved_id, out["status"] = str(row[0]), row[1]
        else:
            resolved_id = experiment_id
        out["live"] = is_experiment_live(db, experiment_id, tenant_id=tenant_id)
        counts = db.execute(text("SELECT variant, COUNT(*) FROM experiment_assignment "
                                 "WHERE tenant_id=:t AND experiment_id=:i GROUP BY variant"),
                            {"t": tenant_id, "i": resolved_id}).fetchall()
        out["assignments"] = {str(c[0]): int(c[1]) for c in counts}
        res = db.execute(text("SELECT decision, uplift_pct FROM experiment_result "
                              "WHERE tenant_id=:t AND experiment_id=:i "
                              "ORDER BY decided_at DESC LIMIT 1"),
                         {"t": tenant_id, "i": resolved_id}).fetchone()
        if res:
            out["last_decision"], out["last_uplift_pct"] = res[0], res[1]
        out["adaptation_killed"] = adaptation_killed()
        return out
    except Exception:
        return out


def promote(
    db, *, tenant_id: str, experiment_id: str = DEFAULT_EXPERIMENT_ID,
    name: Optional[str] = None, target_metric: str = "conversion",
    baseline: Optional[Dict[str, Any]] = None,
    eligibility: Optional[Dict[str, Any]] = None,
    min_samples: int = 30, min_window_seconds: int = 86400,
    rollback_threshold_pct: float = 2.0,
    guardrails: Optional[Dict[str, Any]] = None,
    terminal_policy: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Make the experiment LIVE — create it if absent, else set status=live. Returns the new state.
    (The nudge still needs RANKING_NUDGE_EXPERIMENT_ENABLED to actually fire — this only arms it.)"""
    if db is not None:
        try:
            from src.app.services.experiments import create_experiment, ensure_tables, set_status
            ensure_tables(db)
            exists = db.execute(text("SELECT 1 FROM experiment_run "
                                     "WHERE tenant_id=:t AND (id=:i OR name=:i) LIMIT 1"),
                                {"t": tenant_id, "i": experiment_id}).fetchone()
            if exists:
                set_status(db, tenant_id=tenant_id, experiment_id=experiment_id, status="live")
            else:
                create_experiment(
                    db, tenant_id=tenant_id, name=name or experiment_id,
                    target_metric=target_metric, status="live",
                    baseline=baseline, eligibility=eligibility,
                    min_samples=min_samples, min_window_seconds=min_window_seconds,
                    rollback_threshold_pct=rollback_threshold_pct,
                    guardrails=guardrails,
                    terminal_policy=terminal_policy,
                )
            db.commit()
        except Exception as exc:
            logger.warning("experiment_console.promote failed: %s", exc)
    return state(db, tenant_id=tenant_id, experiment_id=experiment_id)


def evaluate_now(
    db, *, tenant_id: str, experiment_id: str = DEFAULT_EXPERIMENT_ID
) -> Dict[str, Any]:
    """Run the uplift→decide→auto-revert evaluation now (the rollback safety net, on demand). Returns the
    outcome incl. {decision, uplift_pct, reverted?}."""
    if db is None:
        return {"error": "no_db"}
    try:
        from src.app.services.experiment_eval import evaluate_experiment
        out = evaluate_experiment(db, experiment_id, tenant_id=tenant_id)
        # Module 2/6 close-the-loop: persist the terminal outcome so "did the change work?" is answerable
        # and any future execution is measurable/reversible. Best-effort — never breaks the evaluation.
        from src.app.services import market_outcome
        market_outcome.record_outcome(
            db, decision_ref=experiment_id, decision=out.get("decision"), uplift_pct=out.get("uplift_pct"),
            significant=out.get("significant"), n_control=out.get("n_control"),
            n_treatment=out.get("n_treatment"), reverted=bool(out.get("reverted")),
            source="experiment", tenant_id=tenant_id)
        db.commit()
        return out
    except Exception as exc:
        logger.warning("experiment_console.evaluate_now failed: %s", exc)
        return {"error": "eval_failed"}


def revert(db, *, tenant_id: str, experiment_id: str = DEFAULT_EXPERIMENT_ID) -> Dict[str, Any]:
    """The manual revert lever — flip the experiment to 'reverted' so the nudge stops globally. Returns
    the new state. Reverting a LIVE experiment is an operator-initiated rollback, so it's recorded as a
    terminal outcome (auto-reverts are recorded by evaluate_now) — the governance rollback count reflects it."""
    if db is not None:
        try:
            was_live = bool(state(db, tenant_id=tenant_id, experiment_id=experiment_id).get("live"))
            from src.app.services.experiments import set_status
            set_status(db, tenant_id=tenant_id, experiment_id=experiment_id, status="reverted")
            if was_live:
                try:
                    from src.app.services import market_outcome
                    market_outcome.record_outcome(db, decision_ref=experiment_id, decision="revert",
                                                  reverted=True, source="operator", tenant_id=tenant_id)
                except Exception as exc:
                    logger.debug("revert outcome record failed: %s", exc)
            db.commit()
        except Exception as exc:
            logger.warning("experiment_console.revert failed: %s", exc)
    return state(db, tenant_id=tenant_id, experiment_id=experiment_id)
