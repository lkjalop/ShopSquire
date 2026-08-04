"""Entity resolution (agnostic CORE) — the hippograph's canonicalization primitive.

Canonicalizes raw entity references (brand / product / user strings) into STABLE entity ids so the
decision-trace + conversion graph can *compound*: "Dell" / "DELL" / "dell-corp" collapse to one
brand node, a SKU is its own product node, a uid_hash is one user node. Without this the latent
graph has duplicate nodes and can't accumulate signal.

VERTICAL-BLIND mechanism (normalize + alias-map lookup + confidence); the alias DATA lives in the
StoreProfile (e.g. electronics.json `manufacturers`/aliases), never here. PII-safe: users are
referenced by hash only — raw identifiers are never stored on the EntityRef.

The pure resolvers take injected alias/catalog data (fully unit-testable, no app deps); the
``*_for_profile`` wrappers read the active StoreProfile. Nothing here writes or executes — it only
produces canonical ids that the graph-projection read-API will dedupe nodes on.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional

KIND_BRAND = "brand"
KIND_PRODUCT = "product"
KIND_USER = "user"

_WS = re.compile(r"\s+")
_PUNCT = re.compile(r"[^\w\s-]")


@dataclass(frozen=True)
class EntityRef:
    kind: str          # brand | product | user
    id: str            # canonical, stable id (the graph node key)
    label: str         # human-readable label
    confidence: float  # 0..1
    raw: str           # original reference ("<pii-redacted>" for raw users)


def normalize_label(s: Any) -> str:
    s = str(s or "").strip().lower()
    s = _PUNCT.sub("", s)
    s = _WS.sub(" ", s).strip()
    return s


def _slug(s: str) -> str:
    return normalize_label(s).replace(" ", "_")


def resolve_brand(raw: Any, *, alias_map: Optional[Dict[str, str]] = None,
                  known: Optional[Iterable[str]] = None) -> Optional[EntityRef]:
    """Canonicalize a brand string. ``alias_map``: {alias: canonical}; ``known``: canonical ids.
    Exact canonical → 1.0; full-string alias → 0.95; token-level alias/known → 0.7; normalized-only → 0.6.
    """
    norm = normalize_label(raw)
    if not norm:
        return None
    known_set = {normalize_label(k) for k in (known or [])}
    amap = {normalize_label(k): str(v) for k, v in (alias_map or {}).items()}
    if norm in known_set:
        return EntityRef(KIND_BRAND, _slug(norm), str(raw).strip(), 1.0, str(raw))
    if norm in amap:
        canon = amap[norm]
        return EntityRef(KIND_BRAND, _slug(canon), canon, 0.95, str(raw))
    for tok in norm.split():
        if tok in known_set:
            return EntityRef(KIND_BRAND, _slug(tok), tok, 0.7, str(raw))
        if tok in amap:
            canon = amap[tok]
            return EntityRef(KIND_BRAND, _slug(canon), canon, 0.7, str(raw))
    return EntityRef(KIND_BRAND, _slug(norm), str(raw).strip(), 0.6, str(raw))


def resolve_product(raw: Any, *, sku_pattern: Optional[str] = None,
                    catalog_skus: Optional[Iterable[str]] = None) -> Optional[EntityRef]:
    """A SKU is canonical as-is (1.0 if in catalog, 0.9 if it matches the SKU pattern); otherwise a
    normalized name node (0.5) prefixed ``name:`` so it never collides with a real SKU id."""
    s = str(raw or "").strip()
    if not s:
        return None
    if catalog_skus and s in set(catalog_skus):
        return EntityRef(KIND_PRODUCT, s, s, 1.0, s)
    if sku_pattern and re.fullmatch(sku_pattern, s):
        return EntityRef(KIND_PRODUCT, s, s, 0.9, s)
    return EntityRef(KIND_PRODUCT, "name:" + _slug(s), s, 0.5, s)


def resolve_user(raw: Any, *, already_hashed: bool = False, salt: str = "") -> Optional[EntityRef]:
    """Canonical user id = a hash, never raw PII. ``already_hashed`` uses the value as-is (e.g. an
    incoming uid_hash); otherwise SHA-256(salt+raw) truncated. ``raw`` is redacted on the ref."""
    s = str(raw or "").strip()
    if not s:
        return None
    if already_hashed:
        return EntityRef(KIND_USER, s, "user:" + s[:8], 1.0, "<hashed>")
    h = hashlib.sha256((str(salt) + s).encode("utf-8")).hexdigest()[:32]
    return EntityRef(KIND_USER, h, "user:" + h[:8], 1.0, "<pii-redacted>")


def canonical_entity(kind: str, raw: Any, **kw: Any) -> Optional[EntityRef]:
    """Generic dispatcher used by the graph projection to canonicalize trace nodes."""
    if kind == KIND_BRAND:
        return resolve_brand(raw, alias_map=kw.get("alias_map"), known=kw.get("known"))
    if kind == KIND_PRODUCT:
        return resolve_product(raw, sku_pattern=kw.get("sku_pattern"), catalog_skus=kw.get("catalog_skus"))
    if kind == KIND_USER:
        return resolve_user(raw, already_hashed=bool(kw.get("already_hashed", False)), salt=str(kw.get("salt", "")))
    return None


# ── Profile-backed convenience (reads the active StoreProfile; never raises) ──────────────────────
def _brand_alias_map_for_profile(profile_id: Optional[str] = None) -> tuple[Dict[str, str], List[str]]:
    """Build {alias: canonical}, [canonical...] from the profile's manufacturers/aliases.
    brand_label_patterns() returns {canonical: [lines + aliases]} — invert it."""
    try:
        from src.app.platform.store_profile import brand_label_patterns
        patterns = brand_label_patterns(profile_id) or {}
    except Exception:
        return {}, []
    alias_map: Dict[str, str] = {}
    known: List[str] = []
    for canon, aliases in patterns.items():
        known.append(str(canon))
        for a in (aliases or []):
            alias_map[str(a)] = str(canon)
    return alias_map, known


def resolve_brand_for_profile(raw: Any, *, profile_id: Optional[str] = None) -> Optional[EntityRef]:
    alias_map, known = _brand_alias_map_for_profile(profile_id)
    return resolve_brand(raw, alias_map=alias_map, known=known)
