# Production-Grade: Orchestrator Vision Reasoning
*ShopSquire — Deep Dive Implementation Guide | 2026-03-25*

---

## What Is Broken Today

### Current Reality

| Component | File | Status |
|-----------|------|--------|
| Image intake | `src/app/services/image_intake.py` | Real (sanitize + phash) |
| Intent router | `src/app/services/image_intent_router.py` | Real (confidence scoring) |
| CV triage | `src/app/services/cv_triage_basic.py` | **STUB** — keyword labels only |
| Product identity | Not wired anywhere | **MISSING** |
| Spec extraction | Not wired anywhere | **MISSING** |
| Multimodal complexity | `src/app/services/llm_provider.py:142` | **BUG** — score too low |
| Vision to NQE seed | Not wired | **MISSING** |

### The User-Visible Symptoms

1. User uploads a photo of a Lenovo ThinkPad → ShopSquire says "I see a laptop" and asks budget — it should extract the model, RAM, display size from the image and use those as search constraints.
2. User uploads a damage photo → returns generic "damage detected, severity undetermined" — because `cv_triage_basic.py` line 9 is a placeholder for a cloud CV API that was never wired.
3. Complex image+text queries route to `llama3.3:8b` (small model) because the complexity score never exceeds 5 for multimodal queries — even when the user uploads an image and asks a synthesis question.

---

## Architecture Change: Vision Reasoning Stack

```
CURRENT (broken path):
  upload → image_intake → image_intent_router → cv_triage_basic (stub)
                                                       ↓
                                               keyword match only
                                               confidence: 0.3–0.85 hardcoded

PRODUCTION (new path):
  upload → image_intake → image_intent_router
       ↓                         ↓
  sanitized bytes         intent=cv_triage
       └──────────────────────────┘
                   ↓
          VisionReasoningService
          (GPT-4V / Gemini / LLaVA-13B)
                   ↓
          VisionResult {
            product_type, brand, model,
            damage_type, damage_severity,
            extracted_specs: {ram, cpu, display_size, storage},
            visual_confidence,
            plain_english_summary
          }
                   ↓
     ┌─────────────────────────────┐
     │  Product_Identity_Agent     │  ← NEW
     │  seeds NQE with known facts │
     │  sets constraint overrides  │
     └─────────────────────────────┘
                   ↓
         NQE skips already-known fields
         recommend.py uses extracted specs as hard constraints
```

---

## Step 1 — Fix Multimodal Complexity Scoring

**File:** `src/app/services/llm_provider.py`
**Lines:** 139–155 (approximately)

### Current Code (around line 142)
```python
if ctx.get("has_image"):
    signals["multimodal"] = True
    score += 1
```

### The Bug
A user uploading an image and asking "Is this laptop compatible with my software setup?" scores +1 (multimodal) but likely stays under 5, routing to `llama3.3:8b` which cannot reason about images at all.

### Fix
```python
# llm_provider.py  ~line 139
if ctx.get("has_image"):
    signals["multimodal"] = True
    score += 2  # was +1 — image alone warrants medium model minimum

    # Vision synthesis: image + open-ended question (not just "what is this")
    synthesis_patterns = [
        "compatible", "enough", "compare", "better", "difference",
        "good for", "will it", "can it", "should i", "recommend"
    ]
    q_lower = query.lower()
    if any(p in q_lower for p in synthesis_patterns):
        signals["vision_synthesis"] = True
        score += 2  # synthesis over image → needs large model context window

    # Visual similarity intent (user wants "find me something like this")
    similarity_patterns = ["like this", "similar to", "same as", "find this", "match"]
    if any(p in q_lower for p in similarity_patterns):
        signals["visual_similarity"] = True
        score += 1
```

**Effect:** Multimodal queries now score minimum 7 (medium/large), 9 for synthesis — routing to `mixtral:8x7b` or better.

---

## Step 2 — Create VisionReasoningService

**New file:** `src/app/services/vision_reasoning.py`

This service wraps whichever vision LLM is configured and returns a typed result. It supports three backends in priority order: OpenAI GPT-4V, Google Gemini Pro Vision, local LLaVA via Ollama.

