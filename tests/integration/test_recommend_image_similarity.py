"""Tier 3 — image<->query relationship wiring (safe multimodal).

An image query gets a relationship classification on the payload (observability). The visual leg is
flag-gated + needs a FAISS index (inert here). Text-only queries get no image_relationship. The
classification is profile-backed (category_router) + uses only safe labels, never OCR/QR text.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.app.main import create_app
from tests.utils import default_headers
from tests.v2_catalog_fixture import grounded_v2_catalog

_CATALOG = [
    ("IMG-LAP-1", "ThinkPad gaming laptop", 159900, 5,
     {"ram_gb": 16, "storage_gb": 1024, "gaming_style": True}),
]


@pytest.fixture(scope="module", autouse=True)
def _ground_catalog():
    with grounded_v2_catalog(
        _CATALOG,
        node_handle="el-6-11-2",
        source="recommend_image_similarity",
    ):
        yield


def _suggest(uid, **params):
    client = TestClient(create_app(), headers=default_headers())
    r = client.get("/api/v1/recommend/suggest", params={"uid": uid, "query": "gaming laptop under 1800", **params})
    assert r.status_code == 200
    return r.json()


def test_text_only_query_has_no_image_relationship():
    body = _suggest("u-img-none")
    assert "image_relationship" not in body


def test_image_query_classifies_on_topic():
    # laptop image labels + laptop query -> same product type -> on_topic
    body = _suggest("u-img-on", image_labels="laptop,thinkpad", image_ocr_text="ThinkPad X1")
    rel = body.get("image_relationship")
    assert isinstance(rel, dict) and rel.get("relationship") in ("on_topic", "adjacent", "off_topic")
    assert rel.get("relationship") == "on_topic"  # laptop image + laptop query


def test_unrelated_image_never_gets_on_topic_boost():
    # produce/fruit image + laptop query -> must NOT be on_topic (no ranking boost). It may be
    # classified off_topic on the main path OR handled earlier by the off-topic image gate (absent);
    # both are safe. The exact off_topic logic is unit-tested in test_image_query_relationship.
    body = _suggest("u-img-off", image_labels="banana,fruit", image_ocr_text="organic")
    rel = body.get("image_relationship")
    assert rel is None or rel.get("relationship") != "on_topic"
    assert "results" in body
