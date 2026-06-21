"""Safe internet search — recommend.py wiring (flag-gated, NullFetcher = no network)."""
from __future__ import annotations

import os

from fastapi.testclient import TestClient

from src.app.main import app
from tests.utils import default_headers

client = TestClient(app, headers=default_headers())


def _suggest(uid):
    r = client.get("/api/v1/recommend/suggest", params={"uid": uid, "query": "gaming laptop under 1800"})
    assert r.status_code == 200
    return r.json()


def test_disabled_by_default_no_external_field():
    body = _suggest("u-ext-off")
    # default off -> the external_research key is not attached (owned results untouched)
    assert "external_research" not in body or body.get("external_research") == []
    assert "results" in body


def test_enabled_attaches_separate_labeled_source_not_results():
    os.environ["EXTERNAL_RESEARCH_ENABLED"] = "true"
    try:
        body = _suggest("u-ext-on")
        # NullFetcher -> empty external research, but the SEPARATE field + labeled source exist
        assert body.get("external_research") == []
        st = body.get("external_research_status")
        assert isinstance(st, dict) and st.get("source") == "external_research"
        # owned results are a DIFFERENT field and remain intact
        assert "results" in body and body["external_research"] is not body["results"]
    finally:
        os.environ.pop("EXTERNAL_RESEARCH_ENABLED", None)
