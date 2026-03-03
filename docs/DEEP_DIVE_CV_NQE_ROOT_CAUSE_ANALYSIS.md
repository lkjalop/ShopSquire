# ShopSquire — Deep Dive Root Cause Analysis
## CV Security Matrix + NQE Repeated Questions
**Date:** 2026-03-02 | **Branch:** wip/docker-real-env-20260213

---

## TL;DR: Blame List

| # | Blame | Severity | File | Lines |
|---|-------|----------|------|-------|
| 1 | Image CV signals never fed into security matrix | **CRITICAL** | `routers/chat.py` | ~319 |
| 2 | `detect_steganography()` never called on uploaded images | **HIGH** | `routers/vision.py` | ~134-223 |
| 3 | CV Playbook never fires from chat path | **HIGH** | `routers/cv.py` | ~350-387 |
| 4 | QR/adversarial → MITRE/OWASP mapping missing | **HIGH** | `security/observer.py` | `analyze_payload()` |
| 5 | Budget from text query not in NQE `answered_fields` | **HIGH** | `routers/recommend.py` | ~3552, ~5215 |
| 6 | `ask_university_subject` not in NQE cap keep-list | **MEDIUM** | `flows/nqe.py` | ~589 |
| 7 | `imagehash` missing from environment | **MEDIUM** | `pyproject.toml` | — |

---

## PART 1 — WHY THE SECURITY MATRIX SHOWS NOTHING

### 1.1 The Decision Trace Security Tab: What It Actually Shows

The Security tab in Decision Trace reads from `observer.analyze_payload()`. This function:
- Scans **text content only** (query string, OCR text)
- Returns DREAD, CVSS, PASTA Stage, OWASP LLM, STRIDE, MITRE ATLAS entries based on **regex/pattern matching against text**
- A MacBook photo upload with query "is there any macbooks around $600?" → score ~4.8 DREAD, 0.2 CVSS because the text itself has no injection/attack patterns
- **The image security signals (QR detected, adversarial score, steg flags) are a completely separate dict that NEVER reaches `analyze_payload()`**

### 1.2 The Actual Flow When You Upload an Image in Chat

```
Frontend
  ↓ POST /api/v1/vision/triage   ← image bytes (multipart)
  ↓ returns: {labels, extracted_text, security: {qr_code_detected, adversarial_score, ...}}

Frontend sends to:
  ↓ POST /api/v1/chat  ← imageTriageResults embedded in payload.images[]

chat.py extracts image signals → image_cv_signals_in dict
  ↓ line 319: analyze_payload({"query": merged_text}) ← *** ONLY TEXT ***
  ↓ image_cv_signals_in is NEVER passed to analyze_payload()
  ↓ observer fires on text → "macbooks around $600" → no patterns → empty matrix

image_cv_signals_in gets forwarded to recommend.py
  ↓ appears in final cv_signals output
  ↓ shows in Decision Trace Events tab only as raw payload
  ↓ NEVER mapped to MITRE ATLAS / OWASP / STRIDE framework fields
```

**The security matrix fields are empty because nobody maps `{qr_code_detected: true, adversarial_score: 0.3}` to MITRE ATLAS technique IDs, OWASP categories, or STRIDE threats.**

### 1.3 Why QR Codes on macbook-QR.png Are Not Flagged

**Step 1 — Does the triage endpoint even run?**

`vision.py:72` requires `require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER])`.
Frontend sends `x-api-key: VITE_API_KEY` (`App.tsx:600`).
`VITE_API_KEY` is a Vite build-time env var read from `.env`. Default backend key is `"local-merchant-key"` (`MERCHANT_API_KEY` env var).

**If `.env` in the frontend directory has `VITE_API_KEY=local-merchant-key` → auth passes.**
**If not set → `fetch` gets 401 → `r.ok` is false → `return null` → `imageTriageResults = []` → NO TRIAGE RUNS AT ALL.**

This is the most likely reason the QR code is not flagged: silent 401 on `/api/v1/vision/triage`.

**Step 2 — Ollama vision provider may not be reachable locally**

`.env` has:
```
CV_PROVIDER=ollama
OLLAMA_URL=http://host.docker.internal:11434
```

`host.docker.internal` resolves inside Docker containers to the host. When running locally outside Docker, this URL fails. The fallback is Tesseract (`cv_provider.py:48`), which gives text only, no labels. Labels are empty, so CV triage sees nothing.

**Step 3 — QR decode runs independent of OCR, but output is silently swallowed**

`vision.py:139-212`: QR decode via pyzbar/OpenCV runs on raw image bytes regardless of OCR provider. This DOES work locally (pyzbar and cv2 are installed). If `macbook-QR.png` has a decodeable QR code and auth passes, pyzbar SHOULD find it.

