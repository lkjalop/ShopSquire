"""Controlled template phrasing (agnostic CORE) — the SECOND low-risk adaptation.

Varies ONLY the presentation/tone of the assistant message between equivalent, claim-free templates —
never the facts, never a product spec/price/quantity/claim. It is the deck's "controlled template
phrasing" step, deliberately AFTER the ranking-nudge canary has proven automatic rollback.

Safety rails, all on by default:
  • experiment-gated + small canary  — only a fraction of TREATMENT subjects ever see a variant;
  • global kill switch               — ADAPTATION_KILL_SWITCH=1 forces control everywhere;
  • claim-safety guard               — if a variant would change ANY number/claim content, it is
                                       discarded and control (the original message) is returned.

Vertical-blind: operates on an opaque message string; the styles add tone words only.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Optional, Tuple

PHRASING_EXPERIMENT_DEFAULT_ID = "template_phrasing_v1"
_DIGITS = re.compile(r"\d")


def _warm(message: str) -> str:
    """Add a warm lead-in — tone only, no facts. Idempotent (won't stack on an already-warm opener)."""
    m = (message or "").strip()
    if not m:
        return m
    if m.lower().startswith(("happy to help", "glad to help", "sure,", "sure!", "here's what", "here is what")):
        return m
    return f"Happy to help! {m}"


# style registry — control is identity; every variant is a claim-free presentational transform.
_STYLES = {
    "control": lambda m: m,
    "treatment": _warm,
}


def _claim_safe(original: str, transformed: str) -> bool:
    """A phrasing variant MUST NOT change number/claim content (no new spec/price/quantity/digit)."""
    return _DIGITS.findall(original or "") == _DIGITS.findall(transformed or "")


def choose_and_apply(message: str, *, variant: str) -> Tuple[str, str]:
    """Apply the style for ``variant``; returns (message, applied_variant). Falls back to control if
    the transform would alter claim content or errors. ``applied`` is 'treatment' only when the text
    actually changed, else 'control'."""
    fn = _STYLES.get(str(variant), _STYLES["control"])
    try:
        out = fn(message or "")
    except Exception:
        return message, "control"
    if str(variant) == "treatment" and not _claim_safe(message, out):
        return message, "control"  # guard: never let phrasing alter claims
    return (out, "treatment") if (str(variant) == "treatment" and out != (message or "")) else (message, "control")


def apply_phrasing_experiment(db, message: str, *, subject: str,
                              flags: Optional[Dict[str, Any]] = None) -> Tuple[str, Optional[Dict[str, Any]]]:
    """The gated entry point. Returns (possibly-rephrased message, info dict | None). Honors the global
    kill switch, the experiment's live status, and the small canary. Never raises — on any error it
    returns the ORIGINAL message and None (control)."""
    flags = flags or {}
    try:
        from src.app.services.experiment_ops import adaptation_killed, canary_assignment
        from src.app.services.experiments import is_experiment_live, record_assignment
        if adaptation_killed():
            return message, {"variant": "control", "live": False, "applied": "control", "killed": True}
        exp_id = str(flags.get("TEMPLATE_PHRASING_EXPERIMENT_ID") or PHRASING_EXPERIMENT_DEFAULT_ID)
        try:
            canary = float(flags.get("TEMPLATE_PHRASING_CANARY_FRACTION") or 0.1)
        except Exception:
            canary = 0.1
        live = is_experiment_live(db, exp_id)
        variant = canary_assignment(experiment_id=exp_id, subject=subject, canary_fraction=canary) if live else "control"
        if live and db is not None:
            record_assignment(db, experiment_id=exp_id, subject_hash=subject, variant=variant)
            db.commit()
        out, applied = choose_and_apply(message, variant=variant if live else "control")
        return out, {"experiment_id": exp_id, "variant": variant, "live": bool(live), "applied": applied}
    except Exception:
        return message, None
