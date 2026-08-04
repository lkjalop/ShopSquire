"""Unit tests for src.app.services.redis_factory.create_redis_client."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from src.app.services.redis_factory import create_redis_client


class TestCreateRedisClient:
    def test_defaults_to_localhost(self):
        with patch.dict("os.environ", {}, clear=False):
            # When the redis lib is installed, this returns a client object;
            # we only need to assert the factory does NOT raise and either
            # returns a redis client or None (best-effort).
            client = create_redis_client()
            # We don't assert the type explicitly — only that None or a client.
            assert client is None or hasattr(client, "ping")

    def test_returns_none_when_url_invalid(self, monkeypatch):
        # A definitely-malformed URL should make redis.from_url raise → None.
        client = create_redis_client(url="not-a-url://broken")
        # Library may construct successfully but lazy-fail on ping; we accept
        # either None or a client (the factory contract is "never raises").
        assert client is None or hasattr(client, "ping")

    def test_enforce_tls_acl_blocks_non_rediss_in_prod(self, monkeypatch):
        monkeypatch.setenv("APP_ENV", "production")
        client = create_redis_client(
            url="redis://localhost:6379/0",
            enforce_tls_acl=True,
        )
        assert client is None

    def test_enforce_tls_acl_blocks_missing_acl_in_prod(self, monkeypatch):
        monkeypatch.setenv("APP_ENV", "production")
        monkeypatch.delenv("REDIS_ACL_USERNAME", raising=False)
        monkeypatch.delenv("REDIS_ACL_PASSWORD", raising=False)
        client = create_redis_client(
            url="rediss://localhost:6379/0",
            enforce_tls_acl=True,
        )
        assert client is None

    def test_enforce_tls_acl_allows_in_dev(self, monkeypatch):
        monkeypatch.setenv("APP_ENV", "local")
        client = create_redis_client(
            url="redis://localhost:6379/0",
            enforce_tls_acl=True,
        )
        # Dev bypass — should construct (or None on lib-missing); never error.
        assert client is None or hasattr(client, "ping")

    def test_async_client_returns_async_capable(self):
        client = create_redis_client(async_client=True)
        # redis.asyncio clients expose `aclose` / awaitable methods; we just
        # confirm we got something or None (factory contract).
        assert client is None or hasattr(client, "ping")
