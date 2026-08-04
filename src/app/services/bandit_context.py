"""Request-scoped bandit-arm context (agnostic CORE).

The LinUCB ranking arm is chosen deep inside RecommendationService scoring; this ContextVar carries
it forward to the attribution capture seam (E0) so the SAME arm that ranked the results is the arm
that later gets rewarded (E3) — without threading the value through ~7k lines of route. Mirrors the
existing trace-id ContextVar pattern. Agnostic: an "arm" is an opaque label.

Why this matters: before this, E0 stamped the A/B *variant* ("A"/"B") as the arm, so the reward
feed would have credited a bogus arm. get_bandit_arm() returns the real LinUCB arm
(balanced / explore_novelty / price_value / personalized_heavy) for the current request.
"""
from __future__ import annotations

from contextvars import ContextVar
from typing import Optional

_BANDIT_ARM: "ContextVar[Optional[str]]" = ContextVar("recommend_bandit_arm", default=None)


def set_bandit_arm(arm: Optional[str]) -> None:
    """Record the LinUCB arm chosen for the current request's ranking."""
    _BANDIT_ARM.set(str(arm).strip() if arm and str(arm).strip() else None)


def get_bandit_arm() -> Optional[str]:
    """The arm chosen for the current request, or None if ranking hasn't run / set it."""
    return _BANDIT_ARM.get() or None


def reset_bandit_arm() -> None:
    """Clear the arm (defensive — guards against a value leaking across reused worker contexts)."""
    _BANDIT_ARM.set(None)
