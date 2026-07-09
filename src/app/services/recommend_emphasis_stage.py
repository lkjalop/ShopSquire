"""Storefront-emphasis execution lever (agnostic CORE) — David Phase 3, the FIRST customer-facing
adaptation, built on the same cage as the ranking nudge.

For a TREATMENT subject (small canary) of a LIVE experiment, behind the unified adaptive-action gate, it
sets ``payload['right_panel']['emphasis']`` to a profile-defined messaging variant (value / urgency /
features). The copy is DATA from the active StoreProfile — NEVER free-form LLM. The lever is:

  • flag-gated (STOREFRONT_EMPHASIS_EXPERIMENT_ENABLED, default OFF) + global kill-switch honoured;
  • reversible — experiment_console.revert flips status, is_experiment_live() → off → no emphasis globally;
  • measured — assignments recorded; the experiment eval → market_outcome closes the loop;
  • gated — an actual apply must pass adaptive_action_gate.authorize (confidence + audit), else no-op.

Mutates ``payload`` in place; a no-op (flag off / control / not-live / gate-deny) leaves it byte-identical.
Vertical-blind (the only flavour is the profile copy); never raises.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, Optional

DEFAULT_EXPERIMENT_ID = "storefront_emphasis_v1"
_FLAG = "STOREFRONT_EMPHASIS_EXPERIMENT_ENABLED"


def _flag_on(flags: Dict[str, Any], key: str) -> bool:
    # env wins, then flags (2026-07-09 convention fix — the 9th-mute-layer class: flags-dict-only
    # gates strand every env-driven deployment because load_feature_flags merges almost no env).
    import os
    v = os.getenv(key)
    if v is None:
        v = (flags or {}).get(key)
    if v is None:
        return False
    return str(v).strip().lower() in ("1", "true", "yes", "on")


def apply_storefront_emphasis(payload: Dict[str, Any], *, flags: Optional[Dict[str, Any]] = None,
                              simulate: bool = False, uid_hash: Any = None, uid: Any = None,
                              trace_id: Any = None, decision_id: Any = None,
                              profile_fn: Optional[Callable] = None,
                              trace_fn: Optional[Callable] = None) -> None:
    """Apply the gated storefront-emphasis variant to payload['right_panel']['emphasis']. No-op unless the
    flag is on, the experiment is live, the subject is TREATMENT, and the adaptive-action gate ALLOWs."""
    flags = flags or {}
    if not (_flag_on(flags, _FLAG) and not simulate):
        return
    rp = payload.get("right_panel")
    if not isinstance(rp, dict):
        return  # only adapt an already-built panel
    try:
        from src.app.models.db import db_session
        from src.app.services.experiment_ops import adaptation_killed, canary_assignment
        from src.app.services.experiments import assign_variant, is_experiment_live, record_assignment
        if adaptation_killed():
            return  # global kill switch
        variants = (profile_fn("storefront_emphasis_variants", default={}) or {}) if profile_fn else {}
        if not isinstance(variants, dict) or not variants:
            return  # no profile copy → nothing to apply (vertical without this lever)
        keys = sorted(k for k in variants if str(variants.get(k) or "").strip())
        if not keys:
            return
        exp_id = str(flags.get("STOREFRONT_EMPHASIS_EXPERIMENT_ID") or DEFAULT_EXPERIMENT_ID)
        subject = str(uid_hash or uid or "")
        try:
            import os as _os
            canary = float(_os.getenv("STOREFRONT_EMPHASIS_CANARY_FRACTION")
                           or flags.get("STOREFRONT_EMPHASIS_CANARY_FRACTION") or 0.1)
        except (TypeError, ValueError):
            canary = 0.1
        variant = canary_assignment(experiment_id=exp_id, subject=subject, canary_fraction=canary)
        with db_session() as db:
            live = is_experiment_live(db, exp_id)
            record_assignment(db, experiment_id=exp_id, subject_hash=subject, variant=variant)
            db.commit()
        emphasis: Dict[str, Any] = {"experiment_id": exp_id, "variant": variant, "live": bool(live),
                                    "applied": False}
        if variant == "treatment" and live:
            from src.app.services.adaptive_action_gate import authorize
            # deterministic + stable emphasis key for the subject (consistent across turns)
            key = assign_variant(experiment_id=f"{exp_id}:key", subject=subject, variants=keys)
            with db_session() as gdb:
                gate = authorize(gdb, action_type="template_phrasing", confidence=1.0,
                                 subject=subject, target=f"storefront:{key}")
            emphasis["gate"] = gate.reason
            if gate.allowed:
                emphasis.update({"applied": True, "key": key, "text": str(variants.get(key) or "")})
                rp["emphasis"] = emphasis
        payload.setdefault("storefront_emphasis", emphasis)  # envelope for observability (even control)
        if trace_fn is not None:
            trace_fn(trace_id=trace_id, event_type="storefront_emphasis", source_type="agent",
                     source_id="ExperimentGate", target_type="ui", target_id=decision_id, payload=emphasis)
    except Exception as exc:
        try:
            from src.app.services.safe_stage import record_partial_failure
            record_partial_failure("storefront_emphasis", exc, trace_id=trace_id)
        except Exception:
            pass
