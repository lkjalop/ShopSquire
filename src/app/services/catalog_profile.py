from __future__ import annotations

from collections import Counter
import json
import time
from typing import Any, Dict

from sqlalchemy import text

from src.app.services.category_router import category_from_image_labels, detect_category
from src.app.services.product_taxonomy import infer_product_family


_FAMILY_TO_CATEGORY = {
    "LAP": "laptop",
    "MON": "monitor",
    "PERIPH": "accessory",
    "HEAD": "accessory",
    "ACC": "accessory",
    "COOL": "accessory",
    "BAG": "accessory",
}

_SUPPORTED_COMMERCE_CATEGORIES = {"laptop", "desktop", "phone", "tablet", "monitor", "tv", "accessory"}

_CATALOG_PROFILE_CACHE: Dict[str, Dict[str, Any]] = {}
_CATALOG_PROFILE_TTL_SEC = 300


def _catalog_profile_signature(db) -> Dict[str, Any]:
    try:
        row = db.execute(
            text(
                """
                SELECT COUNT(*) AS product_count, MAX(COALESCE(updated_at, '')) AS max_updated_at
                FROM products
                WHERE COALESCE(active, 1) = 1
                """
            )
        ).fetchone()
    except Exception:
        row = None
    if row is None:
        return {"product_count": 0, "max_updated_at": None}
    if hasattr(row, "_mapping"):
        return {
            "product_count": int(row._mapping.get("product_count") or 0),
            "max_updated_at": row._mapping.get("max_updated_at"),
        }
    return {
        "product_count": int((row[0] if len(row) > 0 else 0) or 0),
        "max_updated_at": row[1] if len(row) > 1 else None,
    }


def _infer_catalog_category(name: str, specs: Dict[str, Any]) -> str:
    text_blob = " ".join(
        [
            str(name or ""),
            str(specs.get("category") or ""),
            " ".join(str(x) for x in (specs.get("tags") or []) if x is not None),
        ]
    ).strip()
    cat = detect_category(query=text_blob, image_labels=[str(specs.get("category") or "")], constraints=specs)
    if cat and cat != "general":
        return cat
    family = infer_product_family(name=name, specs=specs)
    return _FAMILY_TO_CATEGORY.get(family, "general")


def build_catalog_profile(db) -> Dict[str, Any]:
    try:
        rows = db.execute(
            text(
                """
                SELECT name, specs
                FROM products
                WHERE COALESCE(active, 1) = 1
                """
            )
        ).fetchall()
    except Exception:
        rows = []

    counts: Counter[str] = Counter()
    total = 0
    for row in rows or []:
        if isinstance(row, (tuple, list)):
            name = row[0]
            raw_specs = row[1]
        elif hasattr(row, "_mapping"):
            name = row._mapping.get("name")
            raw_specs = row._mapping.get("specs")
        else:
            name = ""
            raw_specs = {}
        if isinstance(raw_specs, str) and raw_specs.strip():
            try:
                specs = json.loads(raw_specs)
            except Exception:
                specs = {}
        else:
            specs = raw_specs if isinstance(raw_specs, dict) else {}
        category = _infer_catalog_category(str(name or ""), specs)
        counts[category] += 1
        total += 1

    if not total:
        return {
            "primary_category": "general",
            "dominant_categories": [],
            "is_mixed_catalog": True,
            "category_counts": {},
            "total_products": 0,
        }

    dominant = [cat for cat, n in counts.most_common(3) if n > 0]
    primary = dominant[0] if dominant else "general"
    primary_share = (counts[primary] / float(total)) if primary in counts else 0.0
    is_mixed = primary_share < 0.65
    return {
        "primary_category": primary,
        "dominant_categories": dominant,
        "is_mixed_catalog": is_mixed,
        "category_counts": dict(counts),
        "total_products": total,
    }


def get_cached_catalog_profile(db, *, tenant_id: str | None = None, cache_ttl_sec: int = _CATALOG_PROFILE_TTL_SEC) -> Dict[str, Any]:
    key = str(tenant_id or "default").strip().lower() or "default"
    now = time.time()
    cached = _CATALOG_PROFILE_CACHE.get(key)
    current_sig = _catalog_profile_signature(db)
    if (
        cached
        and float(cached.get("expires_at") or 0.0) > now
        and dict(cached.get("signature") or {}) == current_sig
    ):
        return dict(cached.get("profile") or {})
    profile = build_catalog_profile(db)
    _CATALOG_PROFILE_CACHE[key] = {
        "profile": dict(profile or {}),
        "signature": current_sig,
        "expires_at": now + max(5, int(cache_ttl_sec or _CATALOG_PROFILE_TTL_SEC)),
    }
    return profile


