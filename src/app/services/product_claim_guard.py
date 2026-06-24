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

# ── Store vocabulary (FLAVOUR, not core) ──────────────────────────────────────
# The grounding MECHANISM (reject invented product/price/spec) is product-agnostic.
# WHICH brands/specs exist is store-specific -> loaded from the StoreProfile
# (config/store_profiles/<id>.json: known_brands/spec_units/gpu_prefixes). Defaults below
# are catastrophic insurance (laptop demo) used only if the profile is unreadable.
_DEFAULT_BRANDS = {
    "msi", "asus", "lenovo", "dell", "hp", "acer", "razer", "apple", "macbook",
    "gigabyte", "alienware", "samsung", "microsoft", "surface", "lg", "sony",
    "intel", "amd", "nvidia",
}
_DEFAULT_SPEC_UNITS = ["gb", "tb", "hz", "ghz"]
_DEFAULT_GPU_PREFIXES = ["rtx", "gtx", "rx"]

_VOCAB_CACHE: dict | None = None


def _load_store_vocab() -> dict:
    """Load store vocabulary (cached) from the StoreProfile (SSOT). Falls back to the
    laptop defaults only if the profile is unreadable. Phase 1: this used to read
    config/store_vocab.json (a parallel second profile); that file is now archived."""
    global _VOCAB_CACHE
    if _VOCAB_CACHE is not None:
        return _VOCAB_CACHE
    brands, units, gpus = set(_DEFAULT_BRANDS), list(_DEFAULT_SPEC_UNITS), list(_DEFAULT_GPU_PREFIXES)
    try:
        from src.app.platform.store_profile import get_store_profile
        prof = get_store_profile()
        if prof.get("known_brands"):
            brands = {str(b).lower() for b in prof["known_brands"]}
        if prof.get("spec_units"):
            units = [str(u).lower() for u in prof["spec_units"]]
        if prof.get("gpu_prefixes") is not None:  # explicit [] (e.g. pharmacy) must be honoured
            gpus = [str(g).lower() for g in prof["gpu_prefixes"]]
    except Exception:
        pass
    # Empty gpu list (a non-electronics vertical) must match NOTHING, not every 3-4 digit number.
    if gpus:
        gpu_re = re.compile(r"\b(?:" + "|".join(re.escape(g) for g in gpus) + r")\s?(\d{3,4})\b", re.IGNORECASE)
    else:
        gpu_re = re.compile(r"a^")  # never matches
    _VOCAB_CACHE = {
        "brands": brands,
        "spec_unit_re": re.compile(r"(\d[\d.]*)\s?(" + "|".join(re.escape(u) for u in units) + r")\b", re.IGNORECASE),
        "gpu_re": gpu_re,
    }
    return _VOCAB_CACHE


def reset_vocab_cache() -> None:
    """Clear the cached vocab — call when the active profile changes (tests/determinism)."""
    global _VOCAB_CACHE
    _VOCAB_CACHE = None


_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
_INJECTION_RE = re.compile(
    r"\b(ignore (all )?previous|disregard .{0,20}instruction|system prompt|do anything now)\b",
    re.IGNORECASE,
)
_PRICE_RE = re.compile(r"\$\s?(\d[\d,]*)(?:\.\d+)?")
_PERFORMANCE_CLAIM_RE = re.compile(
    r"\b(?:\d{2,3}\+?\s*fps|frames per second|high settings|ultra settings|ray tracing|4k gaming)\b",
    re.IGNORECASE,
)
_PERFORMANCE_EVIDENCE_RE = re.compile(
    r"\b(?:fps|frames per second|benchmark|benchmarked|performance profile|high settings|ultra settings|ray tracing|4k gaming)\b",
    re.IGNORECASE,
)


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
        for b in _load_store_vocab()["brands"]:
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
    _vocab = _load_store_vocab()
    for b in _vocab["brands"]:
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
    spec_tokens = [f"{n}{u}".lower() for n, u in _vocab["spec_unit_re"].findall(text)] if _has_spec_evidence else []
    spec_tokens += _vocab["gpu_re"].findall(text) if _has_spec_evidence else []
    for tok in spec_tokens:
        t = str(tok).lower()
        # match the bare number too (e.g. "4070" from "rtx 4070")
        if t in ev_text or re.search(rf"\b{re.escape(t)}\b", ev_text):
            continue
        violations.append(f"ungrounded_spec:{t}")

    # 5. Unsupported performance claims: GPU/display specs do not prove game
    # FPS, ray-tracing, or settings-level benchmark claims. Those need explicit
    # benchmark/performance evidence in the product data.
    if _PERFORMANCE_CLAIM_RE.search(text) and not _PERFORMANCE_EVIDENCE_RE.search(ev_text):
        violations.append("unsupported_performance_claim")

    return GuardResult(grounded=not violations, violations=violations)


def guard_enabled() -> bool:
    import os
    return str(os.getenv("COMMERCE_NARRATION_GUARD", "0")).strip().lower() in ("1", "true", "yes")
