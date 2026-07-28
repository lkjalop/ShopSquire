from __future__ import annotations

import json
import io
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.app.services.market_evidence_policy import validate_source_policy
from src.app.services.market_source_registry import load_market_source_registry
from src.app.services.public_market_source_fetch import (
    PublicHttpResponse,
    fetch_public_market_source,
)


def _db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    db = sessionmaker(bind=engine, future=True)()
    db.execute(text("""
        CREATE TABLE market_source_fetch_revision (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            source_id TEXT NOT NULL,
            request_key TEXT NOT NULL,
            revision_number INTEGER NOT NULL,
            request_json TEXT NOT NULL,
            outcome TEXT NOT NULL,
            http_status INTEGER,
            etag TEXT,
            last_modified TEXT,
            content_sha256 TEXT,
            normalized_json TEXT,
            source_policy_json TEXT NOT NULL,
            error_code TEXT,
            retrieved_at TIMESTAMP NOT NULL,
            expires_at TIMESTAMP NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
            UNIQUE (tenant_id, source_id, request_key, revision_number)
        )
    """))
    db.commit()
    return db


def _recall_body() -> bytes:
    return json.dumps([{
        "RecallID": 42,
        "RecallNumber": "26042",
        "RecallDate": "2026-07-20T00:00:00",
        "LastPublishDate": "2026-07-21T00:00:00",
        "Title": "Synthetic fixture recall",
        "URL": "https://www.cpsc.gov/Recalls/2026/example",
        "Products": [{"Name": "Example Toaster"}],
        "Hazards": [{"Name": "Fire"}],
        "ConsumerContact": "must not be retained",
    }]).encode()


def _pink_sheet_body() -> bytes:
    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Monthly Prices"
    sheet.append(["World Bank Commodity Price Data"])
    sheet.append(["monthly prices"])
    sheet.append(["nominal"])
    sheet.append(["Updated on July 02, 2026"])
    sheet.append([None, "Crude oil, average", "Aluminum"])
    sheet.append([None, "($/bbl)", "($/mt)"])
    sheet.append(["2026M04", 70.0, 2300.0])
    sheet.append(["2026M05", 75.0, 2280.0])
    sheet.append(["2026M06", 72.0, 2350.0])
    output = io.BytesIO()
    workbook.save(output)
    return output.getvalue()


def test_registry_exposes_only_approved_live_origins():
    sources = load_market_source_registry()
    supported = [
        source for source in sources.values() if source.get("fetch_profile")
    ]
    assert sorted(source["source_id"] for source in supported) == [
        "cpsc_recalls",
        "world_bank_pink_sheet",
    ]
    assert {
        source["fetch_profile"]["allowed_host"] for source in supported
    } == {"www.saferproducts.gov", "thedocs.worldbank.org"}


def test_fetch_persists_revision_and_reuses_tenant_scoped_cache():
    db = _db()
    calls = []

    def transport(url, params, headers, timeout):
        calls.append((url, params, headers, timeout))
        return PublicHttpResponse(
            status_code=200,
            headers={"etag": '"fixture-v1"'},
            body=_recall_body(),
        )

    now = datetime(2026, 7, 29, tzinfo=timezone.utc)
    first = fetch_public_market_source(
        db,
        tenant_id="tenant-a",
        source_id="cpsc_recalls",
        query={"recall_date_start": "2026-07-01"},
        now=now,
        transport=transport,
        enabled=True,
    )
    assert first["outcome"] == "observed"
    assert first["revision_number"] == 1
    assert first["execution_allowed"] is False
    observation = first["observations"][0]
    assert observation["authority"] == "advisory_only"
    assert observation["can_establish_sku_exposure"] is False
    assert "ConsumerContact" not in json.dumps(observation)
    assert validate_source_policy(observation["source_policy"])["eligible"] is True

    cached = fetch_public_market_source(
        db,
        tenant_id="tenant-a",
        source_id="cpsc_recalls",
        query={"recall_date_start": "2026-07-01"},
        now=now + timedelta(minutes=1),
        transport=transport,
        enabled=True,
    )
    assert cached["outcome"] == "cache_hit"
    assert len(calls) == 1

    other_tenant = fetch_public_market_source(
        db,
        tenant_id="tenant-b",
        source_id="cpsc_recalls",
        query={"recall_date_start": "2026-07-01"},
        now=now + timedelta(minutes=1),
        transport=transport,
        enabled=True,
    )
    assert other_tenant["outcome"] == "observed"
    assert len(calls) == 2