def get_cached_catalog_profile_with_meta(db, *, tenant_id: str | None = None, cache_ttl_sec: int = _CATALOG_PROFILE_TTL_SEC) -> tuple[Dict[str, Any], Dict[str, Any]]:
    key = str(tenant_id or "default").strip().lower() or "default"
    now = time.time()
    cached = _CATALOG_PROFILE_CACHE.get(key)
    current_sig = _catalog_profile_signature(db)
    if (
        cached
        and float(cached.get("expires_at") or 0.0) > now
        and dict(cached.get("signature") or {}) == current_sig
    ):
        return dict(cached.get("profile") or {}), {"cache_hit": True, "cache_key": key}
    profile = build_catalog_profile(db)
    _CATALOG_PROFILE_CACHE[key] = {
        "profile": dict(profile or {}),
        "signature": current_sig,
        "expires_at": now + max(5, int(cache_ttl_sec or _CATALOG_PROFILE_TTL_SEC)),
    }
    return profile, {"cache_hit": False, "cache_key": key}


def invalidate_catalog_profile_cache(*, tenant_id: str | None = None) -> None:
    if tenant_id is None:
        _CATALOG_PROFILE_CACHE.clear()
        return
    key = str(tenant_id or "default").strip().lower() or "default"
    _CATALOG_PROFILE_CACHE.pop(key, None)


def infer_image_category(*, image_context: Dict[str, Any], query: str | None = None) -> str:
    labels = [str(x or "") for x in (image_context.get("labels") or [])]
    product_identity = image_context.get("product_identity") if isinstance(image_context.get("product_identity"), dict) else {}
    label_category = category_from_image_labels(labels)
    if label_category and label_category != "general":
        return label_category
    candidate = (
        str(image_context.get("intent") or "")
        or str(product_identity.get("product_type") or "")
        or str(product_identity.get("category") or "")
    )
    if candidate:
        cat = detect_category(query=candidate, image_labels=labels, constraints={"product_type": candidate})
        if cat and cat != "general":
            return cat
    image_text_blob = " ".join(
        [
            " ".join(labels),
            str(image_context.get("ocr") or ""),
        ]
    ).strip()
    if image_text_blob:
        cat = detect_category(query=image_text_blob, image_labels=labels, constraints=None)
        if cat and cat != "general":
            return cat
    query_text = str(query or "").strip()
    if query_text:
        return detect_category(query=query_text, image_labels=labels, constraints=None)
    return "general"


def assess_catalog_relevance(*, catalog_profile: Dict[str, Any], image_context: Dict[str, Any], query: str | None = None) -> Dict[str, Any]:
    img_category = infer_image_category(image_context=image_context, query=query)
    primary = str(catalog_profile.get("primary_category") or "general")
    dominant = [str(x) for x in (catalog_profile.get("dominant_categories") or []) if str(x)]
    is_mixed = bool(catalog_profile.get("is_mixed_catalog"))
    category_counts = {
        str(k): int(v or 0)
        for k, v in (catalog_profile.get("category_counts") or {}).items()
        if str(k)
    }
    total_products = max(1, int(catalog_profile.get("total_products") or 0))
    category_count = int(category_counts.get(img_category, 0))
    category_share = float(category_count) / float(total_products)

    if not img_category or img_category == "general":
        return {
            "off_domain": False,
            "image_category": img_category,
            "catalog_primary": primary,
            "catalog_category_count": category_count,
            "catalog_category_share": round(category_share, 4),
        }

    off_domain = False
    low_support = False
    soft_warning = None
    if category_count <= 0:
        off_domain = True
    elif img_category not in set(dominant or [primary]):
        if is_mixed:
            low_support = category_share < 0.12
            if img_category in _SUPPORTED_COMMERCE_CATEGORIES:
                off_domain = False
                if low_support:
                    soft_warning = "supported_commerce_category_not_primary_in_catalog"
            else:
                off_domain = True
                soft_warning = "image_category_not_supported_by_primary_catalog"
        else:
            off_domain = True

    return {
        "off_domain": off_domain,
        "low_support": low_support,
        "soft_warning": soft_warning,
        "image_category": img_category,
        "catalog_primary": primary,
        "dominant_categories": dominant,
        "is_mixed_catalog": is_mixed,
        "catalog_category_count": category_count,
        "catalog_category_share": round(category_share, 4),
    }
