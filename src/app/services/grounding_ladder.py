from __future__ import annotations

"""Grounding ladder — assert product identity only to the level the evidence supports.

The anti-hallucination primitive: *assert-to-evidence, escalate-the-residual.*

Given multi-source evidence about what product the shopper means (their typed
query, a CLIP catalog match, a vision-LLM guess, OCR/labels), we:

  1. resolve each identity field (brand / product_line / category / specs) by a
     reliability-weighted vote across sources;
  2. GATE each assertion against the catalog ("catalog disposes"): a brand the
     catalog can't confirm is dropped, not asserted;
  3. detect cross-source CONFLICT (two trustworthy sources disagree);
  4. settle on the most specific TIER that is both supported and grounded;
  5. turn the unresolved residual into a clarifying question (the bounded-autonomy
     boundary — ask the human only here).

`ground_identity()` is pure (takes already-extracted evidence dicts) so it is
fully unit-testable. `resolve_grounded_identity()` is the thin I/O orchestrator
that gathers evidence from the existing agents (product_identity_agent,
visual_search) and calls the pure core.

Tiers (most → least specific):
    0  brand + product_line + specs     "MSI Raider, RTX 4080"
    1  brand + product_line             "MSI Raider"
    2  brand + category                 "MSI gaming laptop"
    3  category                         "gaming laptop"
    4  query only                       (no product anchor)
"""

import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

# Reliability of each evidence source (how much we trust a field value from it).
RELIABILITY = {
    "user_text": 1.0,      # the shopper typed it — authoritative
    "visual_match": 0.85,  # CLIP nearest-neighbour against catalog images — robust + grounded
    "vision_vlm": 0.60,    # vision LLM guess — capable but hallucination-prone
    "text_ocr": 0.50,      # labels / OCR — useful but spoofable
}

_TIER_NAMES = {
    0: "brand_line_specs",
    1: "brand_line",
    2: "brand_category",
    3: "category",
    4: "query_only",
}

# Brand aliases → canonical brand (lowercase).
_BRAND_ALIASES = {
    "macbook": "apple", "imac": "apple", "iphone": "apple", "ipad": "apple",
    "thinkpad": "lenovo", "ideapad": "lenovo", "legion": "lenovo", "yoga": "lenovo",
    "xps": "dell", "inspiron": "dell", "alienware": "dell", "latitude": "dell",
    "rog": "asus", "tuf": "asus", "zenbook": "asus", "vivobook": "asus",
    "omen": "hp", "spectre": "hp", "envy": "hp", "pavilion": "hp",
    "predator": "acer", "nitro": "acer", "aspire": "acer", "swift": "acer",
    "raider": "msi", "stealth": "msi", "katana": "msi",
    "blade": "razer", "surface": "microsoft", "gram": "lg",
}

# Product-line keyword → (canonical brand, line label).
_PRODUCT_LINES = {
    "raider": ("msi", "Raider"), "stealth": ("msi", "Stealth"), "katana": ("msi", "Katana"),
    "legion": ("lenovo", "Legion"), "thinkpad": ("lenovo", "ThinkPad"), "yoga": ("lenovo", "Yoga"),
    "ideapad": ("lenovo", "IdeaPad"),
    "rog": ("asus", "ROG"), "tuf": ("asus", "TUF"), "zenbook": ("asus", "Zenbook"),
    "vivobook": ("asus", "Vivobook"),
    "xps": ("dell", "XPS"), "alienware": ("dell", "Alienware"), "inspiron": ("dell", "Inspiron"),
    "omen": ("hp", "Omen"), "spectre": ("hp", "Spectre"), "victus": ("hp", "Victus"),
    "pavilion": ("hp", "Pavilion"),
    "predator": ("acer", "Predator"), "nitro": ("acer", "Nitro"), "swift": ("acer", "Swift"),
    "macbook": ("apple", "MacBook"), "blade": ("razer", "Blade"),
    "surface": ("microsoft", "Surface"),
}

_KNOWN_BRANDS = {
    "apple", "dell", "hp", "lenovo", "asus", "acer", "microsoft", "samsung",
    "msi", "razer", "lg", "huawei", "google", "framework", "gigabyte",
}

