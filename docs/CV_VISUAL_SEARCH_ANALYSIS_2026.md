# CV & Visual Search Pipeline — Analysis & Fix Roadmap
**Date:** 2026-03-12
**Branch:** wip/docker-real-env-20260213
**Prepared by:** Claude Code (claude-sonnet-4-6)

---

## 1. What the Screenshots Show

### `dump/where-macbook-msi.png`
Two images uploaded (`macbook-QR.png`, `ms-texti.png`) with query: *"which laptops to get for university? can I get one for 1200?"*

**Expected:** MacBook and/or MSI recommended or at least considered.
**Actual:** Generic AMD Ryzen HP/Lenovo/Dell laptops returned. Neither uploaded brand appears in results.

### `dump/no-steg-msi.png`
Decision Trace → Security Matrix tab:
- `macbook-QR.png` → **FLAGGED** — QR code detected, external URL (Wikipedia), `qr_external_url_detected = True`
- `ms-texti.png` → **FLAGGED** — PayID social engineering text, card numbers (`PayID: 0450 123 456 $1500 '5481 1224 0987 4321 09/30 123'`)
- Steganography: **not triggered** on MSI image — correct behaviour (explained below)

---

## 2. Why MacBook and MSI Are Not Recommended

### 2a. Both images are security-flagged before brand extraction runs

**File:** `src/app/routers/vision.py`

| Lines | Behaviour |
|---|---|
| 166–210 | `decode_barcodes()` → QR found in macbook image → `security_clean = False` |
| 283–322 | OCR normalization → PayID/PCI card pattern in MSI image → `payment_social_engineering = True` → `security_clean = False` |
| 324–340 | `resp["security"]["reupload_needed"] = True` — image treated as threat, not a product |

Once `security_clean = False`, neither image's labels are passed to the recommendation pathway with product-search intent. The chat falls back to the **text query alone** ("laptops for university, $1200") and returns generic results.

### 2b. Brand inference from image labels is extremely narrow

**File:** `src/app/routers/recommend.py`, lines **4544–4557**

```python
img_labels_low = [str(x).lower() for x in (image_context.get("labels") or [])]
inferred_brand = None
if any("macbook" in t for t in img_labels_low):
    inferred_brand = "apple"
elif any("thinkpad" in t for t in img_labels_low):
    inferred_brand = "lenovo"
elif any("xps" in t for t in img_labels_low):
    inferred_brand = "dell"
```

**Missing brands:** MSI, Asus ROG, HP, Acer, Surface, Razer, Gigabyte, Samsung, Toshiba.
Even if "msi" appeared in labels, it would fall through to `strict_image_brand_hint = "windows"` (line 4557) — a generic fallback, not MSI-specific.

### 2c. The Ollama vision prompt is a damage-triage prompt, not a product-identity prompt

**File:** `src/app/services/cv_provider.py`, lines **67–71**

```python
prompt = (
    "You are an e-commerce vision assistant. Analyze the provided image and "
    "return a compact JSON object with keys 'labels' (array of lowercase keywords) "
    "and 'text' (any visible serial/receipt text snippets). Use laptop-related labels like "
    "screen, crack, hinge, keyboard, charger when relevant. ..."
)
```

The model (llava/qwen/llava-latest) is instructed to return damage-triage labels like `["screen", "crack", "hinge"]`. It is **never asked** to identify brand, model, generation, or product category for purchase intent.

**Result:** llava returns `["laptop", "keyboard"]` for a MacBook and `["laptop", "keyboard"]` for an MSI. No brand differentiation. The recommendation engine sees identical evidence for both images.

### 2d. Filename fallback exists but only fires on empty labels

**File:** `src/app/routers/vision.py`, lines **122–123**

```python
if not labels and name:
    labels = [name]   # e.g. "macbook-QR.png" → label = "macbook-QR.png"
```

- Only triggers when Ollama returns **zero labels**.
- If Ollama returns even `["laptop"]`, the filename is discarded.
- If it does fire, `"macbook" in "macbook-qr.png"` is `True` — substring match works — but this is accidental, not designed.

### 2e. No visual similarity / embedding search exists

There is no CLIP embedding, no product image vector database, no ANN/FAISS search. "Visual search" in ShopSquire is purely: *label text keywords → brand keyword match → filter catalog by brand*. It is not visual similarity in any meaningful sense.

---

## 3. Why Steganography Did Not Fire on the MSI Image

