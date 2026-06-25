"""Unit tests for the request-scoped bandit-arm ContextVar (services/bandit_context.py)."""
from __future__ import annotations

from src.app.services.bandit_context import get_bandit_arm, reset_bandit_arm, set_bandit_arm


def test_default_is_none():
    reset_bandit_arm()
    assert get_bandit_arm() is None


def test_set_and_get():
    set_bandit_arm("explore_novelty")
    assert get_bandit_arm() == "explore_novelty"
    reset_bandit_arm()


def test_blank_and_none_normalize_to_none():
    set_bandit_arm("  ")
    assert get_bandit_arm() is None
    set_bandit_arm(None)
    assert get_bandit_arm() is None


def test_reset_clears():
    set_bandit_arm("balanced")
    reset_bandit_arm()
    assert get_bandit_arm() is None
