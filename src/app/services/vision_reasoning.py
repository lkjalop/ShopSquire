"""Vision LLM reasoning service.

Wraps vision-capable LLM providers in priority order:
  1. OpenAI GPT-4o   (OPENAI_API_KEY)
  2. Google Gemini   (GOOGLE_AI_API_KEY)
  3. Ollama LLaVA    (OLLAMA_VISION_MODEL, default llava:13b)

Falls back gracefully to None when no provider is configured —
callers (cv_triage_basic, vision router) should detect `result.error`
and fall through to their existing keyword logic.
"""
from __future__ import annotations

import base64
import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from src.app.config import get_settings
from src.app.security.provider_boundary import require_provider_transfer, sanitize_for_provider

log = logging.getLogger(__name__)


def _normalize_image_bytes(image_bytes: bytes, *, max_px: int = 1024) -> bytes:
    """Transcode to PNG AND downscale to <=max_px so the vision model reliably decodes it. Ollama vision
    returns an EMPTY response for oversized images (measured 2026-06-28: 2048x2048 .webp → empty; the same
    image at 1024px → correct identification) and for some .webp inputs; PNG <=1024px works. Falls back to
    the raw bytes if PIL can't open them (non-image payloads are handled upstream)."""
    try:
        import io
        from PIL import Image
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        img.thumbnail((max_px, max_px))  # in-place, preserves aspect ratio; no-op if already smaller
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except Exception:
        return image_bytes

# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class ExtractedSpecs:
    brand: Optional[str] = None
    model_name: Optional[str] = None
    cpu: Optional[str] = None
    ram_gb: Optional[int] = None
    display_inches: Optional[float] = None
    storage_gb: Optional[int] = None
    gpu: Optional[str] = None
    condition: Optional[str] = None
    color: Optional[str] = None


@dataclass
class VisionResult:
    product_type: str = "unknown"
    extracted_specs: ExtractedSpecs = field(default_factory=ExtractedSpecs)
    damage_type: Optional[str] = None        # physical / cosmetic / functional / packaging / none
    damage_severity: Optional[str] = None    # critical / major / minor / none
    damaged_component: Optional[str] = None  # display / chassis / keyboard / power / none
    visual_confidence: float = 0.0
    plain_english_summary: str = ""
    raw_vision_response: str = ""
    provider_used: str = "none"
    error: Optional[str] = None

    def to_nqe_facts(self) -> Dict[str, Any]:
        """Return fields suitable for injecting into NQEInput.answered_fields."""
        facts: Dict[str, Any] = {}
        s = self.extracted_specs
        if s.brand:
            facts["brand"] = s.brand
        if s.model_name:
            facts["model"] = s.model_name
        if s.ram_gb:
            facts["ram_gb"] = s.ram_gb
        if s.display_inches:
            facts["display_size"] = s.display_inches
        if s.cpu:
            facts["cpu"] = s.cpu
        if s.storage_gb:
            facts["storage_gb"] = s.storage_gb
        return facts

    def to_dict(self) -> Dict[str, Any]:
        return {
            "product_type": self.product_type,
            "brand": self.extracted_specs.brand,
            "model": self.extracted_specs.model_name,
            "ram_gb": self.extracted_specs.ram_gb,
            "display_inches": self.extracted_specs.display_inches,
            "cpu": self.extracted_specs.cpu,
            "storage_gb": self.extracted_specs.storage_gb,
            "gpu": self.extracted_specs.gpu,
            "condition": self.extracted_specs.condition,
            "damage_type": self.damage_type,
            "damage_severity": self.damage_severity,
            "damaged_component": self.damaged_component,
            "visual_confidence": round(self.visual_confidence, 2),
            "plain_english_summary": self.plain_english_summary,
            "provider_used": self.provider_used,
            "error": self.error,
        }


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

_PRODUCT_PROMPT = """You are a product identification expert for a tech retailer.
Look at this image and extract what you can see. Return ONLY raw JSON (no markdown, no code fences):
{
  "product_type": "laptop|phone|tablet|monitor|keyboard|camera|other|unknown",
  "brand": "brand name or null",
  "model_name": "specific model name or null",
  "cpu": "processor name or null",
  "ram_gb": integer or null,
  "display_inches": float or null,
  "storage_gb": integer or null,
  "gpu": "GPU name or null",
  "condition": "new|used|damaged|unknown",
  "color": "color or null",
  "plain_english_summary": "One sentence. E.g.: This is a 15-inch Dell XPS 15 with 16GB RAM in good condition."
}
Only include values you can actually see. Use null for anything not visible."""

