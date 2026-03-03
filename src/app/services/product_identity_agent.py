"""Product Identity Agent — extracts structured specs from a product image via vision LLM.

Takes an image (bytes) and returns structured specs (brand, model, CPU tier, RAM, GPU,
display size, form factor) that can be injected as typed constraints into
Candidate_Retrieval_Agent for spec-anchored similarity search.

This agent is designed to run in Orchestrator Phase 1 alongside CV_Label_Agent.
"""
from __future__ import annotations

import base64
import json
import os
import re
import time
from typing import Any, Dict, Optional

import requests

try:
    from PIL import Image  # type: ignore
except Exception:  # pragma: no cover
    Image = None  # type: ignore

from src.app.services.decision_log import log_trace_event


_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def _extract_json(text: str) -> Dict[str, Any] | None:
    if not text:
        return None
    s = text.strip()
    try:
        return json.loads(s)
    except Exception:
        pass
    try:
        m = _JSON_RE.search(s)
        if m:
            return json.loads(m.group(0))
    except Exception:
        pass
    return None


_SPEC_EXTRACTION_PROMPT = (
    "You are a product identification specialist for an ecommerce platform.\n"
    "Analyze this product image and extract structured specifications.\n"
    "Return ONLY valid JSON (no markdown, no prose).\n"
    "Schema:\n"
    "{\n"
    '  "identified": true|false,\n'
    '  "product_type": "laptop|desktop|tablet|phone|monitor|accessory|other",\n'
    '  "brand": "string or null",\n'
    '  "model": "string or null",\n'
    '  "cpu_tier": "budget|midrange|performance|workstation|unknown",\n'
    '  "cpu_hint": "e.g. i5-13th, Ryzen 7, M2 Pro, or null",\n'
    '  "ram_gb_hint": 8|16|32|null,\n'
    '  "gpu_hint": "e.g. RTX 4060, integrated, or null",\n'
    '  "display_inches_hint": 14|15.6|16|null,\n'
    '  "form_factor": "ultrabook|standard|gaming|workstation|2-in-1|unknown",\n'
    '  "price_tier": "budget|midrange|premium|flagship|unknown",\n'
    '  "confidence": 0.0 to 1.0,\n'
    '  "notes": "short free-text"\n'
    "}\n"
    "Rules:\n"
    "- Identify from visible branding, form factor, bezels, keyboard layout, chassis design.\n"
    "- If you see visible text (model label, spec sticker), use it.\n"
    "- If uncertain about a field, use null or unknown.\n"
    "- confidence reflects overall identification certainty.\n"
)


def _get_ollama_urls() -> list[str]:
    env_url = (os.getenv("OLLAMA_URL") or "http://127.0.0.1:11434").rstrip("/")
    urls = [env_url]
    try:
        in_docker = os.path.exists("/.dockerenv")
    except Exception:
        in_docker = False
    if in_docker and ("127.0.0.1" in env_url or "localhost" in env_url):
        urls.append("http://host.docker.internal:11434")
    if (not in_docker) and ("host.docker.internal" in env_url):
        urls.append("http://127.0.0.1:11434")
    return list(dict.fromkeys(urls))


def _get_model_candidates() -> list[str]:
    chosen = (
        os.getenv("CV_IDENTITY_MODEL")
        or os.getenv("CV_VISION_MODEL")
        or os.getenv("OLLAMA_VISION_MODEL")
        or "llava:latest"
    ).strip()
    candidates = [chosen]
    if ":" in chosen:
        candidates.append(chosen.split(":", 1)[0])
    if chosen not in ("llava:latest", "llava"):
        candidates.extend(["llava:latest", "llava"])
    return list(dict.fromkeys(c for c in candidates if c))