def test_expired_cache_uses_conditional_request_and_appends_revision():
    db = _db()
    responses = [
        PublicHttpResponse(200, {"etag": '"fixture-v1"'}, _recall_body()),
        PublicHttpResponse(304, {"etag": '"fixture-v1"'}, b""),
    ]
    seen_headers = []

    def transport(_url, _params, headers, _timeout):
        seen_headers.append(dict(headers))
        return responses.pop(0)

    now = datetime(2026, 7, 29, tzinfo=timezone.utc)
    fetch_public_market_source(
        db,
        tenant_id="tenant-a",
        source_id="cpsc_recalls",
        query={"product_name": "toaster"},
        now=now,
        transport=transport,
        enabled=True,
    )
    refreshed = fetch_public_market_source(
        db,
        tenant_id="tenant-a",
        source_id="cpsc_recalls",
        query={"product_name": "toaster"},
        now=now + timedelta(hours=7),
        transport=transport,
        enabled=True,
    )
    assert refreshed["outcome"] == "not_modified"
    assert refreshed["revision_number"] == 2
    assert seen_headers[1]["If-None-Match"] == '"fixture-v1"'
    assert db.execute(text(
        "SELECT count(*) FROM market_source_fetch_revision"
    )).scalar() == 2


def test_fetch_requires_a_bounded_filter_and_is_disabled_by_default(monkeypatch):
    db = _db()
    monkeypatch.delenv("PUBLIC_MARKET_FETCH_ENABLED", raising=False)
    disabled = fetch_public_market_source(
        db,
        tenant_id="tenant-a",
        source_id="cpsc_recalls",
        query={},
    )
    assert disabled["outcome"] == "disabled"
    with pytest.raises(ValueError, match="public_market_bounded_filter_required"):
        fetch_public_market_source(
            db,
            tenant_id="tenant-a",
            source_id="cpsc_recalls",
            query={},
            enabled=True,
        )


def test_rate_limit_is_typed_and_never_sleeps_inside_request():
    db = _db()
    result = fetch_public_market_source(
        db,
        tenant_id="tenant-a",
        source_id="cpsc_recalls",
        query={"title": "dresser"},
        enabled=True,
        transport=lambda *_args: PublicHttpResponse(
            429,
            {"retry-after": "120"},
            b"",
        ),
    )
    assert result["outcome"] == "rate_limited"
    assert result["retry_after"] == "120"
    assert result["execution_allowed"] is False


def test_world_bank_prices_are_bounded_series_observations():
    db = _db()
    result = fetch_public_market_source(
        db,
        tenant_id="tenant-a",
        source_id="world_bank_pink_sheet",
        query={
            "series": ["Crude oil, average"],
            "signal_type": "transport_fuel_price",
        },
        enabled=True,
        transport=lambda *_args: PublicHttpResponse(
            200,
            {"etag": '"pink-sheet-v1"'},
            _pink_sheet_body(),
        ),
    )
    assert result["outcome"] == "observed"
    assert len(result["observations"]) == 3
    latest = result["observations"][-1]
    assert latest["measurement"]["value"] == 72.0
    assert latest["measurement"]["direction"] == "decrease"
    assert latest["measurement"]["currency"] == "USD"
    assert latest["can_establish_sku_exposure"] is False


def test_world_bank_rejects_unknown_or_unbounded_series():
    db = _db()

    def response(*_args):
        return PublicHttpResponse(200, {}, _pink_sheet_body())

    with pytest.raises(ValueError, match="public_market_series_invalid"):
        fetch_public_market_source(
            db,
            tenant_id="tenant-a",
            source_id="world_bank_pink_sheet",
            query={},
            enabled=True,
            transport=response,
        )
    malformed = fetch_public_market_source(
        db,
        tenant_id="tenant-a",
        source_id="world_bank_pink_sheet",
        query={"series": ["Not a real benchmark"]},
        enabled=True,
        transport=response,
    )
    assert malformed["outcome"] == "malformed"