_DAMAGE_PROMPT = """You are a warranty claims assessor at a tech retailer.
Look at this image and assess any visible damage. Return ONLY raw JSON (no markdown, no code fences):
{
  "damage_type": "physical|cosmetic|functional|packaging|none",
  "damage_severity": "critical|major|minor|none",
  "damaged_component": "display|chassis|keyboard|power_port|battery|none",
  "plain_english_summary": "One sentence a customer service rep would say to the customer."
}"""


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class VisionReasoningService:
    """
    Thin async wrapper over vision LLM providers.
    Instantiate once and reuse — provider detection is cached at init time.
    """

    def __init__(self) -> None:
        self._provider = self._detect_provider()

    # ------------------------------------------------------------------
    # Provider detection
    # ------------------------------------------------------------------
    @staticmethod
    def _detect_provider() -> str:
        settings = get_settings()
        if str(settings.openai_api_key or "").strip():
            return "openai"
        if str(settings.google_ai_api_key or "").strip():
            return "gemini"
        vision_model = str(settings.ollama_vision_model or "").strip()
        if vision_model:
            return "ollama"
        return "none"

    @property
    def available(self) -> bool:
        return self._provider != "none"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    async def analyze_product(
        self,
        image_bytes: bytes,
        mime: str = "image/jpeg",
    ) -> VisionResult:
        """Extract product type, brand, model and specs from a product photo."""
        return await self._dispatch(image_bytes, mime, _PRODUCT_PROMPT, mode="product")

    async def analyze_damage(
        self,
        image_bytes: bytes,
        mime: str = "image/jpeg",
    ) -> VisionResult:
        """Classify damage type, severity and component from a damage photo."""
        return await self._dispatch(image_bytes, mime, _DAMAGE_PROMPT, mode="damage")

    # ------------------------------------------------------------------
    # Internal dispatch
    # ------------------------------------------------------------------
    async def _dispatch(
        self,
        image_bytes: bytes,
        mime: str,
        prompt: str,
        mode: str,
    ) -> VisionResult:
        if self._provider == "none":
            return self._err("No vision LLM configured. Set OPENAI_API_KEY, GOOGLE_AI_API_KEY, or OLLAMA_VISION_MODEL.")
        try:
            if self._provider == "openai":
                return await self._openai(image_bytes, mime, prompt, mode)
            if self._provider == "gemini":
                return await self._gemini(image_bytes, mime, prompt, mode)
            if self._provider == "ollama":
                return await self._ollama(image_bytes, mime, prompt, mode)
        except Exception as exc:
            log.warning("VisionReasoningService (%s) failed: %s", self._provider, exc)
            return self._err(str(exc), provider=self._provider)
        return self._err("unknown provider")

    # ------------------------------------------------------------------
    # OpenAI GPT-4o
    # ------------------------------------------------------------------
    async def _openai(
        self,
        image_bytes: bytes,
        mime: str,
        prompt: str,
        mode: str,
    ) -> VisionResult:
        try:
            import openai  # type: ignore
        except ImportError:
            return self._err("openai package not installed — pip install openai")

        require_provider_transfer("openai", data_categories=["vision_image"])
        prompt, _, _ = sanitize_for_provider("openai", prompt, data_categories=["vision_prompt"])
        b64 = base64.b64encode(_normalize_image_bytes(image_bytes)).decode()
        api_key = get_settings().openai_api_key
        client = openai.AsyncOpenAI(api_key=api_key)
        resp = await client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{mime};base64,{b64}",
                                "detail": "high",
                            },
                        },
                    ],
                }
            ],
            max_tokens=512,
            temperature=0,
        )
        raw = resp.choices[0].message.content or ""
        return self._parse(raw, provider="openai", mode=mode)

    # ------------------------------------------------------------------
    # Google Gemini Pro Vision
    # ------------------------------------------------------------------
    async def _gemini(
        self,
        image_bytes: bytes,
        mime: str,
        prompt: str,
        mode: str,
    ) -> VisionResult:
        try:
            import google.generativeai as genai  # type: ignore
            import PIL.Image  # type: ignore
            import io
        except ImportError:
            return self._err("google-generativeai / Pillow not installed — pip install google-generativeai pillow")

        require_provider_transfer("gemini", data_categories=["vision_image"])
        prompt, _, _ = sanitize_for_provider("gemini", prompt, data_categories=["vision_prompt"])
        genai.configure(api_key=get_settings().google_ai_api_key)
        img = PIL.Image.open(io.BytesIO(image_bytes))
        model = genai.GenerativeModel("gemini-1.5-pro-latest")
        response = model.generate_content([prompt, img])
        raw = response.text or ""
        return self._parse(raw, provider="gemini", mode=mode)

    # ------------------------------------------------------------------
    # Ollama LLaVA (local)
    # ------------------------------------------------------------------
    async def _ollama(
        self,
        image_bytes: bytes,
        mime: str,
        prompt: str,
        mode: str,
    ) -> VisionResult:
        try:
            import httpx  # type: ignore
        except ImportError:
            return self._err("httpx not installed")

        b64 = base64.b64encode(_normalize_image_bytes(image_bytes)).decode()
        vision_model = get_settings().ollama_vision_model or "llava:13b"
        ollama_url = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{ollama_url.rstrip('/')}/api/generate",
                json={
                    "model": vision_model,
                    "prompt": prompt,
                    "images": [b64],
                    "stream": False,
                    "options": {"temperature": 0},
                },
            )
            resp.raise_for_status()
            raw = resp.json().get("response", "")
        return self._parse(raw, provider="ollama", mode=mode)

    # ------------------------------------------------------------------
    # Response parser
    # ------------------------------------------------------------------
    def _parse(self, raw: str, *, provider: str, mode: str) -> VisionResult:
        cleaned = raw.strip()
        # Strip markdown code fences if LLM wrapped the JSON
        if cleaned.startswith("```"):
            lines = cleaned.splitlines()
            start = 1
            end = len(lines) - 1 if lines[-1].strip() == "```" else len(lines)
            cleaned = "\n".join(lines[start:end])
        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError:
            log.debug("Vision LLM non-JSON response (provider=%s): %s", provider, raw[:200])
            return self._err(f"LLM returned non-JSON: {raw[:120]}", provider=provider)

        summary = data.get("plain_english_summary") or ""

        if mode == "product":
            specs = ExtractedSpecs(
                brand=_str_or_none(data.get("brand")),
                model_name=_str_or_none(data.get("model_name")),
                cpu=_str_or_none(data.get("cpu")),
                ram_gb=_int_or_none(data.get("ram_gb")),
                display_inches=_float_or_none(data.get("display_inches")),
                storage_gb=_int_or_none(data.get("storage_gb")),
                gpu=_str_or_none(data.get("gpu")),
                condition=_str_or_none(data.get("condition")),
                color=_str_or_none(data.get("color")),
            )
            # Confidence: higher when we identified brand or model
            identified = sum(
                1
                for v in [specs.brand, specs.model_name, specs.ram_gb, specs.cpu]
                if v is not None
            )
            confidence = min(0.5 + identified * 0.1, 0.90)
            return VisionResult(
                product_type=_str_or_none(data.get("product_type")) or "unknown",
                extracted_specs=specs,
                visual_confidence=confidence,
                plain_english_summary=summary,
                raw_vision_response=raw,
                provider_used=provider,
            )
        else:  # damage
            return VisionResult(
                product_type="unknown",
                damage_type=_str_or_none(data.get("damage_type")),
                damage_severity=_str_or_none(data.get("damage_severity")),
                damaged_component=_str_or_none(data.get("damaged_component")),
                visual_confidence=0.80,
                plain_english_summary=summary,
                raw_vision_response=raw,
                provider_used=provider,
            )

    @staticmethod
    def _err(reason: str, provider: str = "none") -> VisionResult:
        return VisionResult(error=reason, provider_used=provider)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _str_or_none(v: Any) -> Optional[str]:
    if v is None:
        return None
    s = str(v).strip()
    return s if s and s.lower() not in ("null", "none", "") else None


def _int_or_none(v: Any) -> Optional[int]:
    try:
        return int(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _float_or_none(v: Any) -> Optional[float]:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None