def identify_product_from_image(
    image_bytes: bytes,
    *,
    user_query: str | None = None,
    trace_id: str | None = None,
    timeout_s: float = 12.0,
) -> Dict[str, Any]:
    """Extract structured product specs from an image via vision LLM.

    Returns dict with keys: identified, product_type, brand, model, cpu_tier,
    cpu_hint, ram_gb_hint, gpu_hint, display_inches_hint, form_factor,
    price_tier, confidence, notes, ok, ms, model_used.
    """
    empty: Dict[str, Any] = {
        "ok": False,
        "identified": False,
        "product_type": "unknown",
        "brand": None,
        "model": None,
        "cpu_tier": "unknown",
        "cpu_hint": None,
        "ram_gb_hint": None,
        "gpu_hint": None,
        "display_inches_hint": None,
        "form_factor": "unknown",
        "price_tier": "unknown",
        "confidence": 0.0,
        "notes": "",
    }
    if not image_bytes:
        return {**empty, "error": "no_image_bytes"}

    # Normalize to PNG for reliable vision model processing
    norm_bytes = image_bytes
    try:
        if Image is not None:
            import io
            img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            norm_bytes = buf.getvalue()
    except Exception:
        norm_bytes = image_bytes

    img_b64 = base64.b64encode(norm_bytes).decode("ascii")

    ctx_line = ""
    if user_query:
        ctx_line = f"User's query: {user_query}\n"

    prompt = _SPEC_EXTRACTION_PROMPT + ctx_line

    urls = _get_ollama_urls()
    models = _get_model_candidates()
    last_err = None

    for url in urls:
        for m in models:
            started = time.time()
            try:
                resp = requests.post(
                    f"{url}/api/generate",
                    json={
                        "model": m,
                        "prompt": prompt,
                        "images": [img_b64],
                        "stream": False,
                        "options": {"temperature": 0.0},
                    },
                    timeout=timeout_s,
                )
                ms = int((time.time() - started) * 1000)
                if resp.status_code >= 400:
                    last_err = {"error": f"ollama_http_{resp.status_code}", "ms": ms}
                    continue

                data = resp.json() if "json" in resp.headers.get("content-type", "") else {}
                raw = str(data.get("response") or "")
                parsed = _extract_json(raw)
                if not isinstance(parsed, dict):
                    last_err = {"error": "non_json_response", "ms": ms}
                    continue

                result = {**empty, **parsed, "ok": True, "ms": ms, "model_used": m}
                if trace_id:
                    try:
                        log_trace_event(
                            trace_id=trace_id,
                            event_type="product_identity_extracted",
                            source_type="agent",
                            source_id="Product_Identity_Agent",
                            target_type="system",
                            target_id=None,
                            payload={
                                "identified": result.get("identified"),
                                "brand": result.get("brand"),
                                "model": result.get("model"),
                                "cpu_tier": result.get("cpu_tier"),
                                "price_tier": result.get("price_tier"),
                                "confidence": result.get("confidence"),
                                "ms": ms,
                            },
                        )
                    except Exception:
                        pass
                return result
            except requests.exceptions.Timeout:
                last_err = {"error": "timeout", "ms": int((time.time() - started) * 1000)}
                continue
            except Exception as exc:
                last_err = {"error": str(exc)[:200], "ms": int((time.time() - started) * 1000)}
                continue

    return {**empty, **(last_err or {})}


def specs_to_constraints(identity: Dict[str, Any]) -> Dict[str, Any]:
    """Convert Product_Identity_Agent output into typed constraint dict
    suitable for merging into the Candidate_Retrieval_Agent's constraints.
    """
    if not identity.get("identified") or float(identity.get("confidence") or 0) < 0.3:
        return {}

    constraints: Dict[str, Any] = {}

    # Brand
    brand = identity.get("brand")
    if brand and brand.lower() not in ("unknown", "null", "none", ""):
        constraints["identity_brand"] = brand

    # Price tier → budget hints
    tier_map = {
        "budget": (300, 800),
        "midrange": (700, 1400),
        "premium": (1200, 2200),
        "flagship": (2000, None),
    }
    price_tier = str(identity.get("price_tier") or "").lower()
    if price_tier in tier_map:
        lo, hi = tier_map[price_tier]
        constraints["identity_budget_min"] = lo
        if hi:
            constraints["identity_budget_max"] = hi

    # CPU tier
    cpu_tier = identity.get("cpu_tier")
    if cpu_tier and cpu_tier != "unknown":
        constraints["identity_cpu_tier"] = cpu_tier

    # RAM hint
    ram = identity.get("ram_gb_hint")
    if ram and isinstance(ram, (int, float)) and ram > 0:
        constraints["identity_ram_gb_min"] = int(ram)

    # GPU hint
    gpu = identity.get("gpu_hint")
    if gpu and str(gpu).lower() not in ("null", "none", "unknown", "integrated", ""):
        constraints["identity_gpu_class"] = gpu

    # Display
    display = identity.get("display_inches_hint")
    if display and isinstance(display, (int, float)) and display > 0:
        constraints["identity_display_inches"] = float(display)

    # Form factor
    ff = identity.get("form_factor")
    if ff and ff != "unknown":
        constraints["identity_form_factor"] = ff

    # Product type
    pt = identity.get("product_type")
    if pt and pt != "unknown":
        constraints["identity_product_type"] = pt

    return constraints


