# ShopSquire — Bug Deep Dive & Fix Roadmap
**Date:** 2026-03-20
**Scope:** Three user-reported issues from screenshots + source code analysis

---

## Table of Contents
1. [Cracked Mac — Wrong Routing (Products Instead of Warranty/Repair/FAQ)](#1-cracked-mac)
2. [Email Security Lab — Analyse/Escalate/Demo/Agents Do Nothing](#2-email-security-lab)
3. [MSI QR Code — SSN Not Detected in Linked Artifact](#3-qr-ssn-detection)

---

## 1. Cracked Mac — Wrong Routing

### What You See
- User uploads `cracked-mac.jpg` (MacBook with shattered screen)
- User types: "i cracked my macbook! who do i talk to?"
- System responds with **3 MacBook Pro product recommendations** and a "What will you mainly use this for?" clarifying question
- Decision Trace shows: **Intent = "Why Recommended"**, Urgency = normal, Price sensitivity = medium

### What Should Happen
1. Detect damage → route to **warranty/repair/FAQ flow**, NOT product recommendations
2. Show: "This looks like a damaged MacBook. Would you like to start a warranty or repair claim?"
3. If user is **logged in** → query order history for that SKU → surface receipt/purchase proof
4. If user is **guest** → prompt: "Do you have a receipt or proof of purchase? Upload it here."
5. Surface RAG FAQ answers about Apple warranty, AppleCare, repair options, return policy

---

### Root Cause Analysis

#### A. The Intent Router IS Correct — But Never Actioned

**File:** `src/app/services/image_intent_router.py`

`classify_image_intent()` properly scores "cracked" (+0.45 cv_triage from `_CV_TRIAGE_PAT`) and a damage_score > 0.4 for a cracked screen (+0.20 cv_triage). It should return `intent = "cv_triage"` with high confidence.

**BUT**: the result is placed in `resp["intent_routing"]` in `vision.py:204-207` and then **completely ignored**. No code reads it back.

#### B. The Recommend Router Never Checks for Damage/Repair Intent

**File:** `src/app/routers/recommend.py`

The `/api/v1/recommend/suggest` endpoint receives `image_labels`, `image_ocr_text`, `image_cv_signals` from the frontend (`ImageRecommendPanel.tsx:486`). None of these signal "this is a broken product, don't show buy recommendations."

The recommend router has no guard: "if damage_score > 0.4 AND query contains repair/warranty intent → redirect to support FAQ."

#### C. Frontend Never Reads `intent_routing` from Vision Triage

**File:** `frontend/src/components/ImageRecommendPanel.tsx`

`ImageRecommendPanel` calls `/api/v1/vision/triage` (via App.tsx), receives the result, and passes `labels/ocr_text/cv_signals` to `fetchSuggest()`. It never inspects `intent_routing.intent`. Even when intent is `"cv_triage"`, it still calls `fetchSuggest()` which calls recommend.

#### D. No Warranty/Repair/FAQ RAG Path Exists in the Chat Flow

**File:** `src/app/routers/recommend.py`, `src/app/routers/chat.py`

There is a `support.py` router and a `support_complaints.py` router. The `image_intent_router.py` correctly classifies `intent="cv_triage"`. But the orchestrator (`recommend.py`) never calls the support/FAQ path based on this signal.

There is no code path that:
- Fetches FAQ articles by damage type (cracked screen, water damage, etc.)
- Queries `orders` table by logged-in user + likely-matching SKU
- Shows a receipt upload prompt or links to an existing purchase

---

### Files to Edit / Create

#### Fix 1 — `ImageRecommendPanel.tsx`: Gate on intent before recommending

**File:** `frontend/src/components/ImageRecommendPanel.tsx`
**Where:** `buildGroups()` function, around line 605 where `computeTrustLevel()` is called

Before calling `fetchSuggest()`, read the `intent_routing` from the triage response. If `intent == "cv_triage"` and `damage_score > 0.4`, skip `fetchSuggest()` and instead render a repair/warranty prompt card.

```typescript
// In App.tsx or wherever vision/triage response is processed:
// Pass intentRouting to ImageRecommendPanel as a prop

// In ImageRecommendPanel.tsx buildGroups(), before fetchSuggest():
const triageIntent = ctx.intent_routing?.intent;  // "cv_triage" | "visual_search" | "faq"
const damageScore = ctx.damage_score ?? 0;

if (triageIntent === 'cv_triage' || damageScore > 0.4) {
  // Return repair/warranty card — do NOT call fetchSuggest()
  return {
    group: {
      source: ctx.source_name || `Image ${i + 1}`,
      icon: '🔧',
      trustLevel: 'green',
      friendlyBrand: brand,
      securityNote: '',
      products: [],
      summary: '',
      isRepairIntent: true,   // NEW prop
      repairContext: { brand, damage_score: damageScore },
    },
    traceId: null,
  };
}
```

**New repair card JSX to add in the render loop:**

```tsx
{group.isRepairIntent && (
  <div className={styles.repairCard}>
    <div className={styles.repairHeading}>
      🔧 This looks like a damaged {group.friendlyBrand}.
    </div>
    <p>Would you like to:</p>
    <ul>
      <li><button onClick={() => onClarify?.('Start a warranty claim')}>
        Start a warranty / repair claim
      </button></li>
      <li><button onClick={() => onClarify?.('How do I return a damaged product?')}>
        Check the return policy
      </button></li>
      <li><button onClick={() => onClarify?.('Find an Apple repair centre')}>
        Find a repair centre near me
      </button></li>
    </ul>
    <div className={styles.repairProofPrompt}>
      Do you have a receipt or proof of purchase? Upload it below.
    </div>
  </div>
)}
```

#### Fix 2 — `recommend.py`: Add damage/repair intent guard

**File:** `src/app/routers/recommend.py`
**Where:** Early in the `suggest()` endpoint, after parsing image signals

```python
# Read intent routing from image context if provided
image_cv_signals = json.loads(request.query_params.get("image_cv_signals") or "{}")
damage_score = float(image_cv_signals.get("damage_score") or 0.0)
is_cv_triage = bool(image_cv_signals.get("intent_cv_triage"))  # set by frontend

if damage_score > 0.4 or is_cv_triage:
    # Route to support FAQ instead of product recommendations
    return {
        "mode": "support",
        "assistant_message": "It looks like your device may be damaged. "
                             "I can help you with warranty claims, return options, or finding a repair centre.",
        "faq_results": _fetch_warranty_faq(brand=image_cv_signals.get("brand_hint")),
        "products": [],
        "damage_score": damage_score,
        "intent": "cv_triage",
    }
```

#### Fix 3 — `recommend.py` / `chat.py`: FAQ RAG function

**New function to add in `recommend.py`:**

```python
def _fetch_warranty_faq(brand: str | None = None) -> list[dict]:
    """Pull top FAQ articles matching warranty/repair/return topics."""
    from src.app.services.faq_retrieval import search_faq  # needs creating or already exists
    query = f"{brand or ''} warranty repair return damaged policy".strip()
    return search_faq(query=query, top_k=3, topic_filter="warranty_repair")
```

**New file needed:** `src/app/services/warranty_repair_flow.py`
- `get_user_purchase_history(user_id, brand_hint)` → query `orders` table filtered by brand
- `build_repair_prompt(damage_type, brand, has_receipt, purchase_date)` → structured response
- `escalate_to_repair_agent(case_context)` → creates incident via `escalation_room.py`

#### Fix 4 — `vision.py`: Pass `intent_routing` + `damage_score` into CV signals

**File:** `src/app/routers/vision.py:200-207`

Currently `intent_routing` is stored in `resp["intent_routing"]` but NOT included in the `security.signals` or any field the frontend ImageRecommendPanel reads for routing decisions.

```python
# After computing intent_result, line ~205:
intent_result = classify_image_intent(...)
resp["intent_routing"] = intent_result

# ADD: propagate damage_score into cv_signals so the frontend can gate on it
resp["damage_score"] = resp.get("damage_score", 0.0)
resp["intent"] = intent_result.get("intent", "visual_search")
```

Then in `App.tsx`, when building `imageContext` from the vision triage response, include:
```typescript
intent_routing: triageResp.intent_routing,
damage_score: triageResp.damage_score,
```

#### Fix 5 — If User is Logged In: Pull Purchase History

**File:** `src/app/routers/recommend.py` or new `support_image.py` endpoint

```python
@router.post("/support/image-triage")
async def support_image_triage(
    uid: str,
    brand_hint: str | None = None,
    damage_type: str | None = None,
):
    """Called instead of /suggest when intent == cv_triage."""
    # 1. Pull user orders
    orders = await get_orders_for_user(uid)
    matching_orders = [o for o in orders if brand_hint and brand_hint.lower() in o.get("brand", "").lower()]

    # 2. Check warranty status
    warranty_eligible = [
        o for o in matching_orders
        if _within_warranty_window(o.get("purchase_date"), months=24)
    ]

    # 3. Fetch FAQ
    faq = search_faq(f"{brand_hint} {damage_type} repair warranty return", top_k=3)

    return {
        "intent": "cv_triage",
        "matching_orders": matching_orders[:3],
        "warranty_eligible": warranty_eligible[:3],
        "faq": faq,
        "next_step": "escalate_to_support" if warranty_eligible else "check_policy",
        "prompt": _build_repair_message(brand_hint, damage_type, bool(warranty_eligible)),
    }
```

---

### Summary of Changes Required

| File | Change | Priority |
|------|--------|----------|
| `frontend/src/components/ImageRecommendPanel.tsx` | Read `intent_routing` / `damage_score`, skip recommend if cv_triage | CRITICAL |
| `src/app/routers/vision.py` | Pass `damage_score` + `intent` into response fields readable by frontend | HIGH |
| `src/app/routers/recommend.py` | Guard: if `damage_score > 0.4` → return support FAQ instead of products | HIGH |
| `src/app/routers/recommend.py` | New endpoint `/support/image-triage` for repair/warranty flow | HIGH |
| `src/app/services/warranty_repair_flow.py` | NEW: purchase history lookup, warranty eligibility, RAG FAQ | HIGH |
| `frontend/src/App.tsx` | Pass `intent_routing` + `damage_score` through to ImageRecommendPanel | MEDIUM |

---

## 2. Email Security Lab — Analyse/Escalate/Demo/Agents Do Nothing

### What You See
- Email body is filled in (IngramWake supplier, payment change)
- 2 PDF files loaded as attachments
- Click Analyse → nothing happens
- Click Escalate → nothing happens
- Click Demo → nothing happens
- Click Agents → nothing happens
- Right panel: "Decision Trace & Security Matrix" stays empty, "Related Incident: Status: none"

---

### Root Cause Analysis

#### A. PRIMARY: API Auth Failure — `ROLE_OWNER` / `ROLE_DEVELOPER` Required

**File:** `src/app/routers/email_security.py:31`

```python
role: str = Depends(require_role([ROLE_OWNER, ROLE_DEVELOPER])),
```

The `/api/v1/email_security/evaluate` endpoint requires `ROLE_OWNER` or `ROLE_DEVELOPER`. This is **more restrictive** than other demo-facing endpoints which allow `ROLE_MERCHANT`.

**What the JS does:**
1. Tries `getApiKey()` — reads cookie `shopsquire_api_key`. A fresh browser session to `/merchant/email-lab` has NO cookie set (email-lab is a plain HTML route, doesn't run the React app login flow).
2. On 401/403, retries with `getOwnerKey()` which returns `local-owner-key`.

**The gap:** Unless the backend has `OWNER_API_KEY=local-owner-key` in its environment AND `local-owner-key` maps to `ROLE_OWNER`, the retry also fails with 403. The error IS caught and sets `status` text — but the `#status` span is visually tiny at the bottom of the button row and easy to miss.

**Fix:** Add `ROLE_MERCHANT` to the allowed roles for the evaluate endpoint (it's a demo lab tool), OR make the email lab pre-authenticate using the same cookie mechanism as the React app.

```python
# email_security.py:31 — change to:
role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER])),
```

OR: In `merchant_dashboard.py`, add a cookie injection in the email-lab HTML header response:

```python
# At top of merchant_email_lab() — inject the api key as a cookie so JS can use it
from src.app.config import OWNER_API_KEY
response = HTMLResponse(content=html)
response.set_cookie("shopsquire_api_key", OWNER_API_KEY, httponly=False, samesite="strict")
return response
```

#### B. Demo Button — Static Assets Don't Exist

**File:** `src/app/routers/merchant_dashboard.py:756-778`

`loadDemoAssets()` tries to fetch:
- `/static/email_lab/invoice_demo.md`
- `/static/email_lab/email_demo.eml`
- `/static/email_lab/homoglyph_demo.txt`

These files almost certainly don't exist in the `static/email_lab/` directory. The `fetch()` fails with 404, the `try/catch` silently swallows errors (`catch(e){ /* ignore */ }`), and the status shows "Demo assets ready" even with empty attachments.

**Fix:** Create the static demo assets:

```
static/email_lab/invoice_demo.md          — fake supplier invoice with bank fields
static/email_lab/email_demo.eml           — raw EML format fake email with BEC signals
static/email_lab/homoglyph_demo.txt       — text with confusable Unicode chars
```

Or change `loadDemoAssets()` to use inline hardcoded content instead of fetching:

```javascript
async function loadDemoAssets() {
  // Use inline demo content instead of static files
  const invoiceText = `INVOICE #INV-2026-0142\nIngramWake Pty Ltd\nBSB: 062-000\nAccount: 12345678\nAmount: $48,500.00`;
  const b64 = btoa(unescape(encodeURIComponent(invoiceText)));
  window.__demoAtts = [{
    name: 'invoice_demo.txt',
    content_type: 'text/plain',
    size_bytes: invoiceText.length,
    content_b64: b64,
  }];
  document.getElementById('att_list').textContent = 'invoice_demo.txt (inline demo)';
  document.getElementById('status').textContent = 'Demo assets loaded';
}
```

#### C. Agents Button — `/api/v1/trace/events` Auth

**File:** `merchant_dashboard.py:1037`

```javascript
const r = await fetch('/api/v1/trace/events', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json', 'x-api-key': getApiKey() },
  body: JSON.stringify(batch)
});
```

Same problem: `getApiKey()` returns empty string without cookie → 401. The button silently fails because the error sets `status.textContent='Simulation failed'` which is tiny.

**Fix:** Same as Fix A — pass auth cookie or loosen auth for `/api/v1/trace/events` to allow `ROLE_MERCHANT`.

#### D. Right Panel Cards Don't Show Full Agent Findings

**Issue:** Even when analysis succeeds, the right panel cards (Security Overview, BEC Kill Chain, Threat Correlation, etc.) only populate if `j.evidence_snapshot` contains the right nested keys. If the backend `evaluate_email_security()` doesn't return those keys, all cards stay hidden.

**File:** `src/app/security/email_security.py`

Verify that `evaluate_email_security()` returns an `evidence_snapshot` dict with keys:
- `bec_kill_chain` (with `stage`, `confidence`, `attack_flow`)
- `trust_case` (with `score`, `level`, `progressive_access`, `actions`)
- `threat_correlation` (with `mitre_attack`, `dread`, `cvss`, `kill_chain_stage`, `pasta_stage`, `kev`)
- `detonation` (with `provider`, `malicious`, `findings`)
- `ioc_counts` (with `url`, `domain`, `hash`)
- `artifact_intel` (with `signals`)
- `attachment_ingest_gate` (with `signal_score`, `band`)
- `ocr_qr_sanitization` (with `qr_count`, `malicious_qr`, `urls_found`, `ocr_tokens`)

If any of these are missing from the response, the `renderSecurityPanels()` function silently hides that card (`if(thr.mitre_attack || thr.dread || ...)` will be falsy).

**Debug step:** Add `console.log(j)` after the fetch in `analyze()` to see the raw response. Also check `#status` in the page — the status text will show the error even though it's small.

#### E. PDF Attachment Analysis — SSN Detection in PDFs

**Issue:** The two uploaded PDFs (IngramFake_March2026_Catalog.pdf, IngramTech_March_Catalog.pdf) should be scanned for:
- Fake bank fields (BSB, account number)
- Embedded QR codes
- Steganography in embedded images
- Payment fraud signals

**File:** `src/app/security/email_attachment_parser.py`

The `hydrate_attachments_from_bytes()` function does this correctly IF the `content_b64` is provided. Check that the JS `collectAttachments()` is sending the base64 correctly — it should be.

**Verify:** After `analyze()` succeeds, check `j.evidence_snapshot?.attachment_ingest_gate` in the browser console.

#### F. Playbook Results Not Surfaced in UI

**Issue:** `config/security/cv_playbooks.json` contains playbooks but the email lab UI has no panel to show which playbook fired and what actions it took.

**Fix needed in `renderSecurityPanels(j)`:**

```javascript
// Add after existing panels:
const playbook = j.evidence_snapshot?.playbook_run || j.playbook_run;
if (playbook) {
  const pb = document.getElementById('playbook_card');
  pb.style.display = 'block';
  document.getElementById('pb_name').textContent = playbook.playbook_id || '-';
  document.getElementById('pb_actions').innerHTML =
    (playbook.actions_completed || []).map(a => `<div class='pill'>${a}</div>`).join('');
}
```

And add the playbook card HTML in the right panel.

#### G. `findRelatedIncident()` — Wrong Endpoint

**File:** `merchant_dashboard.py:997`

```javascript
const r = await fetch('/api/v1/admin/email_security/incidents?limit=20&has_ticket=true');
```

This endpoint `/api/v1/admin/email_security/incidents` is defined in `email_security_admin.py` or `admin_email_security.py` — check whether `has_ticket=true` is a supported query param. If it's not, the endpoint returns all incidents and the `match` lookup fails because `evidence_snapshot.trace_id` isn't populated.

---

### Summary of Changes Required

| File | Change | Priority |
|------|--------|----------|
| `src/app/routers/email_security.py:31` | Add `ROLE_MERCHANT` to allowed roles | CRITICAL |
| `src/app/routers/merchant_dashboard.py` | Inject API key cookie in email-lab response | CRITICAL |
| `static/email_lab/` | Create demo asset files (or use inline JS content) | HIGH |
| `src/app/routers/merchant_dashboard.py:renderSecurityPanels` | Add `console.log(j)` for debug; verify all evidence_snapshot keys | HIGH |
| `src/app/security/email_security.py` | Verify `evidence_snapshot` includes all keys the UI expects | HIGH |
| `src/app/routers/merchant_dashboard.py` | Add Playbook Run panel to right panel HTML + renderSecurityPanels | MEDIUM |
| `src/app/routers/merchant_dashboard.py:findRelatedIncident()` | Fix endpoint URL / query params | MEDIUM |

---

## 3. QR Code SSN Detection — Why It Fails

### What You See
- `test-cv/msi-SSN.png` — MSI laptop with a QR code overlaid on the screen
- `test-sec/QR-SSN.png` — the standalone QR code
- `SSN-numberz - Sheet1.pdf` — a PDF containing SSN data
- Screenshots show:
  - QR is detected ✓ (`https://scanned.page/r/R2gZ1b`)
  - QR External URL flagged ✓
  - Linked Artifact: type = HTML ✓ (the landing page)
  - **PII detected = N** ← WRONG, should be Y
  - **SSN hits = empty** ← WRONG
  - PASTA Stage2 (Technical Scope Definition) ← correct given no hypothesis confirmed

---

### Root Cause Analysis (5-Layer Failure)

#### Layer 1: `_provider_candidate_urls()` Has Wrong Path Pattern

**File:** `src/app/security/linked_artifact_analysis.py:58-64`

```python
def _provider_candidate_urls(*, source_url: str) -> List[str]:
    parsed = urlparse(source_url)
    host = str(parsed.netloc or "").lower()
    path = str(parsed.path or "").strip("/")
    if host not in {"scanned.page", "www.scanned.page"}:
        return []

    parts = [p for p in path.split("/") if p]
    if len(parts) < 2 or parts[0] != "p":   # ← BUG: checks for "p", not "r"
        return []
```

The URL is `https://scanned.page/r/R2gZ1b`. The path is `/r/R2gZ1b`, so `parts[0] = "r"`, not `"p"`. The check `parts[0] != "p"` fails → function returns `[]` → no API metadata fetch → no PDF URL found.

**Fix:** Add `"r"` as a supported path prefix:

```python
# linked_artifact_analysis.py
_SCANNED_PAGE_PATH_PREFIXES = {"p", "r", "s", "qr"}

parts = [p for p in path.split("/") if p]
if len(parts) < 2 or parts[0] not in _SCANNED_PAGE_PATH_PREFIXES:
    return []
uid = parts[1].strip()

# Try both API patterns for scanned.page:
api_candidates = [
    f"{parsed.scheme or 'https'}://{host}/api/qr-code?uId={uid}",
    f"{parsed.scheme or 'https'}://{host}/api/scan/{uid}",
    f"{parsed.scheme or 'https'}://{host}/api/v1/qr/{uid}",
]
for api_url in api_candidates:
    try:
        resp = safe_request("GET", api_url, timeout=6.0, allow_redirects=True)
        if int(getattr(resp, "status_code", 0) or 0) < 400:
            data = resp.json() if hasattr(resp, "json") else {}
            if isinstance(data, dict) and data.get("data"):
                # process data...
                break
    except Exception:
        continue
```

#### Layer 2: The Landing Page Is a JavaScript SPA

`scanned.page/r/R2gZ1b` likely serves a React/Next.js SPA. The static HTML returned by `safe_request()` is a shell page that loads the actual content via JavaScript fetch calls. The static HTML contains `<div id="root"></div>` and script tags, but the SSN-containing PDF URL is only visible AFTER JavaScript runs.

**`_extract_candidate_urls()` will find JavaScript bundle URLs**, not the PDF. The `_score()` function inside ranks URLs by `artifact_ext` and `artifact_hint`, but if the PDF URL is in a JS variable or API response, it won't be in the static HTML at all.

**Fix:** Two approaches:
1. Use Playwright/headless Chrome to render the SPA before analysis (heavy, good for production)
2. Try a predictable API URL pattern for scanned.page to get the direct PDF link (lighter, demo-friendly)

For the demo, approach 2 is better:

```python
# In _provider_candidate_urls(), after getting the API response:
# scanned.page API returns data.pdf = "https://cdn.scanned.page/.../document.pdf"
for key in ("pdf", "pdfUrl", "documentUrl", "fileUrl", "website", "url", "file"):
    value = str(payload.get(key) or "").strip()
    if value.startswith(("http://", "https://")):
        candidates.append(value)
# Also check nested structures:
if isinstance(payload.get("content"), dict):
    for key in ("pdf", "url", "fileUrl"):
        value = str(payload["content"].get(key) or "").strip()
        if value.startswith(("http://", "https://")):
            candidates.append(value)
```

#### Layer 3: SSN Pattern Only Matches Hyphenated Format

**File:** `src/app/security/linked_artifact_analysis.py:16`

```python
_SSN_PAT = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
```

This only matches `XXX-XX-XXXX` (hyphenated). SSNs in spreadsheets/CSVs often appear as:
- `123456789` (no separators, from spreadsheet cell)
- `123 45 6789` (space-separated)
- `123.45.6789` (period-separated)

**File:** `c:\AI\ShopSquire\dump\SSN-numberz - Sheet1.pdf` — a Google Sheets export. The SSN likely appears as a bare 9-digit number `123456789` in the CSV/PDF.

**Fix:**

```python
_SSN_PAT = re.compile(
    r"\b(\d{3}[-.\s]?\d{2}[-.\s]?\d{4})\b"          # XXX-XX-XXXX or XXXXXXXXX
    r"|\bSSN[\s:]*(\d{3}[-.\s]?\d{2}[-.\s]?\d{4})\b"  # SSN: XXXXXXXXX
    r"|\bSocial\s+Security\s+Number[\s:]*(\d{3}[-.\s]?\d{2}[-.\s]?\d{4})\b",
    re.IGNORECASE,
)
```

Also add a `_SSN_BARE_PAT` for 9-digit numbers that could be SSNs (with low confidence, requires context):

```python
_SSN_BARE_PAT = re.compile(r"\b([2-9]\d{2}[1-9]\d[1-9]\d{4})\b")  # valid SSN range heuristic
```

#### Layer 4: OCR Not Running on the PDF (BUG-3 from Memory)

Even if the PDF is fetched, `_ocr_pdf_pages()` requires:
- `pypdfium2` (for rasterizing PDF pages)
- `pytesseract` + Tesseract binary (for OCR)

From project memory (BUG-3): **`pytesseract`, `pyzbar`, `paddleocr`, `imagehash` are NOT installed in the Docker container**. All CV operations silently fail via `except Exception: pass`.

**Without OCR, `_extract_pdf_text()` runs instead. A Google Sheets PDF export might be text-selectable (pypdf works) OR it might be a rasterized image (pypdf finds nothing, OCR needed).**

**Fix:**
1. Add to `requirements.txt` / `pyproject.toml`:
   ```
   pypdfium2>=4.0.0
   pytesseract>=0.3.10
   pyzbar>=0.1.9
   ```
2. Add to `Dockerfile`:
   ```dockerfile
   RUN apt-get install -y tesseract-ocr libzbar0 libzbar-dev
   ```
3. **Verify** by checking `src/app/security/linked_artifact_analysis.py:125-127`:
   ```python
   def _ocr_pdf_text(blob: bytes) -> str:
       return _ocr_pdf_pages(blob, max_pages=3, scale=2.0)
   ```
   This is called at line 205: `if artifact_type == "pdf" and (len(combined_text) < 48 or _pdf_text_looks_unusable(combined_text)):`
   So OCR is a FALLBACK only when pypdf text extraction fails. If the PDF is a Sheets export, pypdf might work fine and OCR never runs — which would be fine IF the SSN regex matches.

#### Layer 5: `vision.py` Does NOT Auto-Call `analyze_linked_artifact()`

**File:** `src/app/routers/vision.py:228-279`

The QR URL is detected and placed in `security_signals["qr_payloads"]`. The vision endpoint runs:
- `_probe_redirect_chain()` (follows HTTP redirects only, max 3 hops, 1.25s timeout)
- Does NOT call `analyze_linked_artifact()`

`analyze_linked_artifact()` is only called:
1. When the user clicks the "Analyze linked document" button in the Security Matrix UI → calls `POST /api/v1/incidents/analyze-linked-artifact`
2. When an incident is manually escalated

**So the SSN scan only runs on explicit user action, not automatically during vision triage.**

**Fix:** In `vision.py`, after detecting `qr_external_url`, automatically call `analyze_linked_artifact()` for the first external URL found:

```python
# vision.py, after line ~278 (qr_external_url detection):
if security_signals.get("qr_external_url") and not fast:
    try:
        from src.app.security.linked_artifact_analysis import analyze_linked_artifact
        qr_url = next(
            (str(c.get("data") or "") for c in qr_codes
             if str(c.get("data") or "").lower().startswith(("http://", "https://"))),
            None,
        )
        if qr_url:
            linked = analyze_linked_artifact(url=qr_url, timeout=6.0)
            resp["linked_artifact"] = linked
            # Promote signals from linked artifact
            if linked.get("pii_detected"):
                security_signals["pii_detected"] = True
                security_signals["pii_types"] = linked.get("pii_type", [])
                security_clean = False
            if linked.get("ssn_hits"):
                security_signals["ssn_detected"] = True
                security_signals["ssn_count"] = len(linked["ssn_hits"])
                security_clean = False
            # Update attack hypothesis
            linked_hypo = linked.get("linked_attack_hypothesis", "unknown_remote_artifact")
            if linked_hypo not in ("unknown_remote_artifact",):
                security_signals["linked_artifact_hypothesis"] = linked_hypo
    except Exception:
        pass
```

#### Layer 6: Security Matrix UI Doesn't Show SSN/PII From Linked Artifact

**File:** `frontend/src/components/DecisionTrace.tsx` (and the visual search Security Matrix tab)

Even if `linked_artifact.ssn_hits` is returned by the vision triage endpoint, the Security Matrix panel only displays the data from `payload_analysis` (which comes from `passive_payload_analysis.py`). The `passive_payload_analysis.py` has no `ssn_exposed` hypothesis type.

**Fix in `passive_payload_analysis.py`:**

```python
# Add to _HYPOTHESIS_TO_MITRE:
"pii_data_exfil_via_qr": ["T1041", "T1566.002", "T1078"],

# Add to classify_passive_payload() after checking for ssn in signals:
if sigs.get("ssn_detected") or sigs.get("pii_detected"):
    hypothesis = "pii_data_exfil_via_qr"

# Add to SIGNAL_LABELS:
"ssn_detected": "SSN in Linked Artifact",
"pii_detected": "PII Data Exposed",
"pii_types": "PII Types Found",
```

**Fix in UI:** Add SSN/PII rows to the Security Matrix panel in `DecisionTrace.tsx`:

```tsx
{securityData?.ssn_detected && (
  <tr className={styles.threatRow}>
    <td>SSN Detected</td>
    <td className={styles.threatYes}>
      ⚠️ {securityData.ssn_count} SSN(s) found in linked artifact
    </td>
  </tr>
)}
```

---

### End-to-End Fix Path for SSN Detection

The correct flow when a user uploads an image with a QR code linking to a page with SSN data:

```
msi-SSN.png uploaded
  ↓ vision.py /api/v1/vision/triage
  ↓ decode_barcodes() → finds QR → "https://scanned.page/r/R2gZ1b"
  ↓ qr_external_url = True [ALREADY WORKS]
  ↓ [NEW] analyze_linked_artifact("https://scanned.page/r/R2gZ1b")
      ↓ _provider_candidate_urls() → FIX: handle /r/ path → get PDF URL from API
      ↓ safe_request(pdf_url) → download PDF
      ↓ _extract_artifact_text(artifact_type="pdf", blob=pdf_bytes)
          ↓ _extract_pdf_text() → pypdf extracts "123-45-6789" from sheet
          ↓ OR _ocr_pdf_text() → pytesseract finds "123456789"
      ↓ _SSN_PAT.findall(combined_text) → FIX: extend regex to match bare 9-digit
      ↓ ssn_hits = ["123-45-6789"]  ← FOUND!
      ↓ pii_detected = True, attack_hypothesis = "linked_pii_exposure"
  ↓ security_signals["ssn_detected"] = True [NEW]
  ↓ passive_payload_analysis → hypothesis = "pii_data_exfil_via_qr" [NEW]
  ↓ UI Security Matrix shows: PII Detected = Y, SSN = 1 found ← WORKING
```

---

### Summary of Changes Required

| File | Change | Priority |
|------|--------|----------|
| `src/app/security/linked_artifact_analysis.py:58-85` | Fix `_provider_candidate_urls()` to handle `/r/` path, try multiple API URLs | CRITICAL |
| `src/app/security/linked_artifact_analysis.py:16` | Extend `_SSN_PAT` to match hyphen-free and space-separated formats | CRITICAL |
| `src/app/routers/vision.py` (after line ~278) | Auto-call `analyze_linked_artifact()` for external QR URLs | HIGH |
| `src/app/security/passive_payload_analysis.py` | Add `pii_data_exfil_via_qr` hypothesis + SSN signals | HIGH |
| `pyproject.toml` / `requirements.txt` | Add `pypdfium2`, `pytesseract`, `pyzbar` | HIGH |
| `Dockerfile` | `apt-get install tesseract-ocr libzbar0` | HIGH |
| `frontend/src/components/DecisionTrace.tsx` | Add SSN/PII rows to Security Matrix panel | MEDIUM |
| `src/app/security/linked_artifact_analysis.py` | Extend candidate URL extraction to check nested JSON keys from SPA APIs | MEDIUM |

---

## Appendix: Priority Order for Next Sprint

### Sprint 1 (Day 1-2) — Critical Path
1. **Email Lab auth** — add `ROLE_MERCHANT` to `/api/v1/email_security/evaluate` or inject cookie
2. **Cracked Mac gate** — read `intent_routing` in `ImageRecommendPanel`, skip recommend if cv_triage
3. **SSN regex fix** — extend pattern in `linked_artifact_analysis.py`
4. **scanned.page `/r/` path fix** — update `_provider_candidate_urls()`

### Sprint 2 (Day 3-4) — High Impact
5. **Auto-call `analyze_linked_artifact()`** from `vision.py` for external QR URLs
6. **Install CV deps** in Docker (`pyzbar`, `pytesseract`, `pypdfium2`, Tesseract binary)
7. **Demo assets** — create `static/email_lab/` files or switch to inline content
8. **Warranty/repair flow** — new `warranty_repair_flow.py` service + endpoint

### Sprint 3 (Day 5+) — Complete the Loop
9. **Email lab playbook panel** — show which playbook fired + actions taken
10. **SSN hypothesis** in `passive_payload_analysis.py`
11. **UI: SSN/PII rows** in Security Matrix
12. **Logged-in user receipts** — query `orders` table in repair/warranty flow

---

## Key Files Reference

```
src/app/routers/vision.py                 — vision triage, QR detection, linked artifact hook
src/app/services/image_intent_router.py   — intent classification (cv_triage vs visual_search)
src/app/security/linked_artifact_analysis.py — scanned.page fetch, SSN detection, PII
src/app/security/passive_payload_analysis.py  — hypothesis classification, signal labels
src/app/rules/barcode_decode.py           — QR/barcode decode (pyzbar + OpenCV)
src/app/security/email_attachment_parser.py   — PDF text/steg extraction for email lab
src/app/routers/email_security.py         — /api/v1/email_security/evaluate endpoint
src/app/routers/merchant_dashboard.py     — email-lab HTML + JS buttons + API calls
frontend/src/components/ImageRecommendPanel.tsx — visual search panel, brand fallback chain
frontend/src/App.tsx                      — chat flow, vision triage dispatch
```
