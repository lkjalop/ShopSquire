import pytest

from src.app.config import get_settings
from src.app.services import secrets_manager
from src.app.routers.payments import _payment_execution_enabled


def _secure_non_payment_runtime(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("SECRETS_ALLOW_ENV_REF_IN_STRICT", "1")
    monkeypatch.setenv("REDIS_URL", "rediss://default:secret@example.redis:10000/0")
    monkeypatch.setenv("REDIS_URL_REF", "env://REDIS_URL")
    monkeypatch.setenv("AUDIT_CHAIN_EXTERNAL_ANCHOR_MODE", "blob")
    monkeypatch.setenv("BACKUP_ENCRYPTION_KEY", "test-only-backup-key")
    monkeypatch.setenv("RETENTION_CLEANUP_ENABLED", "1")
    monkeypatch.setenv("PG_ENCRYPTION_AT_REST", "1")
    monkeypatch.setenv("PAYMENT_EXECUTION_ENABLED", "0")
    monkeypatch.delenv("STRIPE_API_KEY", raising=False)
    secrets_manager._CACHE.clear()
    get_settings.cache_clear()


def test_production_can_start_without_stripe_when_payment_execution_is_disabled(monkeypatch):
    _secure_non_payment_runtime(monkeypatch)

    assert get_settings().stripe_api_key == ""


def test_production_requires_live_stripe_key_when_payment_execution_is_enabled(monkeypatch):
    _secure_non_payment_runtime(monkeypatch)
    monkeypatch.setenv("PAYMENT_EXECUTION_ENABLED", "1")
    monkeypatch.setenv("STRIPE_API_KEY", "sk_test_not_live")
    monkeypatch.setenv("STRIPE_API_KEY_REF", "env://STRIPE_API_KEY")
    secrets_manager._CACHE.clear()
    get_settings.cache_clear()

    with pytest.raises(RuntimeError, match="STRIPE_API_KEY_must_be_live_key"):
        get_settings()


def test_payment_execution_defaults_closed_in_production(monkeypatch):
    monkeypatch.delenv("PAYMENT_EXECUTION_ENABLED", raising=False)

    assert _payment_execution_enabled("production") is False
    assert _payment_execution_enabled("local") is True
