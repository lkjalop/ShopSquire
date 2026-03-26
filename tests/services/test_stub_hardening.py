"""Tests verifying that demo/stub code paths are removed and providers fail-closed.

Covers:
- llm_providers: no API key → RuntimeError, not stub text
- _corroborate_order: SQLite in-memory proves the real query path works
- order_items migration: table structure matches what _corroborate_order expects
"""
from __future__ import annotations

import os
import pytest


# ─────────────────────────────────────────────────────────────────────────────
# llm_providers.py — fail-closed when no API key configured
# ─────────────────────────────────────────────────────────────────────────────
from src.app.services.llm_providers import AnthropicProvider, OpenAIProvider, MistralProvider, get_provider


def _unset(*keys):
    """Context manager that temporarily clears env keys."""
    import contextlib

    @contextlib.contextmanager
    def _ctx():
        saved = {k: os.environ.pop(k, None) for k in keys}
        try:
            yield
        finally:
            for k, v in saved.items():
                if v is not None:
                    os.environ[k] = v
    return _ctx()


def test_anthropic_no_key_raises():
    with _unset("ANTHROPIC_API_KEY"):
        with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
            AnthropicProvider().generate("hello")


def test_openai_no_key_raises():
    with _unset("OPENAI_API_KEY"):
        with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
            OpenAIProvider().generate("hello")


def test_mistral_no_key_raises():
    with _unset("MISTRAL_API_KEY"):
        with pytest.raises(RuntimeError, match="MISTRAL_API_KEY"):
            MistralProvider().generate("hello")


def test_get_provider_no_keys_raises():
    """get_provider() with no keys and no LLM_PROVIDER set → RuntimeError."""
    with _unset("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "MISTRAL_API_KEY", "LLM_PROVIDER"):
        with pytest.raises(RuntimeError, match="No LLM provider"):
            get_provider()


def test_no_stub_text_in_provider_responses():
    """Confirm stub strings are gone from the source."""
    import inspect
    import src.app.services.llm_providers as _mod
    src_code = inspect.getsource(_mod)
    assert "[anthropic stub response]" not in src_code
    assert "[openai stub response]" not in src_code
    assert "[mistral stub response]" not in src_code


# ─────────────────────────────────────────────────────────────────────────────
# _corroborate_order — real SQLite path
# ─────────────────────────────────────────────────────────────────────────────
import sqlalchemy as sa
from sqlalchemy.orm import Session
from unittest.mock import patch


def _make_sqlite_session(rows: list[dict] | None = None):
    """Create an in-memory SQLite DB with order_items table and optional rows."""
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.connect() as conn:
        conn.execute(sa.text("""
            CREATE TABLE orders (id TEXT PRIMARY KEY)
        """))
        conn.execute(sa.text("""
            CREATE TABLE order_items (
                id TEXT PRIMARY KEY,
                order_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                sku TEXT NOT NULL,
                product_name TEXT,
                brand TEXT,
                quantity INTEGER NOT NULL DEFAULT 1,
                unit_price_cents INTEGER,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """))
        if rows:
            for r in rows:
                conn.execute(
                    sa.text(
                        "INSERT INTO order_items (id, order_id, user_id, sku, product_name, brand) "
                        "VALUES (:id, :order_id, :user_id, :sku, :product_name, :brand)"
                    ),
                    r,
                )
        conn.commit()
    return engine


def _corroborate(uid, sku, pkg, engine):
    """Call _corroborate_order with a patched db_session."""
    from contextlib import contextmanager

    @contextmanager
    def _fake_session():
        with engine.connect() as conn:
            yield conn

    with patch("src.app.routers.returns.db_session", _fake_session):
        from src.app.routers.returns import _corroborate_order
        return _corroborate_order(uid, sku, pkg)


def test_corroborate_order_found_no_mismatch():
    engine = _make_sqlite_session([{
        "id": "oi-1", "order_id": "ord-1", "user_id": "u1",
        "sku": "LAPTOP-X", "product_name": "Lenovo ThinkPad", "brand": "lenovo",
    }])
    pkg = {"cv_result": {"raw_labels": ["lenovo", "thinkpad"], "extracted_text": ""}}
    result = _corroborate("u1", "LAPTOP-X", pkg, engine)
    assert result["order_found"] is True
    assert result["mismatch"] is False
    assert result["fraud_score_delta"] == 0


def test_corroborate_no_matching_order():
    engine = _make_sqlite_session([])  # empty order_items
    pkg = {}
    result = _corroborate("u1", "LAPTOP-X", pkg, engine)
    assert result["order_found"] is False
    assert result["fraud_score_delta"] == 15
    assert result["detail"] == "no_matching_order"


def test_corroborate_brand_mismatch():
    engine = _make_sqlite_session([{
        "id": "oi-2", "order_id": "ord-2", "user_id": "u2",
        "sku": "LAPTOP-Y", "product_name": "Dell XPS", "brand": "dell",
    }])
    # CV output shows apple — doesn't mention dell
    pkg = {"cv_result": {"raw_labels": ["apple", "macbook"], "extracted_text": "apple logo"}}
    result = _corroborate("u2", "LAPTOP-Y", pkg, engine)
    assert result["order_found"] is True
    assert result["mismatch"] is True
    assert result["fraud_score_delta"] == 20
    assert "brand_mismatch" in result["detail"]


def test_corroborate_no_uid_short_circuits():
    from src.app.routers.returns import _corroborate_order
    result = _corroborate_order("", "LAPTOP-X", {})
    assert result["fraud_score_delta"] == 15
    assert result["detail"] == "no_uid_provided"
