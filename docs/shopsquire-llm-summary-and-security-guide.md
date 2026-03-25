# ShopSquire — LLM Summary, CV Pipeline & Platform Improvement Guide
> **Version:** 2.0 — March 2026
> **Branch:** wip/docker-real-env-20260213
> **Updated by:** Claude Code (claude-sonnet-4-6)

---

## Table of Contents

1. [Is Asking For This Guide a Noob Move?](#1-is-asking-for-this-guide-a-noob-move)
2. [What's Working vs What Isn't — Honest Assessment](#2-whats-working-vs-what-isnt--honest-assessment)
3. [The Robotic Summary Problem — Root Cause & Fix](#3-the-robotic-summary-problem--root-cause--fix)
4. [LLM Summary Architecture — How It Actually Works](#4-llm-summary-architecture--how-it-actually-works)
5. [Prompt Engineering — What Good Looks Like](#5-prompt-engineering--what-good-looks-like)
6. [CV / Visual Search Pipeline — Current Reality](#6-cv--visual-search-pipeline--current-reality)
7. [New MacBook Products — What Was Seeded & Why](#7-new-macbook-products--what-was-seeded--why)
8. [Upsell & Cart Cross-Sell — How to Make It Human](#8-upsell--cart-cross-sell--how-to-make-it-human)
9. [Making ShopSquire Less Robotic — Priority Fixes](#9-making-shopsquire-less-robotic--priority-fixes)
10. [Security Threat Coverage — Current State](#10-security-threat-coverage--current-state)
11. [Sprint Roadmap — What To Build Next](#11-sprint-roadmap--what-to-build-next)

---

## 1. Is Asking For This Guide a Noob Move?

**No — asking "why does my LLM sound like a robot" is exactly the right question.**

A lot of developers build AI platforms and never ask this. They assume "the LLM is talking, so it must sound natural." ShopSquire actually generates summaries via *deterministic template code*, not a live LLM call — which is why it sounds robotic. Recognising that gap and wanting to fix it is the product-thinking that separates a demo from something users actually want to use.

The screenshots you flagged show real, specific problems that can be fixed. None of this is noob — it's observant.

---

## 2. What's Working vs What Isn't — Honest Assessment

### Working well
| Feature | Status | Notes |
|---|---|---|
| QR code detection + security flagging | ✅ Working | Correctly flagged macbook-QR.png |
| PayID / PCI card OCR detection | ✅ Working | Correctly flagged ms-texti.png |
| Multi-contrast deep OCR (CLAHE) | ✅ Working | Finds low-contrast overlaid text |
| Right-band + bottom-band zone scanning | ✅ Working | New zones added in cv_pipeline.py |
| Decision Trace security matrix | ✅ Working | FLAGGED badges render correctly |
| Budget filtering | ✅ Working | Price range logic works |
| Use-case advisor (student/gaming/engineering) | ✅ Working | Injects correct min specs |
| Persona detection from query | ✅ Working | Student/gamer/creative/corporate |
| MSI nearest-match when over budget | ✅ Working | Shows next-best within range |

### Broken or poor
| Feature | Status | Notes |
|---|---|---|
| LLM summary text — robotic raw keys shown | ❌ Fixed (this session) | Was exposing `ram_gb_min:32` to users |
| MacBook recommendation on $700–$1200 budget | ❌ Fixed (this session) | No affordable MacBooks existed in DB |
| Brand extraction from uploaded images | ❌ Needs work | Ollama prompt is damage-triage, not identity |
| Visual similarity search | ❌ Does not exist | No CLIP, no embeddings, no vector DB |
| Copywriting agent actually rewrites text via LLM | ❌ Not enabled | `COPYWRITING_ENABLED=0`, rules-only |
| NQE context memory (repeats same questions) | ❌ Known bug | `previously_asked_ids` not persisted |
| Upsell product-to-persona matching | ⚠️ Partial | SKU family matrix works, no live persona injection |

---

## 3. The Robotic Summary Problem — Root Cause & Fix

### What you saw in screenshots

`no-macbook.png` and `where-macbook-msi.png` both showed per-image summaries like:

> *"Here are some great student-friendly options — I've found 6 matches between $700 and $1,200. Matching specs: ram_gb, min32, storage_gb, min256. Top picks: HP Laptop 15-fc0474AU... (in stock). Good for university general)."*

Three separate problems in one sentence:

### Problem A — Raw internal spec keys exposed
**File:** `src/app/routers/recommend.py` line **2586–2589** (old)

```python
specs = constraints.get("specs") or []
spec_note = ""
if specs:
    spec_note = f" Matching specs: {', '.join(specs)}."
```

`constraints["specs"]` holds internal tokens like `["ram_gb_min:32", "storage_gb_min:256"]`. These were dumped directly into the user-facing string.

**Fix applied this session** — added `_humanize_spec_list()` at line ~2567:
- `"ram_gb_min:32"` → `"32GB RAM"`
- `"storage_gb_min:512"` → `"512GB+ storage"`
- `"gpu_vram_gb_min:8"` → `"8GB GPU"`
- `"refresh_hz_min:144"` → `"144Hz+ display"`

### Problem B — Use-case key exposed raw
`_humanize_positive_factor_tokens()` converts `use_case_match:university_general` to `"Good for university general"` — missing a space between "university" and "general" and including a dangling `)`.

**File:** `src/app/routers/recommend.py` around line **2695–2700**:
```python
elif k in ("use_case_match", "use_case_tag", "use_case_tags"):
    vv = (val or "").replace("_", " ").strip()
    if vv:
        add(f"Good for {vv}")
```

The `_` → space conversion helps but doesn't know `"university_general"` should become `"university use"` not `"university general"`. **To-do:** build a human-readable use-case name map:
```python
_USE_CASE_LABELS = {
    "university_general": "university",
    "gaming_competitive": "competitive gaming",
    "content_creation": "creative work",
    "data_science_student": "data science",
    "engineering_student": "engineering coursework",
    "medical_student": "medical studies",
    # ...
}
```

### Problem C — The LLM is not being called for summaries
**File:** `src/app/routers/recommend.py` around line **2540–2557**

The `_ollama_summary()` function exists and tries to call Ollama, but:
1. It requires Ollama to be running and responsive
2. It's wrapped in resilience/timeout that fails fast
3. When it fails, `_deterministic_assistant_message()` is the fallback

The deterministic fallback is what users are seeing — the template code. The LLM path is mostly unused because Ollama is either not running or times out.

**The fix isn't to force Ollama** — it's to make the deterministic template produce genuinely natural language.

---

## 4. LLM Summary Architecture — How It Actually Works

```
User query + results
       │
       ▼
_ollama_summary()          ← tries LLM first (fails silently when Ollama down)
       │ (on failure)
       ▼
_deterministic_assistant_message()   ← template-based fallback (what users see 90%+ of the time)
       │
       ▼
maybe_apply_copywriting()  ← adds prefix like "Nice pick." if COPYWRITING_ENABLED=1
       │
       ▼
User sees the message
```

### The deterministic template builds:

```
{opening}I've {core}.{spec_note}{why_note}{urgency_note}{closing}
```

Where:
- `opening` = persona phrase ("Here are some great student-friendly options — ")
- `core` = "found N matches between $X and $Y"
- `spec_note` = **WAS** raw internal keys, **NOW** humanized (16GB RAM, 512GB+ storage)
- `why_note` = "Top picks: [ProductName] (In stock, Good for university)"
- `urgency_note` = stock/dispatch note
- `closing` = "Want a detailed list or comparison?"

### The copywriting service
**File:** `src/app/services/copywriting.py`

Currently **disabled** (`COPYWRITING_ENABLED=0`). When enabled, it applies deterministic prefix rules ("Nice pick.", "Curated for quality.") — it does NOT call an LLM. It's a string preprocessor.

To enable: set `COPYWRITING_ENABLED=1` in environment. Profiles available: `balanced`, `premium`, `playful`, `technical`.

---

## 5. Prompt Engineering — What Good Looks Like

### Current Ollama summary prompt (when it does fire)

Not visible in the public codebase — needs to be checked in `_ollama_summary()` at `recommend.py:~2520`. If it's sending a raw product list without persona context, that's why even the LLM output sounds mechanical.

### What a good summary prompt looks like

```python
SUMMARY_PROMPT = """You are a friendly, knowledgeable tech sales assistant.
A customer asked: "{query}"
Their profile: {persona_desc}
Budget: {budget}
Top matching products: {product_list}

Write a 2-3 sentence natural response that:
- Sounds like a helpful human, not a spec sheet
- Names 1-2 specific products and WHY they fit this person
- Ends with ONE focused follow-up question
- Never uses technical internal codes like ram_gb_min or use_case_match
- Keep it under 100 words"""
```

### Per-image visual search summary (what's broken in screenshots)

When two images are uploaded, each gets the same generic student-laptop summary. This happens because:
1. The brand isn't extracted from the image (CV pipeline gap)
2. Both images fall back to the same text-query results
3. The per-image summary has no image-specific context

With the cv_provider.py `mode="visual_search"` fix already applied, the Ollama prompt will now ask for brand/model. Once that feeds into recommendations, per-image summaries should say: *"Your MacBook image suggests you're comfortable with macOS. Here are the best macOS options in your budget..."*

---

## 6. CV / Visual Search Pipeline — Current Reality

> Full technical analysis: `docs/CV_VISUAL_SEARCH_ANALYSIS_2026.md`

### Pipeline summary (as of March 2026, post-fixes)

```
Image upload
    │
    ├── Security path (always runs):
    │     QR decode → PayID/PCI OCR → Steg detection → adversarial detection
    │
    └── Product identity path (NEW — mode="visual_search"):
          Ollama vision LLM → {brand, model, category, labels}
          Filename hint → appended as weak label
          Brand→constraint injection in recommend.py
```

### What's still missing

| Gap | Impact | Effort to fix |
|---|---|---|
| CLIP visual embeddings | Can't do true "show me similar products" | High — needs pgvector setup |
| Brand lookup table expansion | MSI/Asus/HP/Acer not inferred from labels | Low — 30 lines in recommend.py |
| `_BRAND_LABEL_PATTERNS` dict in recommend.py | Only macbook/thinkpad/xps checked | Low — edit lines 4544–4557 |
| Filename-brand cross-validation | Filename spoofing undetected | Medium — new `filename_brand_validator.py` |
| Product_Identity_Agent | No vision-to-spec constraint pipeline | Medium — needs orchestrator wiring |

---

## 7. New MacBook Products — What Was Seeded & Why

### Products added (March 2026)

| Product | SKU | Price | Why added |
|---|---|---|---|
| MacBook Neo 13" A18 Pro 256GB Indigo | `APPLE-NEOAIR13-A18-256-INDIGO` | $899 | Budget Apple entry point |
| MacBook Neo 13" A18 Pro 256GB Silver | `APPLE-NEOAIR13-A18-256-SILVER` | $899 | Same specs, different colour |
| MacBook Neo 13" A18 Pro 512GB Blush | `APPLE-NEOAIR13-A18-512-BLUSH` | $1,099 | Storage upgrade option |
| MacBook Air 13" M5 512GB/16GB Midnight | `APPLE-AIRM5-13-512-MIDNIGHT` | $1,799 | Premium ultrabook tier |

### Before vs After Apple price ladder

| Before | After |
|---|---|
| iPad $499 | iPad $499 |
| iPad Air $1,347 | **MacBook Neo $899** ← new |
| MacBook Pro $2,887 | **MacBook Neo $1,099** ← new |
| MacBook Pro $3,099 | iPad Air $1,347 |
| MacBook Pro $3,899 | **MacBook Air M5 $1,799** ← new |
| | MacBook Pro $2,887 |

### Effect on recommendations

When a user says *"I want a MacBook for university, budget $1,200"*:
- **Before:** "We don't currently stock MacBooks in your range, here are Windows alternatives"
- **After:** Shows MacBook Neo $899 and $1,099 — actual MacBooks within budget

The `strict_image_brand_hint = "apple"` path in recommend.py now has products to return instead of falling back to Windows alternatives.

---

## 8. Upsell & Cart Cross-Sell — How to Make It Human

### Current state
**File:** `src/app/services/checkout_upsell.py`

The upsell engine has a solid foundation:
- SKU family matrix (LAP → PERIPH/BAG/MON/HEAD at 0.75–0.95 weight)
- Transaction history affinity (180-day lookback)
- `_infer_intent_family()` reads query + persona + use_case

But it has two gaps that make upsells feel generic:

### Gap 1 — No persona-specific product selection

The upsell candidates come from the same catalog regardless of persona. A student buying a $899 MacBook Neo and a gamer buying an MSI GT76 get offered similar accessories.

**What it should do:**

| Persona | Primary product | Upsell suggestions |
|---|---|---|
| Student | MacBook Neo $899 | Thule laptop sleeve $179, Samsung portable SSD $169, noise-cancelling headphones |
| Gamer | MSI GT76 | Curved gaming monitor, gaming headset, gaming mouse |
| Corporate | ThinkPad | Docking station, external monitor, carrying brief |
| Creative | MacBook Pro M4 | External SSD, portable monitor, drawing tablet |

**File to edit:** `src/app/services/checkout_upsell.py` — add a `_persona_upsell_weights()` function that applies multipliers to candidate scores based on persona+category match:

```python
_PERSONA_CATEGORY_WEIGHTS = {
    "student":    {"BAG": 1.4, "PERIPH": 1.2, "MON": 0.6, "HEAD": 1.1},
    "gamer":      {"MON": 1.5, "HEAD": 1.4, "PERIPH": 1.3, "BAG": 0.7},
    "corporate":  {"MON": 1.4, "BAG": 1.2, "PERIPH": 1.1, "HEAD": 0.8},
    "creative":   {"MON": 1.3, "PERIPH": 1.2, "BAG": 1.1, "HEAD": 0.9},
    "traveler":   {"BAG": 1.6, "PERIPH": 0.8, "MON": 0.5},
}
```

### Gap 2 — Upsell text is the same for everyone

The upsell message doesn't reference the primary product or explain why the bundle makes sense.

**What's bad:**
> *"You might also like: Lenovo Legion Backpack $199"*

**What's good:**
> *"Students love pairing the MacBook Neo with the Thule sleeve — keeps it safe in a busy campus bag, and it's only $179."*

**File to edit:** `src/app/services/checkout_upsell.py` — add a `_upsell_reason_string()` function:

```python
def _upsell_reason_string(primary_name: str, upsell_name: str, persona: str, category: str) -> str:
    if persona == "student" and category == "BAG":
        return f"Perfect for protecting your {primary_name} on campus."
    if persona == "gamer" and category == "MON":
        return f"Unlock your {primary_name}'s full potential with a dedicated gaming monitor."
    if category == "BAG":
        return f"Keep your {primary_name} safe on the go."
    return f"Great companion for your {primary_name}."
```

### Gap 3 — Non-laptop products not linked to user persona

Currently the upsell only fires when a laptop is in the cart (LAP family). A user browsing tablets, headsets, or monitors gets no cross-sell.

**Add to `_infer_intent_family()`:**
```python
if any(t in text for t in ("tablet", "ipad", "samsung tab")):
    return "TAB"
if any(t in text for t in ("monitor", "screen", "display")):
    return "MON"
if any(t in text for t in ("headset", "headphone", "earphone")):
    return "HEAD"
```

Then expand `_family_complement_weight()` matrix to include TAB → [BAG, PERIPH, HEAD] and MON → [PERIPH, LAP].

---

## 9. Making ShopSquire Less Robotic — Priority Fixes

### Immediate (already done this session)
- [x] `_humanize_spec_list()` — spec tokens now show as "16GB RAM" not "ram_gb_min:16"
- [x] 4 affordable MacBooks seeded ($899–$1,799)
- [x] `cv_provider.py` dual-mode Ollama prompt (damage vs product identity)
- [x] `cv_pipeline.py` right-band + sliding-window zone scanning
- [x] Filename hint always appended as weak label
- [x] Product identity decoupled from security flag

### High impact, low effort
| Fix | File | Effort | User impact |
|---|---|---|---|
| Use-case name map (stop showing "university general") | `recommend.py:~2695` | 2h | High |
| Brand lookup table expansion (MSI, Asus ROG, HP, Acer) | `recommend.py:4544–4557` | 1h | High |
| Enable copywriting with `playful` profile for students | `.env / feature_flags.json` | 30min | Medium |
| Upsell persona multipliers | `checkout_upsell.py` | 4h | High |
| NQE previously_asked_ids persistence fix | `flows/nqe.py`, `routers/recommend.py` | 3h | Very High |

### Medium effort, high payoff
| Fix | File | Effort |
|---|---|---|
| LLM summary Ollama prompt quality (send persona+query context) | `recommend.py:~2520` | 4h |
| Per-image visual search context — use brand_hint from vision | `recommend.py:4544+` | 4h |
| `filename_brand_validator.py` — spoof detection | new file | 3h |
| Upsell reason strings per persona+category | `checkout_upsell.py` | 3h |

### Longer term
| Fix | Effort | Value |
|---|---|---|
| CLIP embeddings + pgvector visual similarity | 2 weeks | Transforms visual search |
| Ollama always-on in Docker (dependency health) | 1 day | Makes LLM summaries reliable |
| WebSocket streaming for Decision Trace | 1 week | Much better UX |
| Human escalation room completion | 1 week | Enterprise requirement |

---

## 10. Security Threat Coverage — Current State

### Detectors active (as of March 2026)

| Threat | Detector | File | Status |
|---|---|---|---|
| QR code injection | `barcode_decode.py` | `src/app/rules/barcode_decode.py` | ✅ Working |
| PayID / card overlay | OCR + regex patterns | `src/app/security/image_threat_signals.py` | ✅ Working |
| Low-contrast text (invisible text attack) | Multi-contrast OCR, CLAHE | `cv_pipeline.py` | ✅ Working |
| Right-side/trackpad zone injection | Right-band crop (NEW) | `cv_pipeline.py:284–293` | ✅ Just added |
| Steganography (LSB/DCT) | `steg_detector.py` | `src/app/security/steg_detector.py` | ✅ Working |
| Adversarial image attack | `adversarial_image_detector.py` | `src/app/security/adversarial_image_detector.py` | ✅ Working |
| Filename brand spoofing | `filename_brand_validator.py` | `src/app/services/` | ⚠️ Partially in vision.py |
| GAN/AI-generated image | `adversarial_image_detector.py` | `src/app/security/adversarial_image_detector.py` | ✅ Score available |
| Prompt injection via QR payload | `_detect_ocr_prompt_injection()` | `vision.py:187–193` | ✅ Working |

### OWASP LLM Top 10 2025 — Current Coverage

| OWASP ID | Threat | Coverage |
|---|---|---|
| LLM01 | Prompt Injection | ✅ QR injection, OCR injection detection |
| LLM02 | Insecure Output Handling | ⚠️ Post-LLM verifier exists, not always wired |
| LLM03 | Training Data Poisoning | ❌ No coverage |
| LLM04 | Model DoS | ✅ Token budget + rate limiting |
| LLM05 | Supply Chain Vulnerabilities | ⚠️ Supply chain harness partial |
| LLM06 | Sensitive Information Disclosure | ✅ PII scrubbing in deps.py |
| LLM07 | Insecure Plugin Design | ✅ Policy gate on agent actions |
| LLM08 | Excessive Agency | ✅ Policy gate + approval workflow |
| LLM09 | Overreliance | ⚠️ No user-facing confidence caveat |
| LLM10 | Model Theft | ✅ `model_theft.py` rate limit + watermarking |

### MITRE ATLAS — Key mappings

| ATLAS Technique | Maps to ShopSquire | Status |
|---|---|---|
| AML.T0051 — LLM Prompt Injection | Image-embedded prompts | ✅ Detected |
| AML.T0054 — Membership Inference | Catalog probing via recommend | ✅ `model_theft.py` |
| AML.T0048 — Societal Harm | PayID social engineering | ✅ Detected |
| AML.T0040 — ML Supply Chain | Dependency analysis | ⚠️ Partial |
| Context poisoning (Oct 2025 addition) | Redis session manipulation | ❌ Not implemented |
| Memory manipulation (Oct 2025 addition) | `session:{uid}:kv_state` poisoning | ❌ Not implemented |

---

## 11. Sprint Roadmap — What To Build Next

### Sprint 1 (this week — quick wins)
- [ ] Use-case name label map (`recommend.py`)
- [ ] Brand lookup table expansion (`recommend.py:4544–4557`)
- [ ] Enable copywriting for student persona
- [ ] NQE `previously_asked_ids` persistence fix

### Sprint 2 (next week — upsell + summary quality)
- [ ] Persona-aware upsell multipliers (`checkout_upsell.py`)
- [ ] Upsell reason strings per persona+category
- [ ] Non-laptop SKU families (TAB, HEAD, MON) for upsell
- [ ] LLM summary Ollama prompt with persona context

### Sprint 3 (2 weeks — visual search)
- [ ] `_BRAND_LABEL_PATTERNS` full brand list in `recommend.py`
- [ ] `filename_brand_validator.py` — spoof detection + security signal
- [ ] Product_Identity_Agent wiring (vision → specs → constraints)

### Sprint 4 (1 month — embedding-based visual search)
- [ ] CLIP embeddings via `transformers` (no Ollama needed)
- [ ] pgvector product image catalog indexing
- [ ] ANN query on upload → visual similarity top-K

---

## Key File Reference

| File | Purpose | Key issues |
|---|---|---|
| `src/app/routers/recommend.py` | Main recommendation orchestrator | Spec humanization (fixed), brand labels (todo), summary template |
| `src/app/services/cv_provider.py` | Vision LLM wrapper | Dual-mode prompt (fixed) |
| `src/app/cv/cv_pipeline.py` | OCR + multi-contrast deep scan | Right-band zone (fixed) |
| `src/app/routers/vision.py` | Image upload + security scan | Product identity decoupled (fixed) |
| `src/app/services/checkout_upsell.py` | Cart upsell engine | Needs persona multipliers |
| `src/app/services/copywriting.py` | Summary post-processing | Disabled — enable for persona tone |
| `src/app/flows/nqe.py` | Next Question Engine | Context loss bug (BUG-1) |
| `src/app/services/image_intent_router.py` | Routes upload to visual_search vs triage | Works, narrow brand signals |