**File:** `src/app/routers/vision.py`, lines **271–281**
**File:** `src/app/security/steg_detector.py`

The barely-visible white text at the bottom of `ms-texti.png` ("PayID: 0450...") is **not steganography**. It is low-contrast visible text — it exists in the image's visible pixel layer, just with near-background luminance.

- Steg detection looks for data hidden in **pixel LSBs** (Least Significant Bit manipulation), DCT coefficient anomalies (JPEG), or palette irregularities.
- Multi-contrast OCR (CLAHE + adaptive threshold, `cv_pipeline.py` lines **247–276**) correctly reads this text because contrast enhancement makes it visible.
- `invisible_text_suspected` flag (line **292–295**) would fire if base OCR returns < 6 chars but enhanced OCR returns ≥ 16 chars. This is the correct detection path for that class of attack.

**The "hidden" text on the right of the trackpad:** If it's truly not visible under any contrast enhancement pass, it may be in the mouse/cursor overlay region clipped by the screenshot tool, or genuinely outside the visible spectrum (e.g., UV-marker, which no software steg detector can find). If it's a very dark area, the bottom-band crop (lines **224–239**, targeting the lower 38% of the image) should find it.

**Verdict:** The steg non-detection is correct. The OCR-based PayID detection is the right path and it worked.

---

## 4. Filename Spoofing as an Attack Vector

If a file is named `macbook-air.jpg` but contains an MSI gaming laptop or iPad:

1. Ollama returns generic labels `["laptop"]`
2. Filename fallback doesn't fire (labels not empty)
3. Alternatively if Ollama fails → labels = `["macbook-air.jpg"]` → brand inferred as Apple
4. Recommendations anchor to Apple products for a non-Apple image
5. **No cross-validation** between filename hint and image content exists anywhere in the pipeline

This is a form of **data integrity attack** against the recommendation engine. A bad actor could upload a competitor's product image with a misleading filename to bias results.

---

## 5. How Other Platforms Handle This

| Platform | Approach | Stack |
|---|---|---|
| **Google Lens / Shopping** | CLIP/ViT image embedding → ANN search (ScaNN) against billions of product images | Proprietary Vision API + FAISS/ScaNN |
| **Amazon Visual Search** | Rekognition product search + separate logo detection + OCR pass for model numbers | AWS Rekognition custom models |
| **Pinterest Lens** | Visual embedding → indexed catalog + brand classifier | Internal PyTorch |
| **Shopify** | No native visual search — third-party apps (Visenze, Google Vision Product Search) | Third-party |
| **Magento** | None built-in | — |

**Industry standard pipeline:**
1. Vision LLM or CLIP → image embedding (product identity, not damage triage)
2. ANN/vector search against pre-embedded product catalog
3. Separate logo detection pass for brand identification
4. Separate OCR pass for model numbers, serial numbers
5. Filename is metadata only — never trusted as ground truth

---

## 6. Files to Edit / Replace

### Priority 1 — Fix Ollama prompt for product identity

**File:** `src/app/services/cv_provider.py`
**Lines:** 67–71 (the `prompt` string)

**Current (damage triage):**
```python
prompt = (
    "You are an e-commerce vision assistant. Analyze the provided image and "
    "return a compact JSON object with keys 'labels' (array of lowercase keywords) "
    "and 'text' (any visible serial/receipt text snippets). Use laptop-related labels like "
    "screen, crack, hinge, keyboard, charger when relevant. ..."
)
```

**Replace with a dual-mode prompt.** The prompt should be chosen based on context:
- **Damage triage context** → existing prompt (keep as-is)
- **Visual search / product identity context** → new prompt:

```python
PRODUCT_IDENTITY_PROMPT = (
    "You are a product identification assistant for an e-commerce platform. "
    "Analyze the provided image and return a compact JSON object with keys: "
    "'brand' (brand name, e.g. Apple, MSI, Lenovo, Dell, HP, Asus, Acer, Samsung, Microsoft, Razer), "
    "'model' (model name or series if visible, e.g. MacBook Pro 16, MSI GT76, ThinkPad X1 Carbon), "
    "'category' (e.g. laptop, gaming_laptop, ultrabook, tablet, phone, desktop), "
    "'labels' (array of 3-8 lowercase product descriptor keywords, e.g. [\"gaming\", \"rgb_keyboard\", \"large_screen\"]), "
    "'text' (any visible model numbers, serial numbers, or spec text). "
    "If you cannot determine a field, use null. "
    "Example: {\"brand\":\"MSI\",\"model\":\"GT76\",\"category\":\"gaming_laptop\","
    "\"labels\":[\"gaming\",\"rgb_keyboard\",\"dragon_logo\"],\"text\":\"GT76 10SF\"}."
)
```