**Step 4 — Even when QR IS detected, the security matrix stays empty**

The triage result `security: {qr_code_detected: true, reupload_needed: true}` flows into `image_cv_signals_in` in chat.py. But `analyze_payload()` at line 319 only gets `{"query": merged_text}`. The QR detection flag is NOT in that dict.

Result in Decision Trace Security tab: **"No CV playbook recorded for this trace"** — correct, because CV Playbooks only fire from the `/api/v1/cv/analyze` endpoint (the explicit complaint/return flow in `cv.py:350-387`), not from the chat endpoint.

### 1.4 Why `detect_steganography()` Never Runs

`steg_detector.py` has 8 detection algorithms (LSB entropy, chi-square, SPA, SRM features, F5/JSteg/OutGuess, cross-channel correlation, metadata stripping). It can detect hidden data in LSB planes, JPEG domain manipulation, and metadata stripped from weaponised images.

**It is never imported or called in `vision.py`.** The triage endpoint only calls:
- `decode_barcodes()` — QR/barcode
- `detect_adversarial()` — spectral perturbation patterns

`detect_steganography()` is a dead module in the live triage path.

**For `macbook-QR.png` specifically:** A QR code overlaid on an image is primarily a BARCODE (pyzbar should catch it) and TEXT OVERLAY (OCR should catch it). It's not necessarily steganography. But a text overlay embedded subtly could also trigger `detect_adversarial()` via high-frequency energy ratio if the QR introduces pixel noise.

### 1.5 The `imagehash` Module Is Missing

`imagehash` (used for perceptual hash comparison in image dedup) is not installed:
```
ModuleNotFoundError: No module named 'imagehash'
```
This means any code path that tries to import it will silently fail or throw. It needs adding to `pyproject.toml`.

### 1.6 The "No CV Playbook" Issue: Two Completely Separate Paths

| Path | Endpoint | CV Playbook fires? | Security Matrix fires? |
|------|----------|-------------------|----------------------|
| Chat upload | `/api/v1/chat` → `vision/triage` | **NO** | Partial (text only) |
| Return/complaint | `/api/v1/cv/analyze` | **YES** | YES (via observer) |

When you upload an image in the chat box and ask "find me a MacBook", you are on the **chat path**. The `/api/v1/cv/analyze` endpoint is the explicit fraud/return investigation path (CV Playbook, evidence bundle, tier2 analysis, security observer full scan). These are two separate systems that share only the `decode_barcodes()` utility.

---

## PART 2 — WHY THE NQE IS "ASKING DUMB QUESTIONS"

### 2.1 The University Subject Question IS Coded — But Gets Blocked

`nqe.py:304-323` has `ask_university_subject` with 8 field-of-study options (Computer Science, Engineering/CAD, Data Science, Design, Architecture, Medical, Law, General). It fires when `inp.detected_use_case == "university_general"`.

This IS being set (`recommend.py:3127-3132`) via `match_use_case_from_query()` when the query contains "university", "student", etc.

**So why does it not show?**

The NQE cap is 3 questions. Coverage priority list (`nqe.py:589`):
```python
keep_ids = [q.id for q in out if q.id in ('ask_budget','ask_budget_tier','ask_use_case','ask_platform','ask_brand_pref')]
```

`ask_university_subject` is **NOT in this list**. When budget + brand are missing (2 questions from keep_ids), the 3rd slot may be filled by `ask_university_subject` only if no other template question gets in first. But if the template system adds `ask_budget_tier`, `ask_use_case`, AND `ask_brand_pref`, that's already 3 → `ask_university_subject` gets dropped.

### 2.2 Why Budget Is Re-Asked After the User Already Gave a Range

This is the biggest UX failure. Query: **"show me products for university around $1400 to $1900"**.

The NLP parser extracts `budget_min=1400, budget_max=1900` into `constraints`. But the NQE gets:

```python
_nqe_answered = dict(structured_state.get("nqe_answered_fields") or kv.get("nqe_answered_fields") or {})
nqe_input = NQEInput(
    ...
    answered_fields=_nqe_answered,   # ← only what was clicked via NQE buttons
)
```

`nqe_answered_fields` in Redis is **only updated when user clicks a disambiguation button**. The budget range typed into the query is in `constraints` but NOT in `nqe_answered_fields`. So the NQE thinks budget is unknown → asks "What budget range should I use?"

The convergence check:
```python
_CONVERGENCE_THRESHOLD = 3
for k in (inp.answered_fields or {}):
    if str(k).lower() in _HIGH_SIGNAL_SLOTS:
        _answered_high += 1
if _answered_high >= _CONVERGENCE_THRESHOLD:
    return []  # stop asking
```

