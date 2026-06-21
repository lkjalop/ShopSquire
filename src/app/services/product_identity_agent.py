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
from functools import lru_cache
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


# ADAPTER fallback: a vertical-neutral identify prompt used when the active profile defines no
# product_identity_prompt slot (electronics' laptop-schema prompt lives in electronics.json).
_GENERIC_IDENTITY_PROMPT = 'You are a product identification specialist for an ecommerce platform.\nAnalyze this product image and return ONLY valid JSON (no markdown, no prose):\n{\n  "identified": true|false,\n  "product_type": "string or other",\n  "brand": "string or null",\n  "model": "string or null",\n  "price_tier": "budget|midrange|premium|flagship|unknown",\n  "confidence": 0.0 to 1.0,\n  "notes": "short free-text"\n}\nRules: identify from visible branding and any visible text; use null/unknown when uncertain.\n'


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
    timeout_s: float | None = None,
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
    # The vision model needs enough TOTAL budget to finish ONE inference (cold
    # qwen2.5vl/llava can take 20-40s) — otherwise it times out, returns degraded,
    # and there is nothing to cache. The deadline below still prevents the url×model
    # loop from STACKING beyond this single budget. Tune via CV_IDENTITY_TIMEOUT_SEC;
    # for fast demos point CV_IDENTITY_MODEL at a small model (e.g. moondream).
    if timeout_s is None:
        timeout_s = float(os.getenv("CV_IDENTITY_TIMEOUT_SEC", "30") or 30)

    if not image_bytes:
        return {**empty, "error": "no_image_bytes"}

    # Image-hash cache: the vision call is the dominant latency (measured 50-86s).
    # A repeat of the SAME image — every live demo, retry, or multi-agent fan-out on
    # one upload — returns instantly instead of re-running the model. Fail-open.
    _cache_key = None
    try:
        from src.app.services import vision_cache as _vcache
        _cache_key = _vcache.image_key(image_bytes, "identity")
        _cached = _vcache.get(_cache_key)
        if isinstance(_cached, dict):
            return {**_cached, "from_cache": True}
    except Exception:
        _cache_key = None

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

    prompt = _identity_prompt_for(_active_pid()) + ctx_line

    urls = _get_ollama_urls()
    models = _get_model_candidates()
    last_err = None

    # Bound TOTAL time to ~timeout_s. The url×model loop previously waited up to
    # timeout_s PER iteration, so a slow/unreachable first model could stack to
    # N×timeout_s (a major contributor to the 50-86s image path).
    _deadline = time.time() + float(timeout_s)
    for url in urls:
        for m in models:
            _remaining = _deadline - time.time()
            if _remaining <= 0.5:
                last_err = last_err or {"error": "deadline_exceeded"}
                break
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
                    timeout=max(1.0, min(float(timeout_s), _remaining)),
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
                if _cache_key:
                    try:
                        from src.app.services import vision_cache as _vcache
                        _vcache.put(_cache_key, result)
                    except Exception:
                        pass
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

    # All attempts failed — make the otherwise-silent empty identity OBSERVABLE so a
    # vision outage shows up as a metric instead of just "no grounding" downstream.
    try:
        from src.app.observability.metrics import record_vision_extract_failure
        record_vision_extract_failure(str((last_err or {}).get("error") or "unknown"))
    except Exception:
        pass
    return {**empty, **(last_err or {}), "degraded": True}


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

    # Model / product line — the MOST specific anchor (e.g. "ThinkPad X1", "Pro 7"). Previously
    # dropped, which is why an uploaded photo of a specific model returned generic results. Carried
    # so retrieval/ranking can anchor on the exact product line, not just the brand.
    model = identity.get("model")
    if model and str(model).strip().lower() not in ("unknown", "null", "none", ""):
        constraints["identity_model"] = str(model).strip()

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
# Text-based identity extraction (no vision LLM — uses labels + OCR).
# Brand / product-type / form-factor / CPU keyword maps and the RAM/display/GPU regexes are
# resolved PER REQUEST from the active StoreProfile's identity_* slots (electronics excised
# verbatim). A vertical without these slots does NOT parse images through laptop identity
# fields — brand/type stay unknown (no electronics bleed).
# ---------------------------------------------------------------------------

@lru_cache(maxsize=8)
def _identity_patterns_for(pid: str) -> dict:
    from src.app.platform.store_profile import profile_slot
    return {
        "brand": dict(profile_slot("identity_brand_patterns", profile_id=pid, default={}) or {}),
        "ptype": dict(profile_slot("identity_product_type_kw", profile_id=pid, default={}) or {}),
        "form": dict(profile_slot("identity_form_factor_kw", profile_id=pid, default={}) or {}),
        "cpu": dict(profile_slot("identity_cpu_tier_kw", profile_id=pid, default={}) or {}),
    }


@lru_cache(maxsize=8)
def _identity_regexes_for(pid: str) -> dict:
    from src.app.platform.store_profile import profile_slot
    rx = profile_slot("identity_spec_regexes", profile_id=pid, default={}) or {}
    out = {}
    for key in ("ram", "display", "gpu"):
        pat = rx.get(key)
        out[key] = re.compile(pat, re.IGNORECASE) if pat else None
    return out


def _active_pid() -> str:
    from src.app.platform.store_profile import active_profile_id
    return active_profile_id()


def _identity_prompt_for(pid: str) -> str:
    from src.app.platform.store_profile import profile_slot
    p = profile_slot("product_identity_prompt", profile_id=pid, default=None)
    return p if isinstance(p, str) and p.strip() else _GENERIC_IDENTITY_PROMPT


def reset_cache() -> None:
    """Clear the per-profile identity-pattern caches (test isolation / reload)."""
    _identity_patterns_for.cache_clear()
    _identity_regexes_for.cache_clear()


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

    _pats = _identity_patterns_for(_active_pid())
    _rxs = _identity_regexes_for(_active_pid())

    # --- Brand detection ---
    for brand_name, keywords in _pats["brand"].items():
        if any(kw in text_lower for kw in keywords):
            result["brand"] = brand_name
            break

    # --- Product type ---
    for ptype, keywords in _pats["ptype"].items():
        if any(kw in text_lower for kw in keywords):
            result["product_type"] = ptype
            break

    # --- Form factor ---
    for ff, keywords in _pats["form"].items():
        if any(kw in text_lower for kw in keywords):
            result["form_factor"] = ff
            break

    # --- CPU tier (longest match first) ---
    for cpu_kw in sorted(_pats["cpu"], key=len, reverse=True):
        if cpu_kw in text_lower:
            result["cpu_tier"] = _pats["cpu"][cpu_kw]
            result["cpu_hint"] = cpu_kw
            break

    # --- RAM ---
    ram_m = _rxs["ram"].search(combined) if _rxs["ram"] else None
    if ram_m:
        ram_val = int(ram_m.group(1))
        if 2 <= ram_val <= 256:
            result["ram_gb_hint"] = ram_val

    # --- Display size ---
    disp_m = _rxs["display"].search(combined) if _rxs["display"] else None
    if disp_m:
        disp_val = float(disp_m.group(1))
        if 7 <= disp_val <= 40:
            result["display_inches_hint"] = disp_val

    # --- GPU ---
    gpu_m = _rxs["gpu"].search(combined) if _rxs["gpu"] else None
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