```python
# src/app/services/vision_reasoning.py
from __future__ import annotations
import base64, json, logging
from dataclasses import dataclass, field
from typing import Optional, Dict, Any
from src.app.config import settings

log = logging.getLogger(__name__)

@dataclass
class ExtractedSpecs:
    brand: Optional[str] = None
    model_name: Optional[str] = None
    cpu: Optional[str] = None
    ram_gb: Optional[int] = None
    display_inches: Optional[float] = None
    storage_gb: Optional[int] = None
    gpu: Optional[str] = None
    condition: Optional[str] = None   # new / used / damaged
    color: Optional[str] = None

@dataclass
class VisionResult:
    product_type: str = "unknown"
    extracted_specs: ExtractedSpecs = field(default_factory=ExtractedSpecs)
    damage_type: Optional[str] = None          # physical/cosmetic/functional/None
    damage_severity: Optional[str] = None      # critical/major/minor/None
    damaged_component: Optional[str] = None    # display/chassis/keyboard/None
    visual_confidence: float = 0.0
    plain_english_summary: str = ""
    raw_vision_response: str = ""
    provider_used: str = "none"
    error: Optional[str] = None

    def to_nqe_facts(self) -> Dict[str, Any]:
        """Return a dict suitable for injecting into NQEInput.answered_fields"""
        facts: Dict[str, Any] = {}
        s = self.extracted_specs
        if s.brand:       facts["brand"] = s.brand
        if s.model_name:  facts["model"] = s.model_name
        if s.ram_gb:      facts["ram_gb"] = s.ram_gb
        if s.display_inches: facts["display_size"] = s.display_inches
        if s.cpu:         facts["cpu"] = s.cpu
        if s.storage_gb:  facts["storage_gb"] = s.storage_gb
        return facts


class VisionReasoningService:
    """
    Wraps vision LLM providers.  Priority: OpenAI GPT-4V → Gemini → LLaVA (Ollama).
    Falls back gracefully to cv_triage_basic if no vision LLM configured.
    """

    PRODUCT_PROMPT = """You are a product identification expert.
Look at this image and extract the following in JSON (no markdown, raw JSON only):
{
  "product_type": "laptop|phone|tablet|monitor|keyboard|camera|other|unknown",
  "brand": "brand name or null",
  "model_name": "specific model or null",
  "cpu": "processor name or null",
  "ram_gb": integer or null,
  "display_inches": float or null,
  "storage_gb": integer or null,
  "gpu": "GPU name or null",
  "condition": "new|used|damaged|unknown",
  "color": "color or null",
  "plain_english_summary": "One sentence a customer would understand. E.g.: 'This is a 15-inch Dell XPS with 16GB RAM and a cracked screen on the bottom-left corner.'"
}
Focus on what is VISIBLE in the image. Use null for anything you cannot see."""

    DAMAGE_PROMPT = """You are a warranty claims assessor.
Look at this image and assess any damage. Return JSON only:
{
  "damage_type": "physical|cosmetic|functional|packaging|none",
  "damage_severity": "critical|major|minor|none",
  "damaged_component": "display|chassis|keyboard|power_port|battery|none",
  "damage_description": "One plain-English sentence describing what you see",
  "plain_english_summary": "What a customer service rep would tell the customer"
}"""

    def __init__(self):
        self._provider = self._detect_provider()

    def _detect_provider(self) -> str:
        if getattr(settings, "OPENAI_API_KEY", None):
            return "openai"
        if getattr(settings, "GOOGLE_AI_API_KEY", None):
            return "gemini"
        if getattr(settings, "OLLAMA_VISION_MODEL", None):
            return "ollama"
        return "none"

    async def analyze_product(self, image_bytes: bytes, mime: str = "image/jpeg") -> VisionResult:
        if self._provider == "none":
            return self._fallback_result("No vision LLM configured. Set OPENAI_API_KEY, GOOGLE_AI_API_KEY, or OLLAMA_VISION_MODEL.")
        try:
            if self._provider == "openai":
                return await self._openai_analyze(image_bytes, mime, self.PRODUCT_PROMPT, mode="product")
            if self._provider == "gemini":
                return await self._gemini_analyze(image_bytes, mime, self.PRODUCT_PROMPT, mode="product")
            if self._provider == "ollama":
                return await self._ollama_analyze(image_bytes, mime, self.PRODUCT_PROMPT, mode="product")
        except Exception as exc:
            log.exception("Vision reasoning failed")
            return self._fallback_result(str(exc))
        return self._fallback_result("Unknown provider")

    async def analyze_damage(self, image_bytes: bytes, mime: str = "image/jpeg") -> VisionResult:
        if self._provider == "none":
            return self._fallback_result("No vision LLM configured.")
        try:
            if self._provider == "openai":
                return await self._openai_analyze(image_bytes, mime, self.DAMAGE_PROMPT, mode="damage")
            if self._provider == "gemini":
                return await self._gemini_analyze(image_bytes, mime, self.DAMAGE_PROMPT, mode="damage")
            if self._provider == "ollama":
                return await self._ollama_analyze(image_bytes, mime, self.DAMAGE_PROMPT, mode="damage")
        except Exception as exc:
            log.exception("Damage vision analysis failed")
            return self._fallback_result(str(exc))
        return self._fallback_result("Unknown provider")

    # ── OpenAI GPT-4V ──────────────────────────────────────────────────────────
    async def _openai_analyze(self, image_bytes: bytes, mime: str, prompt: str, mode: str) -> VisionResult:
        import openai
        b64 = base64.b64encode(image_bytes).decode()
        client = openai.AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        resp = await client.chat.completions.create(
            model="gpt-4o",  # gpt-4o has vision built in as of 2025
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}", "detail": "high"}}
                ]
            }],
            max_tokens=512,
            temperature=0
        )
        raw = resp.choices[0].message.content or ""
        return self._parse_vision_response(raw, provider="openai", mode=mode)

    # ── Google Gemini Pro Vision ────────────────────────────────────────────────
    async def _gemini_analyze(self, image_bytes: bytes, mime: str, prompt: str, mode: str) -> VisionResult:
        import google.generativeai as genai
        genai.configure(api_key=settings.GOOGLE_AI_API_KEY)
        import PIL.Image, io
        img = PIL.Image.open(io.BytesIO(image_bytes))
        model = genai.GenerativeModel("gemini-1.5-pro-vision-latest")
        response = model.generate_content([prompt, img])
        raw = response.text or ""
        return self._parse_vision_response(raw, provider="gemini", mode=mode)

    # ── Ollama LLaVA (local) ───────────────────────────────────────────────────
    async def _ollama_analyze(self, image_bytes: bytes, mime: str, prompt: str, mode: str) -> VisionResult:
        import httpx
        b64 = base64.b64encode(image_bytes).decode()
        model = getattr(settings, "OLLAMA_VISION_MODEL", "llava:13b")
        ollama_url = getattr(settings, "OLLAMA_BASE_URL", "http://ollama:11434")
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(f"{ollama_url}/api/generate", json={
                "model": model,
                "prompt": prompt,
                "images": [b64],
                "stream": False,
                "options": {"temperature": 0}
            })
            resp.raise_for_status()
            raw = resp.json().get("response", "")
        return self._parse_vision_response(raw, provider="ollama", mode=mode)

    # ── Response Parser ────────────────────────────────────────────────────────
    def _parse_vision_response(self, raw: str, provider: str, mode: str) -> VisionResult:
        # Strip markdown code fences if LLM wraps in ```json ... ```
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            cleaned = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError:
            return self._fallback_result(f"Vision LLM returned non-JSON: {raw[:200]}", provider=provider)

        if mode == "product":
            specs = ExtractedSpecs(
                brand=data.get("brand"),
                model_name=data.get("model_name"),
                cpu=data.get("cpu"),
                ram_gb=data.get("ram_gb"),
                display_inches=data.get("display_inches"),
                storage_gb=data.get("storage_gb"),
                gpu=data.get("gpu"),
                condition=data.get("condition"),
                color=data.get("color"),
            )
            return VisionResult(
                product_type=data.get("product_type", "unknown"),
                extracted_specs=specs,
                visual_confidence=0.85 if any([specs.brand, specs.model_name, specs.ram_gb]) else 0.45,
                plain_english_summary=data.get("plain_english_summary", ""),
                raw_vision_response=raw,
                provider_used=provider,
            )
        else:  # damage
            return VisionResult(
                product_type="unknown",
                damage_type=data.get("damage_type"),
                damage_severity=data.get("damage_severity"),
                damaged_component=data.get("damaged_component"),
                plain_english_summary=data.get("plain_english_summary", data.get("damage_description", "")),
                raw_vision_response=raw,
                provider_used=provider,
                visual_confidence=0.8,
            )

    def _fallback_result(self, reason: str, provider: str = "none") -> VisionResult:
        return VisionResult(
            product_type="unknown",
            visual_confidence=0.0,
            plain_english_summary="",
            error=reason,
            provider_used=provider,
        )
```