On a fresh first turn: `answered_fields = {}` → `_answered_high = 0` → NQE fires all questions.

**The fix** is to bridge `constraints` → `answered_fields` before constructing NQEInput:

```python
# At ~line 3552 in recommend.py, before constructing nqe_input:
_constraints_as_facts = {}
if constraints.get("budget_min"):
    _constraints_as_facts["budget_min"] = constraints["budget_min"]
if constraints.get("budget_max"):
    _constraints_as_facts["budget_max"] = constraints["budget_max"]
if constraints.get("use_case"):
    _constraints_as_facts["use_case"] = constraints["use_case"]
if constraints.get("brand_preference"):
    _constraints_as_facts["brand_preference"] = constraints["brand_preference"]
# Merge into answered fields so NQE knows what's already resolved
_nqe_answered_merged = {**_nqe_answered, **_constraints_as_facts}

nqe_input = NQEInput(
    ...
    answered_fields=_nqe_answered_merged,  # ← use merged version
```

### 2.3 The "Widen Budget" Repeated Message Is Not NQE — It's the LLM

Looking at `no-cv-lost context.png`: "Can we widen your budget range by $200-$400?" appears 3 times. This is NOT from the NQE question template. It is the **zero-results fallback LLM response** generated fresh each turn when the query returns no products matching the strict constraints. Each turn the budget range is too narrow, the LLM re-generates the same "please widen budget" suggestion.

This is not a bug in NQE — it's that the budget narrowing message has no memory of having been suggested before. The LLM starts from scratch each time.

### 2.4 Should You Scrap the NQE?

**No.** The NQE logic in `nqe.py` is actually quite good:
- University subject detection exists and works
- Gaming depth questions exist with specific game titles
- Software detection (AutoCAD, Solidworks, Blender) exists
- Touch screen / pen input detection exists
- Convergence detection (stops asking after 3 slots filled) exists
- `previously_asked_ids` deduplication exists

**The problems are plumbing bugs, not design failures:**
1. Extracted constraints not synced to `answered_fields`
2. `ask_university_subject` not in the cap priority list
3. The LLM zero-results message is stateless

---

## PART 3 — IS THE PLATFORM A WASTE OF TIME?

Short answer: **No. But the integration layer is broken.**

The algorithms exist and work:
- `steg_detector.py` — 8 algorithms, mathematically sound
- `adversarial_image_detector.py` — FFT + recompression + diffusion spectral detection
- `barcode_decode.py` — pyzbar + OpenCV with corner crops, multi-scale
- `nqe.py` — convergence detection, game/software/touch detection, university specialization
- The security observer — DREAD/CVSS/MITRE/OWASP text pattern analysis

**What's broken is the wiring:**

| Algorithm | Has code? | Called? | Results visible? |
|-----------|-----------|---------|-----------------|
| QR decode | ✅ | ✅ (in vision/triage) | ❌ not in security matrix |
| Steg detect | ✅ | ❌ never called | ❌ |
| Adversarial detect | ✅ | ✅ (in vision/triage) | ❌ not in security matrix |
| CV Playbook | ✅ | ✅ (in cv/analyze only) | ❌ not reached from chat path |
| MITRE ATLAS mapping | ✅ | ✅ (text queries only) | ✅ for text; ❌ for image signals |
| NQE university | ✅ | ✅ | ❌ dropped by cap priority bug |
| NQE budget awareness | ✅ | ✅ | ❌ constraints not synced to answered_fields |

---

## PART 4 — FIXES IN PRIORITY ORDER

### Fix 1 (CRITICAL): Bridge constraints → NQE answered_fields
**File:** `src/app/routers/recommend.py`, around lines 3552 and 5215
**Change:** Before constructing `NQEInput`, merge current-turn `constraints` (budget_min, budget_max, use_case, brand_preference, gpu_preference) into `_nqe_answered`. This stops the NQE from re-asking for information already present in the query.

### Fix 2 (HIGH): Feed image CV signals into security observer
**File:** `src/app/routers/chat.py`, around line 319
**Change:** When `image_cv_signals_in` has `qr_code_detected=True`, `adversarial_detected=True`, or `adversarial_score > 0.5`, include these as a structured `cv_signals` dict in the `analyze_payload()` call so the observer can map them to MITRE ATLAS (T-0012 image manipulation), OWASP LLM Top 10 (LLM04 prompt injection via QR), and STRIDE (tampering/spoofing).

### Fix 3 (HIGH): Call `detect_steganography()` in vision/triage
**File:** `src/app/routers/vision.py`, around line 214
**Change:** Import and call `detect_steganography(content)` alongside `detect_adversarial(content)`. If `steg_result.is_suspicious` → add `security_signals["steg_suspicious"] = True` and `security_clean = False`.

