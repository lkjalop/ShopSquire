"""transport_health() — the deploy preflight that tells the operator whether REAL sending is wired before
they enable autonomy. sandbox is always configured (stages, never transmits); smtp needs HOST + SENDER."""
from __future__ import annotations

from src.app.services.fulfillment.transport import transport_health


def test_sandbox_is_configured_but_does_not_transmit(monkeypatch):
    monkeypatch.delenv("FULFILLMENT_SUPPLIER_TRANSPORT", raising=False)
    h = transport_health()
    assert h["mode"] == "sandbox" and h["configured"] is True and h["transmits"] is False and h["missing"] == []


def test_smtp_missing_env_is_not_configured(monkeypatch):
    monkeypatch.setenv("FULFILLMENT_SUPPLIER_TRANSPORT", "smtp")
    monkeypatch.delenv("SMTP_HOST", raising=False)
    monkeypatch.delenv("SMTP_SENDER", raising=False)
    h = transport_health()
    assert h["mode"] == "smtp" and h["configured"] is False and h["transmits"] is True
    assert "SMTP_HOST" in h["missing"] and "SMTP_SENDER" in h["missing"]


def test_smtp_fully_configured(monkeypatch):
    monkeypatch.setenv("FULFILLMENT_SUPPLIER_TRANSPORT", "smtp")
    monkeypatch.setenv("SMTP_HOST", "mail.example")
    monkeypatch.setenv("SMTP_SENDER", "procurement@shopsquire.example")
    h = transport_health()
    assert h["mode"] == "smtp" and h["configured"] is True and h["missing"] == []