# ---------------------------------------------------------------------------
# Text-based identity extraction (no vision LLM — uses labels + OCR)
# ---------------------------------------------------------------------------

_BRAND_PATTERNS: dict[str, list[str]] = {
    "Apple": ["apple", "macbook", "imac", "mac mini", "mac pro", "mac studio"],
    "Dell": ["dell", "xps", "inspiron", "latitude", "precision", "alienware", "vostro"],
    "HP": ["hp", "hewlett", "spectre", "envy", "pavilion", "elitebook", "probook", "omen", "zbook"],
    "Lenovo": ["lenovo", "thinkpad", "ideapad", "legion", "yoga", "thinkcentre", "thinkbook"],
    "ASUS": ["asus", "zenbook", "vivobook", "rog", "tuf", "proart", "expertbook"],
    "Acer": ["acer", "aspire", "nitro", "predator", "swift", "spin", "travelmate"],
    "Microsoft": ["surface", "microsoft surface"],
    "Samsung": ["samsung", "galaxy book", "galaxy tab"],
    "MSI": ["msi", "stealth", "raider", "creator"],
    "Razer": ["razer", "blade"],
    "LG": ["lg gram"],
    "Huawei": ["huawei", "matebook"],
    "Google": ["google pixel", "pixelbook", "chromebook pixel"],
    "Framework": ["framework"],
}

_PRODUCT_TYPE_KW: dict[str, list[str]] = {
    "laptop": ["laptop", "notebook", "ultrabook", "chromebook", "macbook"],
    "desktop": ["desktop", "tower", "pc", "imac", "mac mini", "mac pro", "mac studio", "nuc"],
    "tablet": ["tablet", "ipad", "surface go", "galaxy tab"],
    "monitor": ["monitor", "display", "screen"],
    "phone": ["phone", "iphone", "smartphone", "galaxy s", "pixel"],
}

_FORM_FACTOR_KW: dict[str, list[str]] = {
    "gaming": ["gaming", "rog", "tuf", "legion", "omen", "predator", "nitro", "alienware", "raider"],
    "ultrabook": ["ultrabook", "swift", "zenbook", "spectre", "xps", "gram", "macbook air"],
    "workstation": ["workstation", "precision", "zbook", "proart", "thinkpad p", "mac pro"],
    "2-in-1": ["2-in-1", "2 in 1", "convertible", "yoga", "spin", "surface pro"],
}

_CPU_TIER_KW: dict[str, str] = {
    "i3": "budget", "celeron": "budget", "pentium": "budget", "athlon": "budget",
    "ryzen 3": "budget", "m1": "midrange", "i5": "midrange", "ryzen 5": "midrange",
    "m2": "midrange", "m3": "midrange",
    "i7": "performance", "ryzen 7": "performance", "m2 pro": "performance",
    "m3 pro": "performance", "m4 pro": "performance",
    "i9": "workstation", "ryzen 9": "workstation", "xeon": "workstation",
    "threadripper": "workstation", "m2 max": "workstation", "m2 ultra": "workstation",
    "m3 max": "workstation", "m3 ultra": "workstation", "m4 max": "workstation",
}

_RAM_RE = re.compile(r"(\d{1,3})\s*gb\s*(?:ram|ddr|memory|lpddr)", re.IGNORECASE)
_DISPLAY_RE = re.compile(r"(\d{2}(?:\.\d)?)\s*[\-\"]?\s*(?:inch|in\b|\")", re.IGNORECASE)
_GPU_RE = re.compile(
    r"(rtx\s*\d{4}\w*|gtx\s*\d{4}\w*|rx\s*\d{4}\w*|radeon\s+\w+|"
    r"arc\s*a\d{3}\w*|quadro\s+\w+|firepro\s+\w+|m\d\s+gpu)",
    re.IGNORECASE,
)


