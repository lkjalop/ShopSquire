"""Bounded extraction of non-authoritative facts from buyer conversations."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from sqlalchemy import text

from src.app.models.db import db_session


_CURRENCIES = "AUD|USD|NZD|CAD|GBP|EUR|JPY|SGD"
_TTL_DAYS = {
    "stated_requirement": 90,
    "brand_exclusion": 180,
    "budget": 30,
    "pack_uom_preference": 180,
    "delivery_requirement": 30,
    "payment_term_request": 90,
    "recurring_use_case": 365,
    "refusal_reason": 180,
}


@dataclass(frozen=True)
class FactCandidate:
    category: str
    value: dict[str, Any]
    excerpt: str
    confidence: float


def _clean(value: str, limit: int = 240) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip(" \t\r\n,.;:")[:limit]


def _add(
    facts: list[FactCandidate],
    category: str,
    value: dict[str, Any],
    excerpt: str,
    confidence: float,
) -> None:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"))
    if any(
        item.category == category
        and json.dumps(item.value, sort_keys=True, separators=(",", ":")) == encoded
        for item in facts
    ):
        return
    facts.append(FactCandidate(category, value, _clean(excerpt), confidence))


def extract_conversation_facts(message: str) -> list[FactCandidate]:
    """Extract only the bounded commercial vocabulary; never infer authority."""
    source = _clean(message, 2000)
    if not source:
        return []
    facts: list[FactCandidate] = []

    budget = re.compile(
        rf"\b(?:budget(?:\s+is|\s+of)?|under|up\s+to|max(?:imum)?|spend)\s*"
        rf"(?P<currency>{_CURRENCIES}|\$|£|€)?\s*"
        r"(?P<amount>\d[\d,]*(?:\.\d{1,2})?)\b",
        re.I,
    )
    for match in budget.finditer(source):
        currency = str(match.group("currency") or "").upper()
        currency = {"$": "AMBIGUOUS_DOLLAR", "£": "GBP", "€": "EUR"}.get(
            currency, currency or "UNSPECIFIED"
        )
        _add(
            facts,
            "budget",
            {
                "amount": match.group("amount").replace(",", ""),
                "currency": currency,
                "scope": "unspecified",
            },
            match.group(0),
            0.92 if currency not in {"AMBIGUOUS_DOLLAR", "UNSPECIFIED"} else 0.76,
        )

    exclusion = re.compile(
        r"\b(?:no|avoid|exclude|excluding|anything\s+but)\s+"
        r"(?P<brands>[A-Za-z0-9][A-Za-z0-9 &+\-]{1,70})"
        r"(?=$|[,.!?;]|\s+(?:please|because|for|with|under|over|and\s+(?:deliver|ship|cost)))",
        re.I,
    )
    for match in exclusion.finditer(source):
        for brand in re.split(r"\s*(?:,|/|\bor\b)\s*", match.group("brands"), flags=re.I):
            brand = _clean(brand, 60)
            if brand and len(brand.split()) <= 4:
                _add(facts, "brand_exclusion", {"brand": brand}, match.group(0), 0.88)

    pack_patterns = (
        re.compile(r"\b(?P<uom>pack|case|box|carton)\s+of\s+(?P<count>\d{1,6})\b", re.I),
        re.compile(r"\b(?P<count>\d{1,6})\s*(?P<uom>units?|pieces?|packs?|cases?|boxes?|cartons?)\b", re.I),
    )
    for pattern in pack_patterns:
        for match in pattern.finditer(source):
            _add(
                facts,
                "pack_uom_preference",
                {"quantity": int(match.group("count")), "uom": match.group("uom").lower()},
                match.group(0),
                0.9,
            )

    delivery = re.compile(
        r"\b(?:deliver(?:y|ed)?|ship(?:ped|ping)?)\s+"
        r"(?P<value>(?:by|before|within|no later than)\s+[^,.!?;]{2,80})",
        re.I,
    )
    for match in delivery.finditer(source):
        _add(
            facts,
            "delivery_requirement",
            {"requirement": _clean(match.group("value"), 100)},
            match.group(0),
            0.86,
        )

    payment = re.compile(
        r"\b(?:payment\s+terms?\s*(?:of|are|:)?\s*)?"
        r"(?P<term>net\s*(?:7|14|15|30|45|60|90)|prepaid|cash\s+on\s+delivery|cod)\b",
        re.I,
    )
    for match in payment.finditer(source):
        _add(
            facts,
            "payment_term_request",
            {"term": re.sub(r"\s+", " ", match.group("term").upper())},
            match.group(0),
            0.94,
        )

    recurring = re.compile(
        r"\b(?P<cadence>(?:every|each)\s+(?:day|week|month|quarter|year)|"
        r"daily|weekly|monthly|quarterly|annually|recurring)\b",
        re.I,
    )
    for match in recurring.finditer(source):
        _add(
            facts,
            "recurring_use_case",
            {"cadence": _clean(match.group("cadence")).lower()},
            match.group(0),
            0.85,
        )

    refusal = re.compile(
        r"\b(?:no|decline|reject|not\s+interested|won't\s+proceed)\s+"
        r"(?:thanks?\s*)?(?:because|due\s+to|as)\s+(?P<reason>[^.!?]{3,180})",
        re.I,
    )
    for match in refusal.finditer(source):
        _add(
            facts,
            "refusal_reason",
            {"reason": _clean(match.group("reason"), 180)},
            match.group(0),
            0.86,
        )

    requirement = re.compile(
        r"\b(?:we|i)\s+(?:need|require|want|am\s+looking\s+for|are\s+looking\s+for)\s+"
        r"(?P<value>[^.!?]{3,220})",
        re.I,
    )
    for match in requirement.finditer(source):
        value = _clean(match.group("value"))
        if value:
            _add(
                facts,
                "stated_requirement",
                {"text": value},
                match.group(0),
                0.8,
            )
    return facts[:24]


def record_conversation_fact_observations(
    *,
    tenant_id: str,
    subject_ref: str,
    source_message_id: str,
    message: str,
    session_id: str | None = None,
    trace_id: str | None = None,
    observed_at: datetime | None = None,
    candidates: Iterable[FactCandidate] | None = None,
) -> list[dict[str, Any]]:
    """Append extracted observations to storage separate from Party authority."""
    tenant = _clean(tenant_id, 128)
    subject = _clean(subject_ref, 160)
    message_id = _clean(source_message_id, 160)
    if not all((tenant, subject, message_id)):
        raise ValueError("conversation_fact_scope_required")
    now = observed_at or datetime.now(timezone.utc)
    facts = list(candidates if candidates is not None else extract_conversation_facts(message))
    recorded: list[dict[str, Any]] = []
    with db_session() as db:
        for fact in facts:
            value_json = json.dumps(
                fact.value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
            )
            fact_id = hashlib.sha256(
                f"{tenant}|{message_id}|{fact.category}|{value_json}".encode()
            ).hexdigest()
            if db.execute(
                text("SELECT 1 FROM conversation_fact_observation WHERE id=:id"),
                {"id": fact_id},
            ).fetchone():
                recorded.append({"id": fact_id, "category": fact.category, "duplicate": True})
                continue
            expiry = now + timedelta(days=_TTL_DAYS[fact.category])
            provenance = {
                "kind": "buyer_conversation",
                "source_message_id": message_id,
                "trace_id": trace_id,
                "extractor": "bounded_rules_v1",
            }
            db.execute(
                text(
                    """
                    INSERT INTO conversation_fact_observation
                    (id, tenant_id, subject_ref, session_id, source_message_id,
                     trace_id, category, normalized_value_json, source_excerpt,
                     provenance_json, confidence, authority, status,
                     observed_at, expires_at, created_at)
                    VALUES
                    (:id, :tenant, :subject, :session, :message, :trace,
                     :category, :value, :excerpt, :provenance, :confidence,
                     'observation_only', 'active', :observed, :expires, :created)
                    """
                ),
                {
                    "id": fact_id,
                    "tenant": tenant,
                    "subject": subject,
                    "session": session_id,
                    "message": message_id,
                    "trace": trace_id,
                    "category": fact.category,
                    "value": value_json,
                    "excerpt": fact.excerpt,
                    "provenance": json.dumps(provenance, sort_keys=True, separators=(",", ":")),
                    "confidence": fact.confidence,
                    "observed": now.isoformat(),
                    "expires": expiry.isoformat(),
                    "created": now.isoformat(),
                },
            )
            recorded.append(
                {
                    "id": fact_id,
                    "category": fact.category,
                    "duplicate": False,
                    "authority": "observation_only",
                    "expires_at": expiry.isoformat(),
                }
            )
        db.commit()
    return recorded