**Also change `get_labels_and_text` signature** to accept a `mode: str = "triage"` parameter and select prompt accordingly. Pass `mode="visual_search"` from the vision router when intent is product search.

---

### Priority 2 — Expand brand inference keyword list

**File:** `src/app/routers/recommend.py`
**Lines:** 4544–4557

**Current — only 3 brands:**
```python
if any("macbook" in t for t in img_labels_low):
    inferred_brand = "apple"
elif any("thinkpad" in t for t in img_labels_low):
    inferred_brand = "lenovo"
elif any("xps" in t for t in img_labels_low):
    inferred_brand = "dell"
```

**Replace with a lookup table covering all major brands:**
```python
_BRAND_LABEL_PATTERNS = {
    "apple":     ["macbook", "imac", "mac mini", "mac pro", "apple"],
    "lenovo":    ["thinkpad", "ideapad", "legion", "yoga", "lenovo"],
    "dell":      ["xps", "inspiron", "alienware", "latitude", "dell"],
    "hp":        ["spectre", "envy", "omen", "elitebook", "probook", "hp laptop", "hp"],
    "asus":      ["rog", "zenbook", "vivobook", "asus"],
    "acer":      ["predator", "aspire", "swift", "nitro", "acer"],
    "msi":       ["msi", "dragon logo", "stealth", "raider", "titan", "creator"],
    "razer":     ["razer", "blade"],
    "microsoft": ["surface", "surface pro", "surface laptop"],
    "samsung":   ["galaxy book", "samsung"],
    "gigabyte":  ["aorus", "gigabyte"],
    "toshiba":   ["dynabook", "toshiba"],
}

inferred_brand = None
for brand, patterns in _BRAND_LABEL_PATTERNS.items():
    if any(any(pat in t for pat in patterns) for t in img_labels_low):
        inferred_brand = brand
        break
```

This also needs the `strict_image_brand_hint` logic (lines 4554–4557) updated so MSI/Asus/Razer etc. set `"windows"` and Apple sets `"apple"`.

---

### Priority 3 — Use filename as a weak signal, not ignored

**File:** `src/app/routers/vision.py`
**Lines:** 122–123

**Current (all-or-nothing):**
```python
if not labels and name:
    labels = [name]
```

**Replace with:** Always append the filename as a low-weight extra signal, but mark it as untrusted:
```python
# Always inject filename as a weak hint (will be labelled "filename_hint" so
# downstream can apply lower weight / cross-validate against vision output)
if name:
    fname_hint = os.path.splitext(str(name).lower())[0].replace("-", " ").replace("_", " ")
    if fname_hint and fname_hint not in " ".join(labels).lower():
        labels = (labels or []) + [fname_hint]   # append, don't replace
```

Then in `recommend.py`, when using `image_context["labels"]`, the last label can be identified as filename-origin and given reduced weight, or flagged if it conflicts with the vision-model labels.

---

### Priority 4 — Don't discard image context when security flagged for QR/text

**File:** `src/app/routers/vision.py`
**Lines:** 324–340, 147–157

**Current problem:** When `security_clean = False`, the `is_product_photo` flag becomes `False` (line 47–54: `_is_product_photo` returns `False` if `damage_score > 0.4`, and security flags inflate effective damage score). The image intent routes to `"cv_triage"` or `"disambiguate"` instead of `"visual_search"`.

**Proposed fix:** Separate the security flag from the product identity extraction. Even a flagged image can still carry brand/model information:

```python
# Extract product identity BEFORE security gating
# Security flags should warn the user, but not prevent brand/model extraction
# for recommendation purposes — the QR payload might even HELP (manufacturer URL)
resp["product_identity_from_image"] = {
    "brand": None,    # to be filled by vision model with PRODUCT_IDENTITY_PROMPT
    "model": None,
    "category": None,
}
```

This is the **Product_Identity_Agent** gap noted in the architecture roadmap.

---

### Priority 5 — Add cross-validation: filename vs vision output

**New file to create:** `src/app/services/filename_brand_validator.py`

