"""Vision image-hash cache (2026-06-15 latency P0).

Proves a repeat image skips the 50-86s vision call (served from cache), the cache
is namespaced + fail-open, and a vision outage is observable (degraded), not silent.
"""
from __future__ import annotations

import src.app.services.vision_cache as vc
import src.app.services.product_identity_agent as pia


def test_cache_roundtrip():
    vc.clear()
    k = vc.image_key(b"abc", "identity")
    assert vc.get(k) is None
    vc.put(k, {"brand": "msi"})
    assert vc.get(k) == {"brand": "msi"}


def test_key_namespacing():
    assert vc.image_key(b"x", "identity") != vc.image_key(b"x", "labels:triage")
    assert vc.image_key(b"x", "identity") == vc.image_key(b"x", "identity")
    assert vc.image_key(b"x", "identity") != vc.image_key(b"y", "identity")


def test_disabled_is_fail_open(monkeypatch):
    monkeypatch.setenv("VISION_CACHE_ENABLED", "0")
    vc.clear()
    k = vc.image_key(b"q", "identity")
    vc.put(k, {"a": 1})
    assert vc.get(k) is None  # disabled → always miss → caller recomputes (safe)


class _Resp:
    status_code = 200
    headers = {"content-type": "application/json"}

    def json(self):
        return {"response": '{"identified": true, "brand": "MSI", "confidence": 0.9}'}


def test_identify_caches_by_image_hash(monkeypatch):
    vc.clear()
    monkeypatch.setenv("VISION_CACHE_ENABLED", "1")
    calls = {"n": 0}

    def fake_execute(*a, **k):
        calls["n"] += 1
        return '{"identified": true, "brand": "MSI", "confidence": 0.9}'

    monkeypatch.setattr(pia, "execute_local_model_role", fake_execute)
    monkeypatch.setattr(pia, "_get_model_candidates", lambda: ["llava"])

    img = b"identical-image-bytes-123"
    r1 = pia.identify_product_from_image(img)
    r2 = pia.identify_product_from_image(img)

    assert r1.get("brand") == "MSI"
    assert r2.get("brand") == "MSI"
    assert r2.get("from_cache") is True
    assert calls["n"] == 1, "vision model must be called once; the repeat is served from cache"


def test_vision_failure_is_observable_not_silent(monkeypatch):
    vc.clear()
    monkeypatch.setenv("VISION_CACHE_ENABLED", "1")

    def boom(*a, **k):
        raise Exception("connection refused")

    monkeypatch.setattr(pia, "execute_local_model_role", boom)
    monkeypatch.setattr(pia, "_get_model_candidates", lambda: ["llava"])

    r = pia.identify_product_from_image(b"img-bytes-xyz")
    assert r.get("identified") is False
    assert r.get("degraded") is True   # failure surfaced, not a silent empty identity
    # a failed extraction must NOT be cached (so a transient outage isn't poisoned)
    assert vc.get(vc.image_key(b"img-bytes-xyz", "identity")) is None
