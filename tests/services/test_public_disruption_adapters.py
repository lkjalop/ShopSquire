import pytest

from src.app.services.public_disruption_adapters import (
    AbfIcsStatusAdapter,
    DfatSanctionsRevisionAdapter,
    NoaaPortConditionsAdapter,
)


def test_abf_adapter_reports_explicit_outage_but_never_confirms_commercial_impact():
    adapter = AbfIcsStatusAdapter(
        fetch_text=lambda url, timeout, max_bytes: (
            "<html><h1>ICS Operational Status</h1>"
            "<p>Current status: service outage. Import declarations are unavailable.</p></html>"
        )
    )

    result = adapter.fetch()

    assert result["source_id"] == "au_abf_ics_operational_status"
    assert result["operational_status"] == "outage_reported"
    assert result["claim_status"] == "reported"
    assert result["commercial_impact_confirmed"] is False
    assert result["authority"] == "advisory_only"


def test_abf_adapter_returns_unknown_when_page_has_no_explicit_status():
    result = AbfIcsStatusAdapter(
        fetch_text=lambda url, timeout, max_bytes: "Subscribe to cargo notifications"
    ).fetch()
    assert result["operational_status"] == "unknown"
    assert result["claim_status"] == "possible"


def test_noaa_port_adapter_is_environmental_evidence_not_congestion_evidence():
    adapter = NoaaPortConditionsAdapter(
        fetch_json=lambda url, timeout, max_bytes: {
            "metadata": {"id": "9414290", "name": "San Francisco"},
            "data": [{"t": "2026-08-03 09:00", "s": "31.2", "d": "270"}],
        }
    )

    result = adapter.fetch(station_id="9414290", product="wind")

    assert result["evidence_type"] == "port_environmental_condition"
    assert result["proves_port_congestion"] is False
    assert result["observations"][0]["speed"] == "31.2"
    assert "9414290" in result["request_url"]


def test_noaa_port_adapter_rejects_unbounded_station_or_product():
    adapter = NoaaPortConditionsAdapter(fetch_json=lambda *args: {})
    with pytest.raises(ValueError, match="station_id_invalid"):
        adapter.fetch(station_id="http://internal", product="wind")
    with pytest.raises(ValueError, match="product_unsupported"):
        adapter.fetch(station_id="9414290", product="predictions")


def test_dfat_adapter_tracks_official_revision_without_doing_fuzzy_legal_matching():
    html = (
        '<a href="/sites/default/files/australian-sanctions-consolidated-list.xlsx">'
        "Australian Sanctions Consolidated List</a>, last updated on 23 July 2026."
    )
    result = DfatSanctionsRevisionAdapter(
        fetch_text=lambda url, timeout, max_bytes: html
    ).fetch()

    assert result["source_revision"] == "2026-07-23"
    assert result["screening_performed"] is False
    assert result["legal_review_required_for_match"] is True
    assert result["authority"] == "source_health_only"
