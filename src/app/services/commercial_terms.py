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
_UNITS = {
    "seat": "seat", "seats": "seat", "user": "user", "users": "user",
    "device": "device", "devices": "device", "endpoint": "endpoint",
    "endpoints": "endpoint", "licence": "licence", "licences": "licence",
    "license": "licence", "licenses": "licence",
    # Physical order units belong in the same literal commercial contract as
    # seats/endpoints.  Keeping them here means a model outage cannot erase a
    # buyer-authored bulk count before affordability and fulfilment arithmetic.
    "laptop": "laptop", "laptops": "laptop",
    "notebook": "notebook", "notebooks": "notebook",
    "workstation": "workstation", "workstations": "workstation",
    "desktop": "desktop", "desktops": "desktop",
    "computer": "computer", "computers": "computer",
    "server": "server", "servers": "server",
    "tablet": "tablet", "tablets": "tablet",
    "phone": "phone", "phones": "phone",
    "unit": "unit", "units": "unit",
}

_QUANTITY_UNITS = (
    r"seats?|users?|devices?|endpoints?|licen[cs]es?|laptops?|notebooks?|"
    r"workstations?|desktops?|computers?|servers?|tablets?|phones?|units?"
)


def parse_commercial_terms(text: str, *, default_currency: str = "USD") -> CommercialTerms:
    q = str(text or "")
    ql = q.lower()
    currency_match = re.search(r"\b(aud|usd|cad|nzd|sgd|hkd|gbp|eur|jpy)\b", ql)
    currency = _CURRENCY.get(currency_match.group(1), str(default_currency or "USD").upper()) if currency_match else str(default_currency or "USD").upper()

    quantity = None
    quantity_unit = None
    quantity_match = re.search(
        r"\b(\d[\d,]{0,8})\s+(?:[a-z][a-z0-9+.-]*\s+){0,3}"
        rf"({_QUANTITY_UNITS})\b", ql,
    )
    if quantity_match:
        quantity = int(quantity_match.group(1).replace(",", ""))
        quantity_unit = _UNITS.get(quantity_match.group(2))

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

    parsed_budget = parse_budget(q)
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