---

## Step 3 — Wire VisionReasoningService into cv_triage_basic.py

**File:** `src/app/services/cv_triage_basic.py`
**Lines to change:** 9–85

### Current (stub)
```python
# line 9
# Managed API placeholder: replace label source with cloud CV (Google/Azure)
# ...
# analyze() returns confidence 0.3–0.85 based on keyword count only
```

### Replacement Pattern

Replace the `analyze()` method body:

```python
# cv_triage_basic.py  (complete rewrite of the analyze() method, ~line 27)
async def analyze(
    self,
    image_bytes: bytes,
    labels: list[str],
    ocr_text: str = "",
    mime: str = "image/jpeg",
) -> CVTriageResult:
    from src.app.services.vision_reasoning import VisionReasoningService, VisionResult

    svc = VisionReasoningService()

    # If vision LLM available, use it — otherwise fall through to keyword logic
    if svc._provider != "none":
        vision: VisionResult = await svc.analyze_damage(image_bytes, mime)
        if vision.error is None:
            return CVTriageResult(
                damage_type=vision.damage_type or "unknown",
                component=vision.damaged_component,
                severity=vision.damage_severity or "undetermined",
                confidence=vision.visual_confidence,
                plain_english=vision.plain_english_summary,
                provider=vision.provider_used,
                raw_labels=labels,
            )
        # Fall through to keyword fallback on error
        log.warning("Vision LLM failed (%s), falling back to keyword analysis", vision.error)

    # Original keyword-based fallback (lines ~40–85 of current file)
    return self._keyword_analyze(labels, ocr_text)
```

