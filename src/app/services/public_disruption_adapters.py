"""Bounded official-source adapters for distinct supply-risk semantics.

These adapters deliberately do not implement search or accept arbitrary URLs.
They return evidence envelopes; they do not infer tenant exposure, confirm a
commercial impact, screen a counterparty, or mutate procurement state.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from datetime import datetime
from typing import Any
from urllib.parse import urlencode


TextFetcher = Callable[[str, float, int], str]
JsonFetcher = Callable[[str, float, int], dict[str, Any]]

ABF_ICS_STATUS_URL = "https://icsnotifications.abf.gov.au/ics?id=ics_performance"
NOAA_DATA_URL = "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter"
DFAT_CONSOLIDATED_LIST_URL = (
    "https://www.dfat.gov.au/international-relations/security/sanctions/consolidated-list"
)


class AbfIcsStatusAdapter:
    """Read the fixed ABF status surface; absence of a status stays unknown."""

    def __init__(self, *, fetch_text: TextFetcher) -> None:
        self._fetch_text = fetch_text

    def fetch(self) -> dict[str, Any]:
        body = self._fetch_text(ABF_ICS_STATUS_URL, 5.0, 512_000)
        normalized = " ".join(re.sub(r"<[^>]+>", " ", body).lower().split())
        status = "unknown"
        if re.search(r"\b(service|system|ics)\s+(outage|unavailable|offline)\b", normalized):
            status = "outage_reported"
        elif re.search(r"\b(degraded|intermittent|performance issues?)\b", normalized):
            status = "degraded_reported"
        elif re.search(r"\b(current status|ics status)\s*:\s*(operational|available)\b", normalized):
            status = "operational_reported"
        return {
            "source_id": "au_abf_ics_operational_status",
            "source_url": ABF_ICS_STATUS_URL,
            "evidence_type": "customs_system_operational_notice",
            "operational_status": status,
            "claim_status": "reported" if status != "unknown" else "possible",
            "commercial_impact_confirmed": False,
            "tenant_exposure_resolved": False,
            "authority": "advisory_only",
        }


class NoaaPortConditionsAdapter:
    """Retrieve bounded environmental observations for an explicit station.

    NOAA PORTS observations can support a lane-risk hypothesis. They do not
    prove congestion, customs delay, terminal capacity, or cargo availability.
    """

    _PRODUCTS = frozenset({"wind", "air_pressure", "water_level", "visibility"})

    def __init__(self, *, fetch_json: JsonFetcher) -> None:
        self._fetch_json = fetch_json

    def fetch(self, *, station_id: str, product: str) -> dict[str, Any]:
        station = str(station_id or "").strip()
        kind = str(product or "").strip().lower()
        if not re.fullmatch(r"[A-Za-z0-9-]{3,20}", station):
            raise ValueError("station_id_invalid")
        if kind not in self._PRODUCTS:
            raise ValueError("product_unsupported")
        query = urlencode({
            "product": kind,
            "application": "ShopSquire",
            "date": "latest",
            "station": station,
            "time_zone": "gmt",
            "units": "metric",
            "format": "json",
        })
        url = f"{NOAA_DATA_URL}?{query}"
        payload = self._fetch_json(url, 5.0, 1_000_000)
        observations = payload.get("data")
        if not isinstance(observations, list):
            observations = []
        normalized_observations = []
        for item in observations[:100]:
            if not isinstance(item, dict):
                continue
            normalized = dict(item)
            if kind == "wind":
                normalized.update({
                    "observed_at": item.get("t"),
                    "speed": item.get("s"),
                    "direction_degrees": item.get("d"),
                })
            normalized_observations.append(normalized)
        return {
            "source_id": "noaa_tides_currents_ports",
            "request_url": url,
            "evidence_type": "port_environmental_condition",
            "station": payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {},
            "product": kind,
            "observations": normalized_observations,
            "proves_port_congestion": False,
            "tenant_exposure_resolved": False,
            "authority": "advisory_only",
        }


class DfatSanctionsRevisionAdapter:
    """Track the authoritative list revision without performing legal matching."""

    def __init__(self, *, fetch_text: TextFetcher) -> None:
        self._fetch_text = fetch_text

    def fetch(self) -> dict[str, Any]:
        body = self._fetch_text(DFAT_CONSOLIDATED_LIST_URL, 5.0, 1_500_000)
        match = re.search(
            r"last updated(?:\s+on)?\s+(\d{1,2}\s+[A-Za-z]+\s+\d{4})",
            body,
            flags=re.IGNORECASE,
        )
        revision = "unknown"
        if match:
            try:
                revision = datetime.strptime(match.group(1), "%d %B %Y").date().isoformat()
            except ValueError:
                revision = "unknown"
        return {
            "source_id": "au_dfat_sanctions_consolidated_list",
            "source_url": DFAT_CONSOLIDATED_LIST_URL,
            "source_revision": revision,
            "evidence_type": "sanctions_list_revision",
            "screening_performed": False,
            "legal_review_required_for_match": True,
            "tenant_exposure_resolved": False,
            "authority": "source_health_only",
        }
