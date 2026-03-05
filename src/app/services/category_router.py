"""Product category detection and NQE template routing.

Given a user query (and optional image labels), detects the product
category (e.g., laptop, phone, clothing, kitchen, furniture) and
returns the appropriate NQE template bank key for the template store.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple


# ── Category keyword maps (order matters: first match wins) ──────
_CATEGORY_PATTERNS: List[Tuple[str, List[str]]] = [
    # Electronics — computers
    ("laptop", [
        r"\blaptop\b", r"\bnotebook\b", r"\bultrabook\b", r"\bmacbook\b",
        r"\bchromebook\b", r"\bthinkpad\b", r"\bideapad\b", r"\blegion\b",
    ]),
    ("desktop", [r"\bdesktop\b", r"\bgaming\s?pc\b", r"\btower\b", r"\bmini\s?pc\b"]),
    ("phone", [r"\bphone\b", r"\bsmartphone\b", r"\biphone\b", r"\bgalaxy\b", r"\bpixel\b", r"\bmobile\b"]),
    ("tablet", [r"\btablet\b", r"\bipad\b", r"\bgalaxy\s?tab\b"]),
    ("monitor", [r"\bmonitor\b", r"\bdisplay\b", r"\bscreen\b"]),
    # Appliances / kitchen
    ("kitchen", [
        r"\bkitchen\b", r"\bmixer\b", r"\bblender\b", r"\btoaster\b",
        r"\bmicrowave\b", r"\bfridge\b", r"\brefrigerator\b", r"\bdishwasher\b",
        r"\boven\b", r"\bcoffee\s?maker\b", r"\bair\s?fryer\b",
    ]),
    # Home / furniture
    ("furniture", [
        r"\bsofa\b", r"\bcouch\b", r"\bbed\b", r"\bmattress\b", r"\bdesk\b",
        r"\bchair\b", r"\bbookshelf\b", r"\bwardrobe\b", r"\btable\b",
    ]),
    # Clothing / fashion
    ("clothing", [
        r"\bshirt\b", r"\bt-?shirt\b", r"\bjacket\b", r"\bdress\b", r"\bshoes?\b",
        r"\bsneaker\b", r"\bjeans\b", r"\bpants\b", r"\bskirt\b", r"\bcoat\b",
        r"\bsweater\b", r"\bhoodie\b", r"\bboots?\b",
    ]),
    # TV / AV
    ("tv", [r"\btelevision\b", r"\btv\b", r"\boled\b", r"\bqled\b", r"\bsoundbar\b"]),
    # Accessories / peripherals
    ("accessory", [
        r"\bkeyboard\b", r"\bmouse\b", r"\bcharger\b", r"\badapter\b",
        r"\bdock\b", r"\bheadset\b", r"\bearbuds?\b", r"\bheadphone\b",
        r"\bwebcam\b", r"\bspeaker\b",
    ]),
]

_COMPILED_PATTERNS: List[Tuple[str, List[re.Pattern]]] = [
    (cat, [re.compile(p, re.IGNORECASE) for p in pats])
    for cat, pats in _CATEGORY_PATTERNS
]

# Image labels (from CV) → category hints
_IMAGE_LABEL_MAP: Dict[str, str] = {
    "laptop": "laptop", "notebook": "laptop", "keyboard": "accessory",
    "phone": "phone", "cell phone": "phone", "smartphone": "phone",
    "television": "tv", "tv": "tv", "monitor": "monitor",
    "sofa": "furniture", "couch": "furniture", "bed": "furniture",
    "shirt": "clothing", "dress": "clothing", "shoe": "clothing",
    "refrigerator": "kitchen", "oven": "kitchen", "microwave": "kitchen",
}


def detect_category(
    query: str | None = None,
    image_labels: List[str] | None = None,
    constraints: Dict[str, Any] | None = None,
) -> str:
    """Return the detected product category slug (primary/top category).

    Priority: explicit constraint > query text > image labels > "general".
    """
    # 1. Explicit constraint
    if constraints:
        pt = str(constraints.get("product_type") or "").strip().lower()
        if pt and pt not in ("", "unknown", "other"):
            return pt

    # 2. Query text matching
    text = (query or "").lower()
    if text:
        for cat, patterns in _COMPILED_PATTERNS:
            for p in patterns:
                if p.search(text):
                    return cat

    # 3. Image labels
    for label in (image_labels or []):
        lbl = label.lower().strip()
        mapped = _IMAGE_LABEL_MAP.get(lbl)
        if mapped:
            return mapped

    return "general"


def nqe_template_key(category: str) -> str:
    """Map a category slug to the NQE template bank key in config/.

    Returns the key used to look up templates in the TemplateStore
    (e.g. "default" for laptop, "clothing" for clothing).
    """
    # Categories with dedicated template banks
    _HAS_BANK = {"clothing", "kitchen", "furniture", "tv", "phone", "tablet"}
    if category in _HAS_BANK:
        return category
    # Everything else falls back to default (laptop-oriented) bank
    return "default"


def route(
    query: str | None = None,
    image_labels: List[str] | None = None,
    constraints: Dict[str, Any] | None = None,
) -> Dict[str, str]:
    """Convenience: detect + resolve template key in one call."""
    cat = detect_category(query, image_labels, constraints)
    return {"category": cat, "template_key": nqe_template_key(cat)}


# ── Multi-Category NER ───────────────────────────────────────────

# Entity patterns: brand names, specs, use-cases
_BRAND_PATTERNS: List[Tuple[str, re.Pattern]] = [
    ("apple", re.compile(r"\b(apple|macbook|iphone|ipad|airpods?|imac)\b", re.I)),
    ("samsung", re.compile(r"\b(samsung|galaxy)\b", re.I)),
    ("dell", re.compile(r"\b(dell|xps|inspiron|latitude|alienware)\b", re.I)),
    ("hp", re.compile(r"\b(hp|pavilion|envy|spectre|omen|elitebook)\b", re.I)),
    ("lenovo", re.compile(r"\b(lenovo|thinkpad|ideapad|legion|yoga)\b", re.I)),
    ("asus", re.compile(r"\b(asus|rog|zenbook|vivobook|tuf)\b", re.I)),
    ("acer", re.compile(r"\b(acer|aspire|predator|nitro|swift)\b", re.I)),
    ("microsoft", re.compile(r"\b(microsoft|surface)\b", re.I)),
    ("google", re.compile(r"\b(google|pixel|chromebook)\b", re.I)),
    ("sony", re.compile(r"\b(sony|playstation|bravia)\b", re.I)),
    ("lg", re.compile(r"\blg\b", re.I)),
    ("nvidia", re.compile(r"\b(nvidia|geforce|rtx|gtx)\b", re.I)),
    ("amd", re.compile(r"\b(amd|ryzen|radeon)\b", re.I)),
    ("intel", re.compile(r"\b(intel|core\s?i[3579])\b", re.I)),
]

_USE_CASE_PATTERNS: List[Tuple[str, re.Pattern]] = [
    ("gaming", re.compile(r"\b(gaming|gamer|game|esports?|fps)\b", re.I)),
    ("video_editing", re.compile(r"\b(video\s?edit|premiere|davinci|final\s?cut|render)\b", re.I)),
    ("programming", re.compile(r"\b(coding|programming|developer|IDE|compil)\b", re.I)),
    ("business", re.compile(r"\b(business|office|enterprise|corporate|professional)\b", re.I)),
    ("student", re.compile(r"\b(student|school|university|college|homework)\b", re.I)),
    ("creative", re.compile(r"\b(creative|design|photo|illustrat|photoshop)\b", re.I)),
    ("streaming", re.compile(r"\b(stream|twitch|youtube|content\s?creat)\b", re.I)),
    ("travel", re.compile(r"\b(travel|portable|lightweight|on\s?the\s?go|commut)\b", re.I)),
    ("home_office", re.compile(r"\b(home\s?office|work\s?from\s?home|remote\s?work|wfh)\b", re.I)),
]

_SPEC_PATTERNS: List[Tuple[str, str, re.Pattern]] = [
    ("ram", "gb", re.compile(r"\b(\d+)\s?(?:gb?\s?)?ram\b", re.I)),
    ("storage", "gb", re.compile(r"\b(\d+)\s?(?:gb|tb)\s?(?:ssd|nvme|storage|hdd|hard\s?drive)\b", re.I)),
    ("screen_size", "inches", re.compile(r"\b(\d{2}(?:\.\d)?)[- ]?(?:in(?:ch)?|\")\b", re.I)),
    ("weight", "lbs", re.compile(r"\b(\d+(?:\.\d+)?)\s?(?:lbs?|pounds?|kg)\b", re.I)),
    ("battery", "hours", re.compile(r"\b(\d+)\s?(?:hr|hour|battery)\b", re.I)),
]


def detect_entities(
    query: str | None = None,
    image_labels: List[str] | None = None,
    constraints: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """Multi-category NER: extract all product categories, brands, specs, and use-cases.

    Returns:
        {
            "categories": [{"slug": "laptop", "confidence": 0.9}, ...],
            "brands": ["apple", "dell"],
            "use_cases": ["gaming", "programming"],
            "specs": {"ram": {"value": "16", "unit": "gb"}, ...},
            "primary_category": "laptop",
        }
    """
    text = (query or "").lower()
    categories: List[Dict[str, Any]] = []
    brands: List[str] = []
    use_cases: List[str] = []
    specs: Dict[str, Dict[str, str]] = {}

    # Detect all matching categories from text
    if text:
        for cat, patterns in _COMPILED_PATTERNS:
            match_count = sum(1 for p in patterns if p.search(text))
            if match_count > 0:
                confidence = min(0.6 + match_count * 0.15, 1.0)
                categories.append({"slug": cat, "confidence": round(confidence, 2), "match_count": match_count})

    # Detect from image labels
    for label in (image_labels or []):
        lbl = label.lower().strip()
        mapped = _IMAGE_LABEL_MAP.get(lbl)
        if mapped and not any(c["slug"] == mapped for c in categories):
            categories.append({"slug": mapped, "confidence": 0.7, "source": "image"})

    # Detect from explicit constraints
    if isinstance(constraints, dict):
        pt = constraints.get("product_type", "").lower().strip()
        if pt and not any(c["slug"] == pt for c in categories):
            categories.append({"slug": pt, "confidence": 1.0, "source": "constraint"})

    # Sort by confidence descending
    categories.sort(key=lambda c: c["confidence"], reverse=True)

    # Extract brands
    if text:
        for brand_name, pattern in _BRAND_PATTERNS:
            if pattern.search(text):
                brands.append(brand_name)

    # Extract use-cases
    if text:
        for use_case, pattern in _USE_CASE_PATTERNS:
            if pattern.search(text):
                use_cases.append(use_case)

    # Extract specs
    if text:
        for spec_name, unit, pattern in _SPEC_PATTERNS:
            m = pattern.search(text)
            if m:
                specs[spec_name] = {"value": m.group(1), "unit": unit}

    primary = categories[0]["slug"] if categories else detect_category(query, image_labels, constraints)

    return {
        "categories": categories,
        "brands": brands,
        "use_cases": use_cases,
        "specs": specs,
        "primary_category": primary,
        "multi_category": len(categories) > 1,
    }