---

## Step 4 — Wire Product Identity Agent into recommend.py

**File:** `src/app/routers/recommend.py`
**Insert after:** the image intake / sanitize block (find the line `sanitized = await sanitize_image(...)`)

When a product image is uploaded on a recommendation request, call `VisionReasoningService.analyze_product()` and inject the extracted specs into `NQEInput.answered_fields` and the product search constraints:

```python
# recommend.py — insert after image sanitization, ~line where image_bytes is available
from src.app.services.vision_reasoning import VisionReasoningService

if image_bytes and intent in ("visual_search", "disambiguate"):
    vision_svc = VisionReasoningService()
    vision_result = await vision_svc.analyze_product(image_bytes, sanitized.get("mime", "image/jpeg"))

    if vision_result.error is None and vision_result.visual_confidence >= 0.6:
        # 1. Inject into NQE answered_fields so NQE skips known facts
        _nqe_answered.update(vision_result.to_nqe_facts())

        # 2. Pre-populate search constraints so catalog search uses these
        extracted = vision_result.extracted_specs
        if extracted.brand and not req.constraints.get("brand"):
            req.constraints["brand"] = extracted.brand
        if extracted.ram_gb and not req.constraints.get("ram_min"):
            req.constraints["ram_min"] = extracted.ram_gb
        if extracted.display_inches and not req.constraints.get("display_size"):
            req.constraints["display_size"] = extracted.display_inches

        # 3. Store in session for future turns
        kv_updates["vision_identified_product"] = {
            "brand": extracted.brand,
            "model": extracted.model_name,
            "specs": vision_result.to_nqe_facts(),
        }

        # 4. Prepend vision summary to the user's effective query
        if vision_result.plain_english_summary:
            effective_query = f"[Identified: {vision_result.plain_english_summary}] {effective_query}"
```

