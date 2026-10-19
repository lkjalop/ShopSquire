from contextlib import contextmanager

import pytest

from src.app.security import buyer_principal


@pytest.mark.parametrize("tenant", ["default", "foreign-shop"])
def test_failed_membership_lookup_cannot_grant_default_or_foreign_access(monkeypatch, tenant):
    @contextmanager
    def unavailable():
        raise RuntimeError("controlled membership database failure")
        yield

    monkeypatch.setenv("BUYER_TENANT_BINDINGS_JSON", "{}")
    monkeypatch.setattr(buyer_principal, "db_session", unavailable)
    assert buyer_principal._tenant_allowed("native-nondefault-buyer", tenant) is False


def test_explicit_revocation_never_falls_through_to_native_membership(monkeypatch):
    monkeypatch.setenv("BUYER_TENANT_BINDINGS_JSON", '{"native-buyer":[]}')

    def should_not_query():
        raise AssertionError("explicit deployment revocation is authoritative")

    monkeypatch.setattr(buyer_principal, "db_session", should_not_query)
    assert buyer_principal._tenant_allowed("native-buyer", "default") is False
