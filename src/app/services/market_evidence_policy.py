"""Licence, provenance and contradiction policy for advisory market evidence."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable


TRUST_ORDER = {"T1": 4, "T2": 3, "T3": 2, "T4": 1}


def validate_source_policy(policy: dict[str, Any]) -> dict[str, Any]:
    required = (
        "source_system",
        "trust_tier",
        "licence_id",
        "licence_url",
        "retrieved_at",
        "terms_hash",
        "allowed_uses",
        "approved_by",
    )
    missing = [field for field in required if not policy.get(field)]
    if missing:
        return {"eligible": False, "reason": "source_policy_incomplete", "missing": missing}
    if str(policy["trust_tier"]) not in TRUST_ORDER:
        return {"eligible": False, "reason": "unsupported_trust_tier", "missing": []}
    if bool(policy.get("personal_data_allowed")):
        return {"eligible": False, "reason": "personal_data_source_disallowed", "missing": []}
    return {"eligible": True, "reason": "licensed_source", "missing": []}


def resolve_contradictions(
    findings: Iterable[dict[str, Any]],
    *,
    decision_time: datetime | None = None,
) -> dict[str, Any]:
    rows = list(findings or [])
    if not rows:
        return {"status": "insufficient_data", "winner": None, "contested": False}
    eligible = []
    for row in rows:
        policy = validate_source_policy(row.get("source_policy") or {})
        if not policy["eligible"] or not row.get("provenance_chain"):
            continue
        observed = _time(row.get("observed_at"))
        if observed is None:
            continue
        eligible.append((row, observed))
    if not eligible:
        return {"status": "insufficient_data", "winner": None, "contested": False}
    eligible.sort(
        key=lambda item: (
            TRUST_ORDER[str(item[0]["source_policy"]["trust_tier"])],
            item[1],
            float(item[0].get("confidence") or 0.0),
        ),
        reverse=True,
    )
    winner = eligible[0][0]
    directions = {str(row.get("direction") or "unknown") for row, _ in eligible}
    contested = len(directions - {"unknown"}) > 1
    return {
        "status": "contested" if contested else "resolved",
        "winner": winner,
        "contested": contested,
        "resolution_basis": "trust_tier_then_freshness_then_confidence",
        "authority": "advisory_only",
        "execution_allowed": False,
    }


def _time(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None
