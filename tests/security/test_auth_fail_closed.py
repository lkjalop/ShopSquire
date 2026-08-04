"""The auth layer must not accept the well-known dev default key in a non-dev environment.

Regression guard for the "auth defaults to a known key" fail-open: `_role_keys()` used to fall back to
`local-merchant-key` whenever MERCHANT_API_KEY was unset — so a prod deploy that forgot to set the key
silently accepted a guessable credential. In non-dev (APP_ENV=production) an UNSET key must resolve to a
non-matchable value; dev/local keeps the convenience default. `_role_keys`/`_non_dev_env` read os.getenv
live, so plain monkeypatch (no module reload) exercises the real behaviour.
"""
from __future__ import annotations

from src.app.security import auth


def test_unset_key_is_rejected_in_non_dev(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("MERCHANT_API_KEY", raising=False)
    monkeypatch.delenv("OWNER_API_KEY", raising=False)
    monkeypatch.delenv("DEVELOPER_API_KEY", raising=False)
    # the guessable defaults must NOT authenticate when the env keys are unset in prod
    assert auth.get_role_from_key("local-merchant-key") is None
    assert auth.get_role_from_key("local-owner-key") is None
    assert auth.get_role_from_key("local-developer-key") is None
    # an empty resolved slot must never be matched by an empty presented key
    assert auth._role_keys()[auth.ROLE_MERCHANT] == ""


def test_explicitly_set_key_still_authenticates_in_non_dev(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("MERCHANT_API_KEY", "a-strong-prod-key-123")
    assert auth.get_role_from_key("a-strong-prod-key-123") == auth.ROLE_MERCHANT
    assert auth.get_role_from_key("local-merchant-key") is None


def test_dev_keeps_the_convenience_default(monkeypatch):
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.delenv("MERCHANT_API_KEY", raising=False)
    assert auth.get_role_from_key("local-merchant-key") == auth.ROLE_MERCHANT
