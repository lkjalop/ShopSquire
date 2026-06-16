"""Product claim guard (0.4) — grounded-narration check for the LLM summary.

Port of GridVerdict's narrator grounding guard (cite-or-suppress), adapted from
numbers to PRODUCT claims. The LLM summary is a NARRATOR over assembled evidence,
not a source of truth: it may rephrase, but every product/brand/price/spec it
asserts must trace to the `results` it was given. If it invents one — a product
not in results, a price no product has, a spec no product has, or it parrots a
quarantined QR/URL/injection payload — the narration is REJECTED and the caller
falls back to deterministic prose.

Pure + deterministic (no I/O, no LLM). Enabled at the call site behind the
COMMERCE_NARRATION_GUARD flag; the deterministic fallback is always the floor.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# Brands we can recognise by name — if the prose names one of these and it is NOT
# in the evidence brands, that is an invented product.
_KNOWN_BRANDS = {
    "msi", "asus", "lenovo", "dell", "hp", "acer", "razer", "apple", "macbook",
    "gigabyte", "alienware", "samsung", "microsoft", "surface", "lg", "sony",
    "intel", "amd", "nvidia",
}

_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
_INJECTION_RE = re.compile(
    r"\b(ignore (all )?previous|disregard .{0,20}instruction|system prompt|do anything now)\b",
    re.IGNORECASE,
)
_PRICE_RE = re.compile(r"\$\s?(\d[\d,]*)(?:\.\d+)?")
# spec tokens: "16gb", "240hz", "1tb", "3.5ghz", GPU models "rtx 4070" / "4070"
_SPEC_UNIT_RE = re.compile(r"(\d[\d.]*)\s?(gb|tb|hz|ghz)\b", re.IGNORECASE)
_GPU_RE = re.compile(r"\b(?:rtx|gtx|rx)\s?(\d{3,4})\b", re.IGNORECASE)


@dataclass
class GuardResult:
    grounded: bool
    violations: list[str] = field(default_factory=list)

    @property
    def reason(self) -> str:
        return ";".join(self.violations[:4])


def _evidence_text(results: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for r in results or []:
        if not isinstance(r, dict):
            continue
        parts.append(str(r.get("name") or ""))
        parts.append(str(r.get("brand") or ""))
        specs = r.get("specs")
        if isinstance(specs, dict):
            parts.append(" ".join(f"{k} {v}" for k, v in specs.items()))
        elif specs:
            parts.append(str(specs))
    return " ".join(parts).lower()


def _evidence_brands(results: list[dict[str, Any]]) -> set[str]:
    out: set[str] = set()
    for r in results or []:
        if not isinstance(r, dict):
            continue
        blob = f"{r.get('brand') or ''} {r.get('name') or ''}".lower()
        for b in _KNOWN_BRANDS:
            if re.search(rf"\b{re.escape(b)}\b", blob):
                out.add(b)
    return out


def _evidence_prices(results: list[dict[str, Any]]) -> set[int]:
    out: set[int] = set()
    for r in results or []:
        if not isinstance(r, dict):
            continue
        try:
            cents = int(r.get("price_cents") or 0)
            if cents > 0:
                out.add(round(cents / 100))
        except Exception:
            continue
    return out


def verify_product_narration(
    prose: str,
    results: list[dict[str, Any]],
    *,
    budget_min: int | None = None,
    budget_max: int | None = None,
) -> GuardResult:
    """Reject narration that asserts a product/price/spec not in the evidence,
    or that parrots a quarantined QR/URL/injection payload.

    budget_min/budget_max are in DOLLARS (matching the prose '$' amounts and the
    dollar-converted product prices), or None.
    """
    violations: list[str] = []
    text = prose or ""
    low = text.lower()
    ev_text = _evidence_text(results)
    ev_brands = _evidence_brands(results)
    ev_prices = _evidence_prices(results)

    # 1. Quarantined payload must never appear in narration (URLs / injection markers).
    for url in _URL_RE.findall(text):
        if url.lower() not in ev_text:
            violations.append(f"ungrounded_url:{url[:40]}")
    if _INJECTION_RE.search(text):
        violations.append("injection_marker")

    # 2. Invented product: a known brand named in prose but not in the evidence.
    for b in _KNOWN_BRANDS:
        if re.search(rf"\b{re.escape(b)}\b", low) and b not in ev_brands:
            violations.append(f"ungrounded_product:{b}")

    # 3. Invented price: a $ amount that is neither a product price nor in budget.
    lo = budget_min if budget_min else None   # dollars
    hi = budget_max if budget_max else None
    for m in _PRICE_RE.findall(text):
        try:
            val = int(m.replace(",", ""))
        except ValueError:
            continue
        if val in ev_prices:
            continue
        # allow if inside the stated budget band (a paraphrase of the budget)
        if lo is not None and hi is not None and lo <= val <= hi:
            continue
        if hi is not None and lo is None and val <= hi:
            continue
        violations.append(f"ungrounded_price:{val}")

    # 4. Invented spec: a spec/GPU token not present in any product's evidence.
    # Only enforce when the evidence ACTUALLY carries specs — if no result has a
    # specs payload there is nothing to verify against, and flagging every spec
    # mention would be a false positive (and would wrongly reject good narration).
    _has_spec_evidence = any(
        isinstance(r, dict) and isinstance(r.get("specs"), dict) and r.get("specs")
        for r in (results or [])
    )
    spec_tokens = [f"{n}{u}".lower() for n, u in _SPEC_UNIT_RE.findall(text)] if _has_spec_evidence else []
    spec_tokens += _GPU_RE.findall(text) if _has_spec_evidence else []
    for tok in spec_tokens:
        t = str(tok).lower()
        # match the bare number too (e.g. "4070" from "rtx 4070")
        if t in ev_text or re.search(rf"\b{re.escape(t)}\b", ev_text):
            continue
        violations.append(f"ungrounded_spec:{t}")

    return GuardResult(grounded=not violations, violations=violations)


def guard_enabled() -> bool:
    import os
    return str(os.getenv("COMMERCE_NARRATION_GUARD", "0")).strip().lower() in ("1", "true", "yes")
