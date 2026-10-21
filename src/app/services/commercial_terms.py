"""Typed, non-authorizing commercial terms observed in one buyer utterance.

This is deliberately separate from ``BudgetParse``.  A hardware budget is a scalar
constraint; enterprise software commonly adds seats/endpoints, billing cadence and a
contract horizon.  These observations may shape a sourcing brief, but never authorize
an RFQ send, purchase order or payment.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional

from src.app.services.budget_grammar import classify_budget_scope, parse_budget


@dataclass(frozen=True)
class CommercialTerms:
    currency: str = "USD"
    quantity: Optional[int] = None
    quantity_unit: Optional[str] = None
    unit_price: Optional[float] = None
    billing_cadence: Optional[str] = None
    contract_term_months: Optional[int] = None
    one_time_fees: Optional[float] = None
    recurring_fees: Optional[float] = None
    renewal_assumptions: Optional[str] = None
    budget_scope: str = "unknown"
    tco_horizon_months: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: Dict[str, Any] | None) -> "CommercialTerms":
        raw = value if isinstance(value, dict) else {}
        allowed = {name for name in cls.__dataclass_fields__}
        return cls(**{key: raw[key] for key in allowed if key in raw})


_CURRENCY = {
    "aud": "AUD", "usd": "USD", "cad": "CAD", "nzd": "NZD", "sgd": "SGD",
    "hkd": "HKD", "gbp": "GBP", "eur": "EUR", "jpy": "JPY",
}
_UNITS = {'seat': 'seat', 'seats': 'seat', 'user': 'user', 'users': 'user', 'device': 'device', 'devices': 'device', 'endpoint': 'endpoint', 'endpoints': 'endpoint', 'licence': 'licence', 'licences': 'licence', 'license': 'licence', 'licenses': 'licence', 'unit': 'unit', 'units': 'unit'}




def stated_currency(text: str, *, money_only: bool = False) -> str | None:
    """An explicit unambiguous currency; a bare dollar sign has no ISO identity."""
    pattern=r"\b(aud|usd|cad|nzd|sgd|hkd|gbp|eur|jpy)\b"+(r"(?=\s*[$€£¥]?\s*\d)" if money_only else '')
    currencies={_CURRENCY[m] for m in re.findall(pattern,str(text).lower())}
    if '€' in text:currencies.add('EUR')
    if '£' in text:currencies.add('GBP')
    return next(iter(currencies)) if len(currencies)==1 else None


def parse_commercial_terms(text: str, *, default_currency: str = "USD") -> CommercialTerms:
    q = str(text or "")
    ql = q.lower()
    currency = stated_currency(q) or str(default_currency or 'USD').upper()

    parsed_budget = parse_budget(q)
    quantity = None
    quantity_unit = None
    from src.app.platform.store_profile import profile_slot
    from src.app.services.bulk_intent import extract_quantity_span
    configured_units = profile_slot('commercial_quantity_units', default={})
    units = {**_UNITS, **(configured_units if isinstance(configured_units, dict) else {})}
    unit_pattern = '|'.join(re.escape(key) for key in sorted(units, key=len, reverse=True))
    observed_count = extract_quantity_span(
        re.sub(r'(?<=\d),(?=\d)', '', ql), unit_nouns=units, max_qty=100_000_000,
    )
    quantity_match = re.search(
        r"\b(\d[\d,]{0,8})\s+(?:[a-z][a-z0-9+.-]*\s+){0,3}"
        rf"({unit_pattern})\b", ql,
    )
    budget_span = parsed_budget.source_span if parsed_budget is not None else None
    overlaps_budget = bool(
        quantity_match and budget_span
        and quantity_match.start(1) < budget_span[1]
        and quantity_match.end(1) > budget_span[0]
    )
    currency_prefixed = bool(
        quantity_match
        and re.search(
            r"(?:[\$â‚¬Â£]|\b(?:aud|usd|cad|nzd|sgd|hkd|gbp|eur|jpy))\s*$",
            ql[max(0, quantity_match.start(1) - 8):quantity_match.start(1)],
        )
    )
    if (quantity_match and observed_count and not overlaps_budget and not currency_prefixed
            and observed_count[0] == int(quantity_match.group(1).replace(",", ""))):
        quantity = int(quantity_match.group(1).replace(",", ""))
        quantity_unit = units.get(quantity_match.group(2))

    cadence = None
    cadence_match = re.search(r"\b(?:per\s+|/\s*)?(month|monthly|year|yearly|annual|annually|quarter|quarterly)\b", ql)
    if cadence_match:
        cadence = {
            "month": "monthly", "monthly": "monthly", "year": "annual",
            "yearly": "annual", "annual": "annual", "annually": "annual",
            "quarter": "quarterly", "quarterly": "quarterly",
        }[cadence_match.group(1)]

    unit_price = None
    recurring = None
    unit_price_match = re.search(
        r"(?:\b(?:aud|usd|cad|nzd|sgd|hkd|gbp|eur|jpy)\s*)?[\$€£]\s*(\d+(?:\.\d+)?)\s*"
        r"(?:/|per\s+)(?:seat|user|device|endpoint|licen[cs]e)(?:\s*(?:/|per\s+)(?:month|year|quarter))?",
        ql,
    )
    if unit_price_match:
        unit_price = float(unit_price_match.group(1))
        if cadence:
            recurring = unit_price

    term_months = None
    term = re.search(r"\b(\d{1,3})\s*(month|months|year|years)\b", ql)
    if term:
        term_months = int(term.group(1)) * (12 if term.group(2).startswith("year") else 1)

    scope = classify_budget_scope(q)
    if scope == "unknown" and parsed_budget and parsed_budget.mode == "per_unit":
        scope = "per_unit"

    return CommercialTerms(
        currency=currency,
        quantity=quantity,
        quantity_unit=quantity_unit,
        unit_price=unit_price,
        billing_cadence=cadence,
        contract_term_months=term_months,
        recurring_fees=recurring,
        budget_scope=scope,
        tco_horizon_months=term_months,
    )
