"""Governed catalogue of external market-data sources.

The registry says which sources may inform an advisory observation. It does not
fetch data, infer SKU exposure, or grant decision authority.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any


REGISTRY_PATH = (
    Path(__file__).resolve().parents[3] / "config" / "market_source_registry.json"
)
_REQUIRED = {
    "source_id",
    "source_system",
    "publisher",
    "trust_tier",
    "licence_id",
    "licence_url",
    "permitted_uses",
    "measurement_scope",
    "signal_types",
    "pestel_domains",
    "decision_authority",
    "personal_data_allowed",
}


@lru_cache(maxsize=4)
def _load(path: str) -> dict[str, dict[str, Any]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if int(payload.get("schema_version") or 0) != 1:
        raise ValueError("unsupported_market_source_registry_version")
    registry: dict[str, dict[str, Any]] = {}
    for raw in payload.get("sources") or []:
        if not isinstance(raw, dict):
            raise ValueError("market_source_registry_row_invalid")
        missing = sorted(_REQUIRED - set(raw))
        if missing:
            raise ValueError(f"market_source_registry_fields_missing:{','.join(missing)}")
        source = dict(raw)
        source_id = str(source["source_id"]).strip()
        if not source_id or source_id in registry:
            raise ValueError("market_source_registry_identity_invalid")
        if source["decision_authority"] != "advisory_only":
            raise ValueError("external_market_source_must_be_advisory")
        if bool(source["personal_data_allowed"]):
            raise ValueError("external_market_source_personal_data_disallowed")
        domains = set(source["pestel_domains"])
        if not domains or not domains <= {
            "political",
            "economic",
            "social",
            "technological",
            "environmental",
            "legal",
        }:
            raise ValueError("external_market_source_pestel_domains_invalid")
        registry[source_id] = source
    return registry


def load_market_source_registry(
    path: str | Path | None = None,
) -> dict[str, dict[str, Any]]:
    selected = str(Path(path).resolve()) if path else str(REGISTRY_PATH)
    return {key: dict(value) for key, value in _load(selected).items()}


def sources_for_signal(
    signal_type: str,
    *,
    permitted_use: str = "advisory_market_monitoring",
    path: str | Path | None = None,
) -> list[dict[str, Any]]:
    """Return explicitly permitted candidates; absence is an honest empty result."""
    requested = str(signal_type or "").strip()
    rows = []
    for source in load_market_source_registry(path).values():
        if requested not in set(source.get("signal_types") or []):
            continue
        uses = set(source.get("permitted_uses") or [])
        if permitted_use not in uses and "calibrate_synthetic_scenarios" not in uses:
            continue
        rows.append(source)
    return sorted(rows, key=lambda row: (int(row.get("priority") or 1000), row["source_id"]))


def govern_external_observation(
    *,
    source_id: str,
    source_record_id: str,
    signal_type: str,
    subject_id: str,
    measurement: dict[str, Any],
    geography: str,
    effective_from: str,
    effective_to: str | None,
    published_at: str,
    available_at: str,
    retrieved_at: str,
    path: str | Path | None = None,
) -> dict[str, Any]:
    """Bind a fetched row to its approved source policy without claiming SKU causality."""
    registry = load_market_source_registry(path)
    source = registry.get(str(source_id))
    if source is None:
        raise ValueError("external_market_source_not_registered")
    if str(signal_type) not in set(source.get("signal_types") or []):
        raise ValueError("external_market_signal_not_permitted")
    if not all((
        str(source_record_id or "").strip(),
        str(subject_id or "").strip(),
        isinstance(measurement, dict) and measurement.get("kind"),
        str(geography or "").strip(),
        str(effective_from or "").strip(),
        str(published_at or "").strip(),
        str(available_at or "").strip(),
        str(retrieved_at or "").strip(),
    )):
        raise ValueError("external_market_observation_scope_incomplete")
    return {
        "source_id": source["source_id"],
        "source_system": source["source_system"],
        "source_record_id": str(source_record_id),
        "signal_type": str(signal_type),
        "subject_id": str(subject_id),
        "measurement": dict(measurement),
        "measurement_scope": source["measurement_scope"],
        "pestel_domains": list(source["pestel_domains"]),
        "geography": str(geography),
        "effective_from": str(effective_from),
        "effective_to": str(effective_to) if effective_to else None,
        "published_at": str(published_at),
        "available_at": str(available_at),
        "retrieved_at": str(retrieved_at),
        "source_policy": {
            "trust_tier": source["trust_tier"],
            "licence_id": source["licence_id"],
            "licence_url": source["licence_url"],
            "permitted_uses": list(source["permitted_uses"]),
            "measurement_scope": source["measurement_scope"],
        },
        "provenance_chain": [
            f"source/{source['source_id']}",
            f"publisher/{source['publisher']}",
            f"record/{source_record_id}",
        ],
        "authority": "advisory_only",
        "can_establish_sku_exposure": False,
        "execution_allowed": False,
    }
