"""Bounded, tenant-scoped fetching of credential-free official market sources.

Only registry-approved HTTPS origins and parsers are callable. Raw provider
text is never treated as SKU exposure or execution authority.
"""
from __future__ import annotations

import hashlib
import json
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from sqlalchemy import text

from src.app.services.market_evidence_policy import resolve_contradictions
from src.app.services.market_source_registry import (
    govern_external_observation,
    load_market_source_registry,
)


_TABLE = "market_source_fetch_revision"
_MAX_ROWS = 100


@dataclass(frozen=True)
class PublicHttpResponse:
    status_code: int
    headers: dict[str, str]
    body: bytes


Transport = Callable[
    [str, dict[str, str], dict[str, str], float],
    PublicHttpResponse,
]


def _utc(value: datetime | None = None) -> datetime:
    selected = value or datetime.now(timezone.utc)
    if selected.tzinfo is None:
        selected = selected.replace(tzinfo=timezone.utc)
    return selected.astimezone(timezone.utc)


def _request_key(query: dict[str, str]) -> str:
    return hashlib.sha256(
        json.dumps(query, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _default_transport(
    url: str,
    params: dict[str, str],
    headers: dict[str, str],
    timeout: float,
) -> PublicHttpResponse:
    import httpx

    with httpx.Client(
        timeout=httpx.Timeout(timeout),
        follow_redirects=True,
        headers={"User-Agent": "ShopSquire-market-intelligence/1.0", **headers},
    ) as client:
        response = client.get(url, params=params)
    return PublicHttpResponse(
        status_code=int(response.status_code),
        headers={str(key).lower(): str(value) for key, value in response.headers.items()},
        body=bytes(response.content),
    )


def _normalize_cpsc_query(query: dict[str, Any]) -> dict[str, str]:
    mapping = {
        "recall_date_start": "RecallDateStart",
        "recall_date_end": "RecallDateEnd",
        "product_name": "ProductName",
        "title": "RecallTitle",
    }
    normalized = {"format": "json"}
    for source_key, provider_key in mapping.items():
        value = str(query.get(source_key) or "").strip()
        if value:
            if len(value) > 120:
                raise ValueError("public_market_query_value_too_long")
            normalized[provider_key] = value
    if len(normalized) == 1:
        raise ValueError("public_market_bounded_filter_required")
    return normalized


def _cpsc_observations(
    rows: Any,
    *,
    retrieved_at: str,
) -> list[dict[str, Any]]:
    if not isinstance(rows, list):
        raise ValueError("public_market_response_shape_invalid")
    observations: list[dict[str, Any]] = []
    for row in rows[:_MAX_ROWS]:
        if not isinstance(row, dict):
            continue
        record_id = str(row.get("RecallNumber") or row.get("RecallID") or "").strip()
        recall_date = str(row.get("RecallDate") or "").strip()
        published_at = str(row.get("LastPublishDate") or recall_date).strip()
        if not record_id or not recall_date:
            continue
        products = row.get("Products") if isinstance(row.get("Products"), list) else []
        product_names = sorted({
            str(product.get("Name") or "").strip()
            for product in products
            if isinstance(product, dict) and str(product.get("Name") or "").strip()
        })
        subject = product_names[0] if product_names else str(row.get("Title") or record_id)
        measurement = {
            "kind": "product_recall",
            "direction": "adverse",
            "recall_number": record_id,
            "title": str(row.get("Title") or "")[:500],
            "products": product_names[:20],
            "hazards": [
                str(hazard.get("Name") or "").strip()
                for hazard in (row.get("Hazards") or [])
                if isinstance(hazard, dict) and str(hazard.get("Name") or "").strip()
            ][:20],
            "source_url": str(row.get("URL") or "")[:1000],
        }
        observations.append(govern_external_observation(
            source_id="cpsc_recalls",
            source_record_id=record_id,
            signal_type="product_recall",
            subject_id=f"cpsc-product:{subject.casefold()}",
            measurement=measurement,
            geography="US",
            effective_from=recall_date,
            effective_to=None,
            published_at=published_at,
            available_at=published_at,
            retrieved_at=retrieved_at,
        ))
    return observations


def _latest_revision(
    db,
    *,
    tenant_id: str,
    source_id: str,
    request_key: str,
) -> dict[str, Any] | None:
    try:
        row = db.execute(text(
            f"SELECT revision_number, outcome, etag, last_modified, normalized_json, "
            f"expires_at FROM {_TABLE} WHERE tenant_id=:tenant AND source_id=:source "
            "AND request_key=:request_key ORDER BY revision_number DESC LIMIT 1"
        ), {
            "tenant": tenant_id,
            "source": source_id,
            "request_key": request_key,
        }).mappings().first()
    except Exception:
        return None
    return dict(row) if row else None


def _parse_time(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return _utc(parsed)
    except (TypeError, ValueError):
        return None


def _append_revision(
    db,
    *,
    tenant_id: str,
    source_id: str,
    request_key: str,
    revision_number: int,
    request: dict[str, str],
    outcome: str,
    now: datetime,
    expires_at: datetime,
    source_policy: dict[str, Any],
    http_status: int | None = None,
    etag: str | None = None,
    last_modified: str | None = None,
    content_sha256: str | None = None,
    normalized: list[dict[str, Any]] | None = None,
    error_code: str | None = None,
) -> None:
    db.execute(text(
        f"INSERT INTO {_TABLE} "
        "(id, tenant_id, source_id, request_key, revision_number, request_json, "
        "outcome, http_status, etag, last_modified, content_sha256, "
        "normalized_json, source_policy_json, error_code, retrieved_at, expires_at) "
        "VALUES (:id,:tenant,:source,:request_key,:revision,:request_json,:outcome,"
        ":http_status,:etag,:last_modified,:content_sha256,:normalized_json,"
        ":source_policy_json,:error_code,:retrieved_at,:expires_at)"
    ), {
        "id": uuid.uuid4().hex,
        "tenant": tenant_id,
        "source": source_id,
        "request_key": request_key,
        "revision": revision_number,
        "request_json": json.dumps(request, sort_keys=True),
        "outcome": outcome,
        "http_status": http_status,
        "etag": etag,
        "last_modified": last_modified,
        "content_sha256": content_sha256,
        "normalized_json": (
            json.dumps(normalized, sort_keys=True) if normalized is not None else None
        ),
        "source_policy_json": json.dumps(source_policy, sort_keys=True),
        "error_code": error_code,
        "retrieved_at": now,
        "expires_at": expires_at,
    })
    db.commit()


def group_contradictions(
    observations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for observation in observations:
        key = (
            str(observation.get("subject_id") or ""),
            str(observation.get("signal_type") or ""),
        )
        groups.setdefault(key, []).append(observation)
    return [
        {
            "subject_id": subject,
            "signal_type": signal,
            **resolve_contradictions(rows),
        }
        for (subject, signal), rows in sorted(groups.items())
    ]


def fetch_public_market_source(
    db,
    *,
    tenant_id: str,
    source_id: str,
    query: dict[str, Any],
    now: datetime | None = None,
    transport: Transport | None = None,
    enabled: bool | None = None,
) -> dict[str, Any]:
    """Fetch, normalize and revision an approved source without raising provider errors."""
    tenant = str(tenant_id or "").strip()
    if not tenant:
        raise ValueError("public_market_tenant_required")
    allow_live = enabled if enabled is not None else (
        os.getenv("PUBLIC_MARKET_FETCH_ENABLED", "0").strip().lower()
        in {"1", "true", "yes", "on"}
    )
    if not allow_live:
        return {
            "source_id": source_id,
            "outcome": "disabled",
            "authority": "advisory_only",
            "execution_allowed": False,
        }
    source = load_market_source_registry().get(str(source_id))
    if source is None:
        raise ValueError("external_market_source_not_registered")
    profile = source.get("fetch_profile")
    if not isinstance(profile, dict):
        return {
            "source_id": source_id,
            "outcome": "unsupported",
            "authority": "advisory_only",
            "execution_allowed": False,
        }
    if profile["kind"] != "cpsc_recalls_json":
        raise ValueError("external_market_source_fetch_kind_invalid")
    request = _normalize_cpsc_query(query)
    request_key = _request_key(request)
    stamp = _utc(now)
    latest = _latest_revision(
        db,
        tenant_id=tenant,
        source_id=source_id,
        request_key=request_key,
    )
    expiry = _parse_time(latest.get("expires_at")) if latest else None
    if latest and expiry and expiry > stamp and latest.get("normalized_json"):
        observations = json.loads(latest["normalized_json"])
        return {
            "source_id": source_id,
            "outcome": "cache_hit",
            "revision_number": int(latest["revision_number"]),
            "observations": observations,
            "contradictions": group_contradictions(observations),
            "fresh_until": expiry.isoformat(),
            "authority": "advisory_only",
            "execution_allowed": False,
        }
    headers: dict[str, str] = {}
    if latest and latest.get("etag"):
        headers["If-None-Match"] = str(latest["etag"])
    if latest and latest.get("last_modified"):
        headers["If-Modified-Since"] = str(latest["last_modified"])
    ttl = max(60, int(profile.get("ttl_seconds") or 3600))
    fresh_until = stamp + timedelta(seconds=ttl)
    revision = int(latest.get("revision_number") or 0) + 1 if latest else 1
    source_policy = {
        "source_system": source["source_system"],
        "licence_id": source["licence_id"],
        "licence_url": source["licence_url"],
        "permitted_uses": source["permitted_uses"],
        "measurement_scope": source["measurement_scope"],
    }
    try:
        response = (transport or _default_transport)(
            str(profile["url"]),
            request,
            headers,
            float(profile.get("timeout_seconds") or 8),
        )
    except Exception:
        return {
            "source_id": source_id,
            "outcome": "unavailable",
            "error_code": "provider_unavailable",
            "authority": "advisory_only",
            "execution_allowed": False,
        }
    if len(response.body) > int(profile.get("max_response_bytes") or 2_000_000):
        return {
            "source_id": source_id,
            "outcome": "malformed",
            "error_code": "response_too_large",
            "authority": "advisory_only",
            "execution_allowed": False,
        }
    normalized: list[dict[str, Any]]
    outcome = "observed"
    if response.status_code == 304 and latest and latest.get("normalized_json"):
        normalized = json.loads(latest["normalized_json"])
        outcome = "not_modified"
    elif response.status_code == 429:
        return {
            "source_id": source_id,
            "outcome": "rate_limited",
            "retry_after": response.headers.get("retry-after"),
            "authority": "advisory_only",
            "execution_allowed": False,
        }
    elif response.status_code < 200 or response.status_code >= 300:
        return {
            "source_id": source_id,
            "outcome": "unavailable",
            "http_status": response.status_code,
            "authority": "advisory_only",
            "execution_allowed": False,
        }
    else:
        try:
            normalized = _cpsc_observations(
                json.loads(response.body.decode("utf-8")),
                retrieved_at=stamp.isoformat(),
            )
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
            return {
                "source_id": source_id,
                "outcome": "malformed",
                "error_code": "provider_payload_invalid",
                "authority": "advisory_only",
                "execution_allowed": False,
            }
    content_hash = hashlib.sha256(response.body).hexdigest() if response.body else None
    try:
        _append_revision(
            db,
            tenant_id=tenant,
            source_id=source_id,
            request_key=request_key,
            revision_number=revision,
            request=request,
            outcome=outcome,
            now=stamp,
            expires_at=fresh_until,
            source_policy=source_policy,
            http_status=response.status_code,
            etag=response.headers.get("etag") or (latest or {}).get("etag"),
            last_modified=(
                response.headers.get("last-modified")
                or (latest or {}).get("last_modified")
            ),
            content_sha256=content_hash,
            normalized=normalized,
        )
    except Exception:
        db.rollback()
        return {
            "source_id": source_id,
            "outcome": "unavailable",
            "error_code": "fetch_revision_store_unavailable",
            "authority": "advisory_only",
            "execution_allowed": False,
        }
    return {
        "source_id": source_id,
        "outcome": outcome,
        "revision_number": revision,
        "observations": normalized,
        "contradictions": group_contradictions(normalized),
        "fresh_until": fresh_until.isoformat(),
        "authority": "advisory_only",
        "can_establish_sku_exposure": False,
        "execution_allowed": False,
    }