def identify_product_from_text(
    labels: list[str],
    ocr_text: str,
    *,
    user_query: str | None = None,
    trace_id: str | None = None,
) -> Dict[str, Any]:
    """Extract product identity from image labels and OCR text without a vision LLM.

    Returns the same schema as ``identify_product_from_image`` so that
    ``specs_to_constraints`` can process the result directly.
    """
    combined = " ".join(labels or []) + " " + (ocr_text or "") + " " + (user_query or "")
    text_lower = combined.lower()

    result: Dict[str, Any] = {
        "ok": True,
        "identified": False,
        "product_type": "unknown",
        "brand": None,
        "model": None,
        "cpu_tier": "unknown",
        "cpu_hint": None,
        "ram_gb_hint": None,
        "gpu_hint": None,
        "display_inches_hint": None,
        "form_factor": "unknown",
        "price_tier": "unknown",
        "confidence": 0.0,
        "notes": "text-based extraction",
        "source": "text_heuristic",
    }

    # --- Brand detection ---
    for brand_name, keywords in _BRAND_PATTERNS.items():
        if any(kw in text_lower for kw in keywords):
            result["brand"] = brand_name
            break

    # --- Product type ---
    for ptype, keywords in _PRODUCT_TYPE_KW.items():
        if any(kw in text_lower for kw in keywords):
            result["product_type"] = ptype
            break

    # --- Form factor ---
    for ff, keywords in _FORM_FACTOR_KW.items():
        if any(kw in text_lower for kw in keywords):
            result["form_factor"] = ff
            break

    # --- CPU tier (longest match first) ---
    for cpu_kw in sorted(_CPU_TIER_KW, key=len, reverse=True):
        if cpu_kw in text_lower:
            result["cpu_tier"] = _CPU_TIER_KW[cpu_kw]
            result["cpu_hint"] = cpu_kw
            break

    # --- RAM ---
    ram_m = _RAM_RE.search(combined)
    if ram_m:
        ram_val = int(ram_m.group(1))
        if 2 <= ram_val <= 256:
            result["ram_gb_hint"] = ram_val

    # --- Display size ---
    disp_m = _DISPLAY_RE.search(combined)
    if disp_m:
        disp_val = float(disp_m.group(1))
        if 7 <= disp_val <= 40:
            result["display_inches_hint"] = disp_val

    # --- GPU ---
    gpu_m = _GPU_RE.search(combined)
    if gpu_m:
        result["gpu_hint"] = gpu_m.group(1).strip()

    # --- Confidence scoring ---
    fields_filled = sum(1 for k in ("brand", "cpu_hint", "ram_gb_hint", "gpu_hint", "display_inches_hint")
                        if result.get(k))
    # Boost: knowing the exact product_type is valuable signal
    if result["product_type"] != "unknown":
        fields_filled += 1
    # Boost: OCR text containing a model-like string (e.g. "ThinkPad X1 Carbon")
    if ocr_text and len(ocr_text.strip()) > 5:
        fields_filled += 1
    if result["brand"] or result["product_type"] != "unknown":
        result["identified"] = True
        result["confidence"] = min(0.9, 0.3 + fields_filled * 0.1)
    else:
        result["confidence"] = 0.0

    # --- Price tier inference ---
    if result["cpu_tier"] != "unknown":
        tier_price_map = {"budget": "budget", "midrange": "midrange",
                          "performance": "premium", "workstation": "flagship"}
        result["price_tier"] = tier_price_map.get(result["cpu_tier"], "unknown")

    if trace_id and result["identified"]:
        try:
            log_trace_event(
                trace_id=trace_id,
                event_type="product_identity_text_extracted",
                source_type="agent",
                source_id="Product_Identity_Agent",
                target_type="system",
                target_id=None,
                payload={
                    "identified": result["identified"],
                    "brand": result["brand"],
                    "model": result.get("model"),
                    "cpu_tier": result["cpu_tier"],
                    "form_factor": result["form_factor"],
                    "confidence": result["confidence"],
                    "source": "text_heuristic",
                },
            )
        except Exception:
            pass

    return result
