"""Cross-validate filename brand hints against vision model output.

Raises a mismatch signal when the brand inferred from the filename
differs from the brand detected by the vision model — a potential
filename-spoofing attack against the recommendation engine.
"""
from __future__ import annotations

from typing import Dict, List, Optional

_BRAND_KEYWORDS: Dict[str, List[str]] = {
    "apple": ["macbook", "mac", "imac", "apple", "mac mini", "mac pro"],
    "msi": ["msi", "stealth", "raider", "titan", "creator"],
    "lenovo": ["lenovo", "thinkpad", "ideapad", "legion", "yoga"],
    "dell": ["dell", "xps", "inspiron", "alienware", "latitude"],
    "hp": ["hp", "spectre", "envy", "omen", "elitebook", "probook"],
    "asus": ["asus", "rog", "zenbook", "vivobook"],
    "acer": ["acer", "predator", "aspire", "swift", "nitro"],
    "razer": ["razer", "blade"],
    "microsoft": ["microsoft", "surface"],
    "samsung": ["samsung", "galaxy book"],
    "gigabyte": ["gigabyte", "aorus"],
    "toshiba": ["toshiba", "dynabook"],
}


def extract_brand_from_filename(filename: str) -> Optional[str]:
    """Return brand slug if *filename* contains a known brand keyword."""
    fn = filename.lower().replace("-", " ").replace("_", " ")
    for brand, keywords in _BRAND_KEYWORDS.items():
        if any(kw in fn for kw in keywords):
            return brand
    return None


def _brand_from_text(text: str) -> Optional[str]:
    """Return brand slug found inside *text* (labels joined, etc.)."""
    low = text.lower()
    for brand, keywords in _BRAND_KEYWORDS.items():
        if any(kw in low for kw in keywords):
            return brand
    return None


def validate_filename_vs_labels(
    filename: str,
    vision_labels: List[str],
    product_identity: Optional[Dict] = None,
) -> Dict:
    """Compare filename-derived brand with vision-model-detected brand.

    Returns a dict with:
      - ``filename_brand``: brand from filename (or ``None``)
      - ``vision_brand``:   brand from vision labels / product_identity (or ``None``)
      - ``match``:          ``True``/``False``/``None`` (None = undetermined)
      - ``mismatch``:       ``True`` when both brands are known and differ
    """
    fn_brand = extract_brand_from_filename(filename)

    # Prefer product_identity.brand (from the vision model) when available
    vision_brand: Optional[str] = None
    if product_identity and product_identity.get("brand"):
        vision_brand = _brand_from_text(str(product_identity["brand"]))
    if vision_brand is None:
        vision_brand = _brand_from_text(" ".join(vision_labels))

    mismatch = bool(fn_brand and vision_brand and fn_brand != vision_brand)
    match: Optional[bool] = None
    if fn_brand and vision_brand:
        match = fn_brand == vision_brand

    return {
        "filename_brand": fn_brand,
        "vision_brand": vision_brand,
        "match": match,
        "mismatch": mismatch,
    }
