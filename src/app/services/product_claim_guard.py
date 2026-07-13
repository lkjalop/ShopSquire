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
# P1-3: shared injection markers (same source as the commerce guard + V2 gate) — no drift.
from src.app.security.injection_patterns import INJECTION_RE as _INJECTION_RE
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


_DOLLAR_AMOUNT_RE = re.compile(r"\$\s*(\d[\d,]*)")
_KEY_UNIT_RE = re.compile(r"(?:^|_)(gb|tb|hz|ghz|mhz|wh|inch(?:es)?)$")


def _amounts_in(text: str) -> set[int]:
    """$-prefixed amounts stated in platform-authored text, as a numeric set (audit 2026-07-08:
    substring matching let any digit-subsequence of a larger preamble number 'ground' an
    invented price). $-prefix required so '~7 days' never whitelists a $7 claim."""
    out: set[int] = set()
    for m in _DOLLAR_AMOUNT_RE.finditer(text or ""):
        try:
            out.add(int(m.group(1).replace(",", "")))
        except ValueError:
            continue
    return out


def _spec_unit_index(results: list[dict[str, Any]], preamble: str | None) -> set[tuple[float, str]]:
    """Every (value, unit) pair the evidence actually states — from number+unit adjacency in
    value strings ('512GB SSD' -> (512, gb)) and from unit-bearing keys ('ram_gb': 32 ->
    (32, gb)) — plus platform-authored preamble facts ('16GB GPU memory'). Numeric membership
    replaces all substring heuristics."""
    vocab = _load_store_vocab()
    pair_re = vocab["spec_unit_re"]
    pairs: set[tuple[float, str]] = set()

    def _add_text(s: str) -> None:
        for n, u in pair_re.findall(s or ""):
            try:
                pairs.add((float(n), str(u).lower()))
            except ValueError:
                continue

    for r in results or []:
        if not isinstance(r, dict):
            continue
        _add_text(str(r.get("name") or ""))
        specs = r.get("specs")
        if isinstance(specs, dict):
            for k, v in specs.items():
                _add_text(str(v))
                km = _KEY_UNIT_RE.search(str(k).lower())
                if km:
                    try:
                        unit = km.group(1)
                        pairs.add((float(v), "inch" if unit.startswith("inch") else unit))
                    except (TypeError, ValueError):
                        continue
        elif specs:
            _add_text(str(specs))
    _add_text(preamble or "")
    return pairs


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
    preamble: str | None = None,
) -> GuardResult:
    """Reject narration that asserts a product/price/spec not in the evidence,
    or that parrots a quarantined QR/URL/injection payload.

    budget_min/budget_max are in DOLLARS (matching the prose '$' amounts and the
    dollar-converted product prices), or None.

    ``preamble`` is the platform-authored narration context (step-up facts, capability
    registry, market evidence) and counts as legitimate evidence: the guard's job is to
    catch what the MODEL invented, not to punish it for citing facts the platform itself
    supplied. (Scope mismatch here was mute-layer 7 of the narration mute stack, bb4cd0a:
    results-only verification rejected every answer that honestly cited its own step-up
    facts — i.e. exactly the nuanced answers on hard queries.) The preamble is
    platform-assembled and image-payload-quarantined upstream, never raw user/image text.
    """
    violations: list[str] = []
    text = prose or ""
    low = text.lower()
    ev_text = _evidence_text(results)
    ev_brands = _evidence_brands(results)
    ev_prices = _evidence_prices(results)
    pre_low = (preamble or "").lower()
    pre_amounts = _amounts_in(preamble or "")

    # 1. Quarantined payload must never appear in narration (URLs / injection markers).
    for url in _URL_RE.findall(text):
        if url.lower() not in ev_text and url.lower() not in pre_low:
            violations.append(f"ungrounded_url:{url[:40]}")
    if _INJECTION_RE.search(text):
        violations.append("injection_marker")

    # 2. Invented product: a known brand named in prose but not in the evidence.
    _vocab = _load_store_vocab()
    for b in _vocab["brands"]:
        if (
            re.search(rf"\b{re.escape(b)}\b", low)
            and b not in ev_brands
            and not re.search(rf"\b{re.escape(b)}\b", pre_low)
        ):
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
        # allow if the platform's own preamble stated this amount (step-up price, capability
        # autonomy limit) — NUMERIC set membership, never substring (audit 2026-07-08: the
        # substring form let an invented $2,000 pass because "$20,000" was in the preamble)
        if val in pre_amounts:
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
    gpu_tokens = _vocab["gpu_re"].findall(text) if _has_spec_evidence else []
    # STRUCTURED spec comparison (audit 2026-07-08, replaces the squash/reversed/TB string
    # heuristics): the earlier substring matching leaked in both directions — evidence
    # "gpu_vram_gb 8" rejected honest "8GB" prose, then the squash fix let invented "12GB"
    # ground against "512GB SSD" and "gb10" against "gb1024". Specs are NUMBERS with UNITS:
    # index every (value, unit) pair the evidence states — from value strings ("512GB SSD")
    # AND from unit-bearing keys ("ram_gb": 32) — normalize tb→gb, and require exact numeric
    # membership. No substrings anywhere.
    ev_units = _spec_unit_index(results, preamble)
    _num_unit = re.compile(r"^(\d+(?:\.\d+)?)([a-z]+)$")
    for tok in spec_tokens:
        t = str(tok).lower()
        m2 = _num_unit.match(t)
        if not m2:
            continue
        try:
            num = float(m2.group(1))
        except ValueError:
            continue
        unit = m2.group(2)
        candidates = {(num, unit)}
        if unit == "tb":  # prose says TB, evidence may state GB
            candidates |= {(num * 1000, "gb"), (num * 1024, "gb")}
        if unit == "gb":  # prose says GB, evidence may state TB
            for div in (1000.0, 1024.0):
                candidates.add((num / div, "tb"))
        if not (candidates & ev_units):
            violations.append(f"ungrounded_spec:{t}")
    # GPU model tokens ("rtx 4070" / bare "4070"): word-boundary match on the RAW haystacks —
    # boundary-safe, and never against conversation text (preamble here is platform-authored
    # guard evidence only; see verify caller).
    for tok in gpu_tokens:
        t = str(tok).lower()
        if re.search(rf"\b{re.escape(t)}\b", ev_text):
            continue
        if pre_low and re.search(rf"\b{re.escape(t)}\b", pre_low):
            continue
        violations.append(f"ungrounded_spec:{t}")

    # 5. Unsupported performance claims: GPU/display specs do not prove game
    # FPS, ray-tracing, or settings-level benchmark claims. Those need explicit
    # benchmark/performance evidence in the product data (or platform-supplied
    # preamble evidence, e.g. the market-intelligence note).
    if (
        _PERFORMANCE_CLAIM_RE.search(text)
        and not _PERFORMANCE_EVIDENCE_RE.search(ev_text)
        and not (pre_low and _PERFORMANCE_EVIDENCE_RE.search(pre_low))
    ):
        violations.append("unsupported_performance_claim")

    return GuardResult(grounded=not violations, violations=violations)


def guard_enabled() -> bool:
    import os
    # Default ON (GPT-5.5 #1): rejecting an ungrounded LLM claim only makes output MORE conservative
    # (it falls back to deterministic grounded copy) — a truthfulness/safety improvement, not a risky
    # behavioural change. Set COMMERCE_NARRATION_GUARD=0 to disable.
    return str(os.getenv("COMMERCE_NARRATION_GUARD", "1")).strip().lower() in ("1", "true", "yes")
