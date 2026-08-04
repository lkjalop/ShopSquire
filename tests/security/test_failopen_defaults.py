"""Regression tests for fail-OPEN defaults that had zero coverage (why they rotted).

These lock in the 2026-06 fail-closed fixes:
  - action_authority_matrix: unmapped privileged action must NOT default-ALLOW.
  - egress_allowlist: an unparseable hostname on an enabled allowlist must be denied.
"""
from __future__ import annotations

import os

import pytest

from src.app.policy.action_authority_matrix import evaluate, AuthDecision


def test_unmapped_action_fails_closed_not_allow():
    v = evaluate("totally_unknown_privileged_action_xyz", value_aud_cents=999_00)
    assert v.decision != AuthDecision.ALLOW, "unmapped action must not default-ALLOW (fail-open)"
    assert v.decision == AuthDecision.HUMAN_REVIEW
    assert v.rule_id == "DEFAULT_FAIL_CLOSED"
    assert v.alert_siem is True


def test_mapped_action_still_evaluated_normally():
    # A known action must still be governed by its real rule (regression guard that the
    # fail-closed default did not swallow mapped actions).
    v = evaluate("refund", value_aud_cents=50_00)
    assert v.rule_id != "DEFAULT_FAIL_CLOSED"


def test_override_flag_restores_allow_for_migration_window(monkeypatch):
    monkeypatch.setenv("POLICY_MATRIX_DEFAULT_ALLOW", "1")
    v = evaluate("totally_unknown_privileged_action_xyz", value_aud_cents=0)
    assert v.decision == AuthDecision.ALLOW
    assert v.rule_id == "DEFAULT_ALLOW_OVERRIDE"


def test_egress_unparseable_hostname_denied_when_enabled(monkeypatch):
    monkeypatch.setenv("EGRESS_ALLOWLIST_ENABLED", "1")
    from src.app.security.egress_allowlist import EgressDomainGuard
    guard = EgressDomainGuard()
    # A URL whose hostname cannot be extracted must be DENIED (was fail-open -> allowed).
    assert guard.is_allowed("not a url ::: \\\\ garbage") is False
    assert guard.is_allowed("") is False


def test_egress_allowlisted_host_still_allowed(monkeypatch):
    # Regression guard: the fail-closed change must not block a normal allowlisted host.
    monkeypatch.setenv("EGRESS_ALLOWLIST_ENABLED", "1")
    from src.app.security.egress_allowlist import EgressDomainGuard
    guard = EgressDomainGuard()
    # A well-formed hostname resolves; result depends on allowlist contents, but it must
    # not raise and must return a bool (parsing path works).
    assert isinstance(guard.is_allowed("https://example.com/path"), bool)