```python
"""
Cross-validate filename brand hints against vision model output.
Raises a mismatch signal if they conflict (potential filename spoofing).
"""
from typing import Optional, List

_BRAND_KEYWORDS = {
    "apple": ["macbook", "mac", "imac", "apple"],
    "msi": ["msi"],
    "lenovo": ["lenovo", "thinkpad", "ideapad", "legion"],
    # ... etc
}

def extract_brand_from_filename(filename: str) -> Optional[str]:
    """Return brand slug if filename contains a known brand keyword."""
    fn = filename.lower().replace("-", " ").replace("_", " ")
    for brand, keywords in _BRAND_KEYWORDS.items():
        if any(kw in fn for kw in keywords):
            return brand
    return None

def validate_filename_vs_labels(filename: str, vision_labels: List[str]) -> dict:
    """
    Returns {"match": True/False/None, "filename_brand": ..., "vision_brand": ..., "mismatch": bool}
    None = could not determine (filename or labels too generic)
    """
    fn_brand = extract_brand_from_filename(filename)
    vision_text = " ".join(vision_labels).lower()
    vision_brand = None
    for brand, keywords in _BRAND_KEYWORDS.items():
        if any(kw in vision_text for kw in keywords):
            vision_brand = brand
            break
    mismatch = bool(fn_brand and vision_brand and fn_brand != vision_brand)
    return {
        "filename_brand": fn_brand,
        "vision_brand": vision_brand,
        "match": (fn_brand == vision_brand) if (fn_brand and vision_brand) else None,
        "mismatch": mismatch,
    }
```

Call this from `vision.py` after label extraction. If `mismatch=True`, add `security_signals["filename_brand_mismatch"] = True`.

---

## 7. Longer-Term: Real Visual Similarity Search

The current pipeline has **no visual embedding or ANN search**. Adding this properly requires:

1. **Embed all product catalog images** using CLIP (`openai/clip-vit-base-patch32` via `transformers`) → store in pgvector (PostgreSQL extension already available via Docker)
2. **On upload:** encode query image → cosine ANN search → return top-K SKUs
3. **Brand confirmation:** run brand classifier (fine-tuned CLIP or lightweight ResNet) to confirm brand from pixels, independent of filename

**Files that would need to be created:**
- `src/app/services/product_image_embedder.py` — batch embed catalog images into pgvector
- `src/app/services/visual_similarity_search.py` — query embedding + ANN retrieval
- `src/app/routers/recommend.py` — add visual similarity results as a ranked signal in the orchestrator

**Model options (Ollama-compatible, self-hosted):**
- `llava:13b` or `qwen2.5vl:7b` for product identity (brand/model extraction)
- CLIP via `transformers` for embeddings (no Ollama needed, pure Python)
- `moondream2` — lightweight 1.8B vision model, fast for brand/category classification

---

## 8. Summary Table

| Issue | File | Lines | Fix Type |
|---|---|---|---|
| Ollama prompt is damage-triage not product-identity | `src/app/services/cv_provider.py` | 67–71 | Edit prompt, add mode param |
| Brand inference misses MSI, Asus, HP, Acer, Razer etc. | `src/app/routers/recommend.py` | 4544–4557 | Replace with lookup table |
| Filename discarded when Ollama returns any label | `src/app/routers/vision.py` | 122–123 | Append filename hint always |
| Security flag prevents product identity extraction | `src/app/routers/vision.py` | 47–54, 147–157 | Decouple security from identity |
| Filename spoofing — no validation | `src/app/services/` | — | New file: `filename_brand_validator.py` |
| No visual similarity / embedding search | `src/app/services/` | — | New service: `visual_similarity_search.py` |
| MSI not in `_BRAND_LABEL_PATTERNS` anywhere | `src/app/routers/recommend.py` | 4546–4585 | Add MSI, Razer, Gigabyte etc. |
| Steg detector not finding MSI text | `src/app/security/steg_detector.py` | — | Not a bug — use OCR path instead |

---

## 9. What Is Working Correctly

- QR decode + external URL detection (`macbook-QR.png` → Wikipedia URL flagged) ✓
- PayID / PCI card pattern OCR detection (`ms-texti.png`) ✓
- Multi-contrast deep OCR (CLAHE + adaptive threshold) for low-contrast text ✓
- Steg detector correctly *not* firing on visible-but-low-contrast text ✓
- `invisible_text_suspected` flag logic in `cv_pipeline.py` lines 292–295 ✓
- Bottom-band ROI crop targeting lower 38% of image for overlay text ✓
- Security Matrix in Decision Trace rendering FLAGGED badges correctly ✓
