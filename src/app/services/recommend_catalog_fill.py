"""Catalog fallback fill for image-led V2 recommendations."""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text

from src.app.services.category_router import detect_category
from src.app.services.product_taxonomy import infer_product_family


def coarse_product_category(
    name: str,
    specs: dict[str, Any] | None = None,
) -> str:
    selected = specs if isinstance(specs, dict) else {}
    text_blob = " ".join([
        str(name or ""),
        str(selected.get("category") or ""),
        " ".join(str(item) for item in selected.get("tags") or [] if item is not None),
    ]).strip()
    category = detect_category(
        query=text_blob,
        image_labels=[str(selected.get("category") or "")],
        constraints=selected,
    )
    if category and category != "general":
        return category
    family = infer_product_family(name=name, specs=selected)
    return {
        "LAP": "laptop",
        "MON": "monitor",
        "PERIPH": "accessory",
        "HEAD": "accessory",
        "ACC": "accessory",
        "COOL": "accessory",
        "BAG": "accessory",
    }.get(family, "general")


def top_up_image_results(
    *,
    db: Any,
    results: list[dict[str, Any]],
    minimum_count: int,
    image_category: str,
    constraints: dict[str, Any],
    catalog_profile: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Fill a short image lane with same-category active catalog products."""
    if minimum_count <= 0 or len(results) >= minimum_count:
        return results, {"applied": False, "added": 0, "reason": "already_sufficient"}
    if not image_category or image_category == "general":
        return results, {
            "applied": False,
            "added": 0,
            "reason": "unknown_image_category",
        }

    existing_skus = {
        str((row or {}).get("sku") or "").strip() for row in results or []
    }
    budget_min = constraints.get("budget_min")
    budget_max = constraints.get("budget_max")
    try:
        rows = db.execute(text(
            """
            SELECT sku, name, price_cents, image_url, specs
            FROM products
            WHERE COALESCE(active, 1) = 1
            ORDER BY COALESCE(price_cents, 0) ASC, name ASC
            """
        )).fetchall()
    except Exception:
        return results, {
            "applied": False,
            "added": 0,
            "reason": "catalog_query_failed",
        }

    fallback_rows: list[dict[str, Any]] = []
    for row in rows or []:
        mapping = row._mapping if hasattr(row, "_mapping") else {}

        def value(key: str, index: int) -> Any:
            if mapping:
                return mapping.get(key)
            if isinstance(row, (tuple, list)) and len(row) > index:
                return row[index]
            return None

        sku = str(value("sku", 0) or "").strip()
        if not sku or sku in existing_skus:
            continue
        name = str(value("name", 1) or sku)
        price_cents = value("price_cents", 2)
        image_url = value("image_url", 3)
        raw_specs = value("specs", 4)
        if isinstance(raw_specs, str) and raw_specs.strip():
            try:
                specs = json.loads(raw_specs)
            except (TypeError, ValueError):
                specs = {}
        else:
            specs = raw_specs if isinstance(raw_specs, dict) else {}
        category = coarse_product_category(name, specs)
        family = infer_product_family(sku=sku, name=name, specs=specs)
        if image_category.strip().lower() == "laptop" and family != "LAP":
            continue
        if category != image_category:
            continue
        if isinstance(price_cents, (int, float)):
            if isinstance(budget_min, (int, float)) and price_cents < int(budget_min) * 100:
                continue
            if isinstance(budget_max, (int, float)) and price_cents > int(budget_max) * 100:
                continue
        fallback_rows.append({
            "sku": sku,
            "name": name,
            "price_cents": int(price_cents or 0),
            "image_url": image_url,
            "specs": specs,
            "confidence": 0.51,
            "factors": {
                "positive": ["catalog category match", "catalog fallback fill"],
                "negative": [],
            },
            "score": 0.01,
            "score_norm": 50.0,
            "rank_delta": None,
            "why_not": [],
            "contrastive_why": "",
            "delta_vs_anchor": {},
            "baseline_rank": None,
            "rerank_delta": None,
            "fallback_fill": True,
        })
        existing_skus.add(sku)
        if len(results) + len(fallback_rows) >= minimum_count:
            break
    merged = list(results or []) + fallback_rows
    return merged, {
        "applied": bool(fallback_rows),
        "added": len(fallback_rows),
        "reason": (
            "catalog_fill" if fallback_rows else "no_matching_fill_candidates"
        ),
        "minimum_count": minimum_count,
        "image_category": image_category,
        "catalog_primary": catalog_profile.get("primary_category"),
    }