---

## Step 5 — Wire Vision Into the Orchestrator EVALUATE Phase

**File:** `src/app/services/orchestrator.py`
**Class:** `Orchestrator`
**Method to extend:** The EVALUATE phase (search for `# EVALUATE` or the method that scores retrieved candidates)

Add a vision-based reranking signal:

```python
# orchestrator.py — in EVALUATE phase, after retrieval
if ctx.get("vision_identified_product"):
    from src.app.services.vision_reasoning import VisionResult
    identified = ctx["vision_identified_product"]
    for candidate in retrieved_candidates:
        # Boost candidates that match the identified brand/model
        if identified.get("brand") and candidate.get("brand", "").lower() == identified["brand"].lower():
            candidate["_vision_brand_match"] = 0.3   # boost score
        if identified.get("model") and identified["model"].lower() in candidate.get("name", "").lower():
            candidate["_vision_model_match"] = 0.5   # strong boost
```

---

## Step 6 — Add Vision Config to config.py

**File:** `src/app/config.py`
**Add to Settings class:**

```python
# Vision LLM providers (in priority order: openai > gemini > ollama)
OPENAI_API_KEY: Optional[str] = None
GOOGLE_AI_API_KEY: Optional[str] = None
OLLAMA_VISION_MODEL: str = "llava:13b"   # local fallback

# Vision reasoning thresholds
VISION_CONFIDENCE_THRESHOLD: float = 0.6   # min confidence to trust extracted specs
VISION_ENABLED: bool = True                 # kill switch
```

---

## Step 7 — Add LLaVA to docker-compose.yml

**File:** `docker-compose.yml`
**In the `ollama` service (or create one), add:**

```yaml
  ollama:
    image: ollama/ollama:latest
    volumes:
      - ollama_models:/root/.ollama
    environment:
      - OLLAMA_NUM_PARALLEL=2
    deploy:
      resources:
        reservations:
          devices:
            - capabilities: [gpu]   # remove if no GPU
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:11434/api/tags"]
      interval: 30s
      timeout: 10s
      retries: 3

volumes:
  ollama_models:
```

**Pull LLaVA on first boot** (add to your startup script or Dockerfile):
```bash
ollama pull llava:13b
```

---

## Business Outcome

| Before | After |
|--------|-------|
| Upload Lenovo ThinkPad photo → "I see a laptop. What's your budget?" | Upload photo → "This looks like a Lenovo ThinkPad X1 Carbon, 14-inch. I'll search for similar ultrabooks. What's your main use — travel, gaming, or office work?" |
| Damage photo → "Damage detected, severity undetermined" | Damage photo → "There's a crack running across the bottom-left of the display. This is a major physical defect. I've opened a warranty assessment with reference #WC-20260325-0042." |
| Multimodal query routes to 8B model → wrong answers | Multimodal query routes to 70B model → accurate reasoning |
| NQE asks for brand even though brand is visible in photo | NQE skips brand question, jumps to use-case clarification |

---

## Testing Checklist

- [ ] Upload `dump/test-cv/lenovo-pro7.webp` → verify `VisionResult.extracted_specs.brand = "Lenovo"`
- [ ] Upload `dump/test-cv/lenovo-pro7.webp` + query "find me something like this" → verify `visual_similarity=True`, score ≥ 7
- [ ] Upload damage image → verify `damage_type` and `damage_severity` are not `"undetermined"`
- [ ] Upload product image → verify NQE does NOT ask about brand/RAM if already extracted
- [ ] Set `OPENAI_API_KEY=` (empty) → verify fallback to Ollama LLaVA
- [ ] Set `OLLAMA_VISION_MODEL=` (empty) → verify graceful `error="No vision LLM configured"`