_CATEGORY_KW = {
    "laptop": ["laptop", "notebook", "ultrabook", "macbook", "chromebook"],
    "desktop": ["desktop", "tower", "workstation", "imac", "mac mini"],
    "tablet": ["tablet", "ipad", "surface go"],
    "phone": ["phone", "smartphone", "iphone", "galaxy"],
    "monitor": ["monitor", "display screen", "gaming monitor"],
}

_GPU_RE = re.compile(r"\b(rtx|gtx|rx)\s*(\d{3,4})\b", re.IGNORECASE)
_RAM_RE = re.compile(r"\b(8|16|24|32|64)\s*gb\b", re.IGNORECASE)


def _norm_brand(value: Any) -> Optional[str]:
    s = str(value or "").strip().lower()
    if not s or s in ("unknown", "null", "none"):
        return None
    s = re.split(r"[\s\-]", s)[0] if s not in _KNOWN_BRANDS else s
    return _BRAND_ALIASES.get(s, s)


@dataclass
class GroundingResult:
    tier: int = 4
    tier_name: str = "query_only"
    brand: Optional[str] = None
    product_line: Optional[str] = None
    category: Optional[str] = None
    specs: Dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    confidence_label: str = "unverified"
    grounded: bool = False
    conflicts: List[Dict[str, Any]] = field(default_factory=list)
    residual_field: Optional[str] = None
    residual_question: Optional[Dict[str, Any]] = None
    evidence: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tier": self.tier,
            "tier_name": self.tier_name,
            "brand": self.brand,
            "product_line": self.product_line,
            "category": self.category,
            "specs": self.specs,
            "confidence": round(float(self.confidence), 3),
            "confidence_label": self.confidence_label,
            "grounded": self.grounded,
            "conflicts": self.conflicts,
            "residual_field": self.residual_field,
            "residual_question": self.residual_question,
            "evidence_sources": [e.get("source") for e in self.evidence],
        }


def _label(conf: float) -> str:
    if conf >= 0.8:
        return "confirmed"
    if conf >= 0.55:
        return "likely"
    if conf >= 0.3:
        return "possibly"
    return "unverified"


def _evidence_from_query(query: str) -> List[Dict[str, Any]]:
    q = str(query or "").lower()
    ev: List[Dict[str, Any]] = []
    # Product line (implies brand) — most specific.
    for kw, (brand, line) in _PRODUCT_LINES.items():
        if re.search(rf"\b{re.escape(kw)}\b", q):
            ev.append({"field": "product_line", "value": line, "source": "user_text", "confidence": 1.0})
            ev.append({"field": "brand", "value": brand, "source": "user_text", "confidence": 1.0})
            break
    # Brand (explicit)
    for b in _KNOWN_BRANDS:
        if re.search(rf"\b{re.escape(b)}\b", q):
            ev.append({"field": "brand", "value": b, "source": "user_text", "confidence": 1.0})
            break
    # Category
    for cat, kws in _CATEGORY_KW.items():
        if any(k in q for k in kws):
            ev.append({"field": "category", "value": cat, "source": "user_text", "confidence": 1.0})
            break
    # Specs
    specs: Dict[str, Any] = {}
    m = _GPU_RE.search(q)
    if m:
        specs["gpu_model"] = f"{m.group(1).upper()} {m.group(2)}"
    m = _RAM_RE.search(q)
    if m:
        specs["ram_gb_min"] = int(m.group(1))
    if specs:
        ev.append({"field": "specs", "value": specs, "source": "user_text", "confidence": 1.0})
    return ev


def _evidence_from_identity(identity: Optional[Dict[str, Any]], source: str) -> List[Dict[str, Any]]:
    if not isinstance(identity, dict) or not identity.get("identified"):
        return []
    conf = float(identity.get("confidence") or 0.0)
    ev: List[Dict[str, Any]] = []
    b = _norm_brand(identity.get("brand"))
    if b:
        ev.append({"field": "brand", "value": b, "source": source, "confidence": conf})
    model = str(identity.get("model") or "").strip()
    if model and model.lower() not in ("unknown", "null", "none"):
        ev.append({"field": "product_line", "value": model, "source": source, "confidence": conf})
    pt = str(identity.get("product_type") or "").strip().lower()
    if pt and pt not in ("unknown", "other", ""):
        ev.append({"field": "category", "value": pt, "source": source, "confidence": conf})
    specs: Dict[str, Any] = {}
    if identity.get("gpu_hint") and str(identity.get("gpu_hint")).lower() not in ("integrated", "null", "none", "unknown"):
        specs["gpu_model"] = identity["gpu_hint"]
    if identity.get("ram_gb_hint"):
        specs["ram_gb_min"] = identity["ram_gb_hint"]
    if specs:
        ev.append({"field": "specs", "value": specs, "source": source, "confidence": conf})
    return ev