### Fix 4 (HIGH): Add `ask_university_subject` to NQE cap keep-list
**File:** `src/app/flows/nqe.py`, line 589
**Change:** Add `'ask_university_subject'` to the `keep_ids` list so it survives the 3-question cap when `detected_use_case == "university_general"`.

### Fix 5 (MEDIUM): Map image CV signals to MITRE/OWASP in observer
**File:** `src/app/security/observer.py`, in `analyze_payload()`
**Change:** Accept optional `cv_signals` dict. If `cv_signals.get("qr_code_detected")` → emit MITRE ATLAS T-0012 (Image Metadata Manipulation). If `cv_signals.get("adversarial_detected")` → emit MITRE ATLAS T-0015 (Adversarial ML Evasion). If `cv_signals.get("steg_suspicious")` → emit STRIDE Tampering + OWASP LLM04.

### Fix 6 (MEDIUM): Install `imagehash`
**File:** `pyproject.toml`
**Change:** Add `imagehash>=4.3.1` to dependencies.

### Fix 7 (LOW): Persist text-extracted constraints to `nqe_answered_fields` in Redis
**File:** `src/app/routers/recommend.py`, around line 2874
**Change:** After constraint extraction, if budget/use_case/brand were resolved from the text query (not just from NQE clicks), save them to `nqe_answered_fields` in Redis so they persist across turns and the convergence counter fires sooner.

---

## PART 5 — DO YOU NEED A SPECIFIC LLM TO FLAG THINGS?

**No, you do not need a specific LLM.** The entire CV security pipeline is designed to be LLM-free:
- QR decode: `pyzbar` / `cv2.QRCodeDetector` (pure computer vision, no LLM)
- Steg detection: statistical LSB analysis + DCT domain tests (pure math)
- Adversarial detection: FFT spectral analysis + JPEG recompression test (pure math)
- Text injection detection: regex patterns in `observer.py` (no LLM)
- MITRE/OWASP mapping: rule-based pattern matching (no LLM)

The `llava` Ollama model is only needed for **semantic image understanding** (what is in this photo? is it damaged?). Security detections are deterministic algorithms that run on raw bytes.

**The issue is not the LLM model tier or routing. It is that the security algorithms are not wired into the data flow.**

---

## PART 6 — THE NQE "SMART QUESTIONS" DESIGN

The user is right that a good NQE should know:
- Engineering student → needs GPU for AutoCAD/Solidworks (RTX 2060+ or Quadro equivalent)
- CS student → depends: web dev needs nothing special, ML needs VRAM ≥ 8GB, systems needs fast SSD
- Arts/Psych/Humanities → note-taking only, i5/Ryzen 5, 8GB RAM, long battery
- Architecture student → CPU render (Revit, Rhino), RAM ≥ 32GB, dedicated GPU

**This logic exists in `use_case_advisor.py` and `config/use_case_knowledge_base.json`.** The university subject question in NQE IS designed to route to these spec profiles. But it's blocked by the cap priority bug (Fix 4) and the answered_fields sync bug (Fix 1).

Once Fix 1 + Fix 4 are applied:
1. User says "laptop for university $1400-$1900"
2. NQE recognizes budget is known (from constraints sync), use_case=university_general
3. NQE fires `ask_university_subject` as the ONLY remaining question
4. User clicks "Engineering / CAD" → `engineering_student` tag saved
5. Use-case advisor injects `min_ram_gb=16, min_gpu_vram_gb=4` from knowledge base
6. Recommend returns RTX laptops with 16GB RAM, not a $1499 MacBook Air

---

## APPENDIX: Key File Reference

| Issue | File | Line(s) |
|-------|------|---------|
| Vision triage auth | `src/app/routers/vision.py` | 72 |
| QR decode | `src/app/rules/barcode_decode.py` | 123 |
| Steg detect (not called) | `src/app/security/steg_detector.py` | 558 (function) |
| Adversarial detect | `src/app/security/adversarial_image_detector.py` | 214 (function) |
| Security observer | `src/app/security/observer.py` | `analyze_payload()` |
| Chat image signals | `src/app/routers/chat.py` | 250-330 |
| NQE input construction (results path) | `src/app/routers/recommend.py` | ~3552 |
| NQE input construction (narrowing path) | `src/app/routers/recommend.py` | ~5215 |
| NQE convergence | `src/app/flows/nqe.py` | 191-227 |
| NQE university question | `src/app/flows/nqe.py` | 304-323 |
| NQE cap keep-list | `src/app/flows/nqe.py` | 589 |
| CV Playbook (cv path only) | `src/app/routers/cv.py` | 350-387 |
| CV Provider (ollama config) | `src/app/services/cv_provider.py` | 17-19 |