def _evidence_from_visual(matches: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    if not matches:
        return []
    top = matches[0]
    score = float(top.get("visual_score") or 0.0)
    if score < 0.20:  # too weak to count as grounding
        return []
    ev: List[Dict[str, Any]] = []
    b = _norm_brand(top.get("brand"))
    if b:
        ev.append({"field": "brand", "value": b, "source": "visual_match", "confidence": score})
    name = str(top.get("name") or "").lower()
    for kw, (brand, line) in _PRODUCT_LINES.items():
        if kw in name:
            ev.append({"field": "product_line", "value": line, "source": "visual_match", "confidence": score})
            break
    return ev


def _resolve_field(
    evidence: List[Dict[str, Any]],
    fieldname: str,
    reliability: Optional[Dict[str, float]] = None,
) -> Tuple[Optional[Any], List[Dict[str, Any]]]:
    """Return (winning_value, conflict_list) for a field via reliability-weighted
    vote. `reliability` maps source→trust (defaults to the product-domain map);
    other domains (claims, supplier) pass their own — this is what makes the
    weighted-vote + conflict primitive reusable across surfaces."""
    reliability = reliability or RELIABILITY
    votes: Dict[str, float] = {}
    value_by_key: Dict[str, Any] = {}
    sources_by_key: Dict[str, set] = {}
    for e in evidence:
        if e.get("field") != fieldname:
            continue
        val = e.get("value")
        key = str(val).strip().lower() if not isinstance(val, dict) else "__specs__"
        w = reliability.get(e.get("source", ""), 0.4) * float(e.get("confidence") or 0.0)
        votes[key] = votes.get(key, 0.0) + w
        value_by_key[key] = val
        sources_by_key.setdefault(key, set()).add(e.get("source"))
    if not votes:
        return None, []
    ranked = sorted(votes.items(), key=lambda kv: -kv[1])
    top_key, top_w = ranked[0]
    conflicts: List[Dict[str, Any]] = []
    if len(ranked) >= 2:
        second_key, second_w = ranked[1]
        # Conflict: a different value with comparable, trustworthy support.
        # (relative: near the leader; absolute: from a source we'd actually trust)
        if second_key != top_key and second_w >= 0.7 * top_w and second_w >= 0.30:
            conflicts.append({
                "field": fieldname,
                "candidates": [value_by_key[top_key], value_by_key[second_key]],
            })
    return value_by_key[top_key], conflicts


def ground_identity(
    query: str,
    *,
    text_identity: Optional[Dict[str, Any]] = None,
    vision_identity: Optional[Dict[str, Any]] = None,
    visual_matches: Optional[List[Dict[str, Any]]] = None,
    catalog_brands: Optional[set] = None,
) -> GroundingResult:
    """Pure grounding core. Combines evidence → grounded, tiered identity + residual."""
    evidence: List[Dict[str, Any]] = []
    evidence += _evidence_from_query(query)
    evidence += _evidence_from_identity(vision_identity, "vision_vlm")
    evidence += _evidence_from_identity(text_identity, "text_ocr")
    evidence += _evidence_from_visual(visual_matches)

    if not evidence:
        return GroundingResult(evidence=[])

    brand, brand_conflicts = _resolve_field(evidence, "brand")
    line, line_conflicts = _resolve_field(evidence, "product_line")
    category, _ = _resolve_field(evidence, "category")
    specs_val, _ = _resolve_field(evidence, "specs")
    specs = specs_val if isinstance(specs_val, dict) else {}
    conflicts = brand_conflicts + line_conflicts

    # ── Grounding gate: can the catalog confirm the brand? ──
    brand_sources = {e["source"] for e in evidence if e.get("field") == "brand" and str(e.get("value")).strip().lower() == str(brand or "").strip().lower()}
    brand_from_user = "user_text" in brand_sources
    brand_in_visual = "visual_match" in brand_sources
    brand_in_catalog = bool(catalog_brands) and (str(brand or "").strip().lower() in {str(b).strip().lower() for b in (catalog_brands or set())})
    # Grounding gate. We only DROP a brand when we have POSITIVE catalog knowledge
    # that excludes it — that's where the anti-hallucination value lives. When the
    # catalog set is unknown/unavailable (e.g. query failed, blind context) we can't
    # disprove the brand, so we trust the evidence rather than dropping (fail-open).
    catalog_known = bool(catalog_brands)
    if catalog_known:
        # Strict: a VLM/OCR-only guess for a brand the catalog can't carry is dropped.
        brand_grounded = bool(brand) and (brand_from_user or brand_in_visual or brand_in_catalog)
    else:
        brand_grounded = bool(brand)

    # If brand is in conflict between two non-authoritative sources, it's not grounded.
    brand_conflicted = any(c["field"] == "brand" for c in conflicts) and not brand_from_user

    # ── Settle the tier ──
    asserted_brand = brand if (brand_grounded and not brand_conflicted) else None
    asserted_line = line if (asserted_brand and line) else None
    if asserted_brand and asserted_line and specs:
        tier = 0
    elif asserted_brand and asserted_line:
        tier = 1
    elif asserted_brand and category:
        tier = 2
    elif category:
        tier = 3
    else:
        tier = 4

    # ── Confidence from tier + evidence strength ──
    base_conf = {0: 0.92, 1: 0.85, 2: 0.72, 3: 0.55, 4: 0.25}[tier]
    if brand_from_user or category in {e.get("value") for e in evidence if e.get("source") == "user_text"}:
        base_conf = min(1.0, base_conf + 0.05)
    if brand_in_visual:
        base_conf = min(1.0, base_conf + 0.05)
    confidence = round(base_conf, 3)

    # ── Residual → clarifying question (the autonomy boundary) ──
    residual_field: Optional[str] = None
    residual_question: Optional[Dict[str, Any]] = None
    if brand_conflicted:
        cand = next((c["candidates"] for c in conflicts if c["field"] == "brand"), [])
        names = [str(x).title() for x in cand[:2]]
        residual_field = "brand"
        residual_question = {
            "id": "clarify_brand_conflict",
            "text": f"I can see a {category or 'device'} but couldn't confirm the brand — is it {' or '.join(names)}?",
            "goal": "clarify_product_identity",
            "options": [{"label": n, "value": n.lower()} for n in names],
        }
    elif brand and not brand_grounded:
        # We had a brand guess we couldn't ground → ask to confirm rather than assert.
        residual_field = "brand"
        residual_question = {
            "id": "confirm_brand_guess",
            "text": f"Is this a {str(brand).title()}? I could see a {category or 'device'} but wasn't fully sure of the brand.",
            "goal": "clarify_product_identity",
            "options": [
                {"label": f"Yes, {str(brand).title()}", "value": str(brand).lower()},
                {"label": "No / not sure", "value": "unknown"},
            ],
        }
    elif tier >= 3 and visual_matches is not None:
        # We can see a category but no model — ask for the model (image present).
        residual_field = "product_line"
        residual_question = {
            "id": "ask_image_model",
            "text": f"I can see a {category or 'device'} but couldn't identify the exact model — what model is it (or the spec you care about)?",
            "goal": "clarify_product_identity",
        }

    return GroundingResult(
        tier=tier,
        tier_name=_TIER_NAMES[tier],
        brand=asserted_brand,
        product_line=asserted_line,
        category=category,
        specs=specs if tier == 0 else {},
        confidence=confidence,
        confidence_label=_label(confidence),
        grounded=bool(asserted_brand) or tier == 3,
        conflicts=conflicts,
        residual_field=residual_field,
        residual_question=residual_question,
        evidence=evidence,
    )


# ---------------------------------------------------------------------------
# I/O orchestrator — gathers evidence from the existing agents, then grounds.
# ---------------------------------------------------------------------------
def resolve_grounded_identity(
    query: str,
    *,
    text_identity: Optional[Dict[str, Any]] = None,
    vision_identity: Optional[Dict[str, Any]] = None,
    image_bytes: Optional[bytes] = None,
    catalog_brands: Optional[set] = None,
    budget_max: Optional[float] = None,
    enable_visual_search: Optional[bool] = None,
) -> GroundingResult:
    """Gather visual-match evidence (best-effort) and ground the identity.

    `text_identity` / `vision_identity` are the dicts already produced by
    product_identity_agent in the recommend flow — passed in to avoid recomputing.
    """
    visual_matches: Optional[List[Dict[str, Any]]] = None
    _vs_on = enable_visual_search
    if _vs_on is None:
        _vs_on = str(os.getenv("GROUNDING_VISUAL_SEARCH", "1")).strip().lower() in ("1", "true", "yes")
    if image_bytes and _vs_on:
        try:
            from src.app.services import visual_search
            if visual_search.is_available():
                visual_matches = visual_search.search(image_bytes=image_bytes, k=5, budget_max=budget_max)
        except Exception:
            visual_matches = None
    return ground_identity(
        query,
        text_identity=text_identity,
        vision_identity=vision_identity,
        visual_matches=visual_matches,
        catalog_brands=catalog_brands,
    )


# ---------------------------------------------------------------------------
# Cached catalog-brand set — the "what can we actually fulfil?" grounding source.
# ---------------------------------------------------------------------------
import time as _time

_CATALOG_BRANDS_CACHE: Dict[str, Any] = {"brands": None, "ts": 0.0, "stamp": None}


def reset_catalog_brands_cache() -> None:
    """Invalidate the catalog-brands cache. Call on catalog mutation (and in tests that
    insert products) so a newly-added product/brand is grounded immediately rather than
    after the TTL — a stale set silently drops over-budget image brands to generic."""
    _CATALOG_BRANDS_CACHE.update({"brands": None, "ts": 0.0, "stamp": None})


def _catalog_stamp(db: Any = None) -> Any:
    """Cheap catalog-change stamp (row count). When it differs from the cached stamp the
    brand set is stale and must be rebuilt — so new products appear at once, not after TTL.
    Returns None on failure (caller then falls back to TTL-only freshness)."""
    from sqlalchemy import text as _sql

    def _run(_db):
        return _db.execute(_sql("SELECT COUNT(*) FROM products")).scalar()

    try:
        if db is not None:
            return _run(db)
        from src.app.models.db import db_session
        with db_session() as _db:
            return _run(_db)
    except Exception:
        return None


def get_catalog_brands(db: Any = None, ttl_seconds: int = 300) -> Optional[set]:
    """Distinct lowercase brands present in the catalog (cached). None on failure
    (callers then fall back to user-text / visual-match grounding only).

    Pass the request's db session when available so we read the SAME engine the
    request uses (avoids cross-engine/empty reads in tests and multi-DB setups)."""
    now = _time.time()
    stamp = _catalog_stamp(db)
    cached = _CATALOG_BRANDS_CACHE.get("brands")
    if (
        cached
        and (now - float(_CATALOG_BRANDS_CACHE.get("ts") or 0.0)) < ttl_seconds
        and (stamp is None or stamp == _CATALOG_BRANDS_CACHE.get("stamp"))
    ):
        return cached
    def _run(_db) -> list:
        from sqlalchemy import text as _sql
        # `name` is universal; the `brand` column may not exist in every schema.
        try:
            return _db.execute(_sql("SELECT name, brand FROM products")).fetchall()
        except Exception:
            return _db.execute(_sql("SELECT name FROM products")).fetchall()

    try:
        if db is not None:
            rows = _run(db)
        else:
            from src.app.models.db import db_session
            with db_session() as _db:
                rows = _run(_db)
        brands: set = set()
        for r in rows or []:
            nm = str(r[0] or "").lower() if r is not None and len(r) > 0 else ""
            # Explicit brand column when present.
            if r is not None and len(r) > 1:
                b = _norm_brand(r[1])
                if b:
                    brands.add(b)
            # Derive brand from the product name (handles "MSI Thin A15" catalogs).
            if nm:
                for kb in _KNOWN_BRANDS:
                    if re.search(rf"\b{re.escape(kb)}\b", nm):
                        brands.add(kb)
                        break
                for kw, (brand, _line) in _PRODUCT_LINES.items():
                    if re.search(rf"\b{re.escape(kw)}\b", nm):
                        brands.add(brand)
                        break
        if brands:
            _CATALOG_BRANDS_CACHE["brands"] = brands
            _CATALOG_BRANDS_CACHE["ts"] = now
            _CATALOG_BRANDS_CACHE["stamp"] = stamp
        return brands
    except Exception:
        return cached  # stale set, or None if never populated
