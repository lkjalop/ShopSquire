# ShopSquire — Next Sprint Roadmap
_Generated 2026-03-10 | AI Architect working reference_

---

## What Niche Are We Targeting?

**Primary:** Independent and mid-market ecommerce brands (Shopify Plus, WooCommerce, Magento) that sell
consumer electronics, appliances, or any high-AOV (average order value >$300) product where:
- Return/warranty fraud is a real cost (cracked screens, manufactured defects)
- Buyers need guided selling ("which laptop for my degree / gaming setup?")
- Post-purchase support is expensive to staff

**Positioning in one sentence:**
> ShopSquire is the AI-native commerce layer that wraps any ecommerce platform with intelligent
> guided selling, CV-powered triage, and a full incident-to-resolution loop — all auditable in
> a bitemporal decision trace.

**Who we are NOT targeting yet:**
- Fashion / apparel (no CV fit model)
- Grocery / FMCG (AOV too low, no warranty dimension)
- B2B procurement (different persona, needs ERP depth not visual search)

---

## Current Platform State (March 2026)

| Layer | Status | Notes |
|---|---|---|
| Chat / NLP recommend | ✅ Working | NQE, persona, budget fitness, copywriting |
| Visual search / image triage | ✅ Working | Triage → ImageRecommendPanel |
| CV complaint triage | ✅ Working | 2 buttons (fixed), image_recommend_context extracted |
| Escalation Room (real-time) | ✅ Wired | WS→SSE→poll fallback, buyer+staff tokens |
| Cart + upsell | ✅ Working | CartPanel calls /checkout_upsell |
| Decision Trace modal | ✅ Working | Timeline, Security Matrix, image triage signals |
| Budget fitness advice | ✅ Fixed | Now surfaces in chat as ⚠️ note |
| onClarify chip → chat | ✅ Fixed | Visual search chips route back to input |
| Warranty policy engine | ❌ Missing | No expiry calc, no repair quote |
| Purchase verification | ❌ Missing | Order ID lookup exists; receipt scan absent |
| Min/Recommended tier UI | ❌ Missing | Backend splits tiers; product cards don't show split |
| ERP wired into triage | ❌ Missing | Connectors built, not called during complaint |
| 3rd-party insurer dispatch | ❌ Missing | Not started |
| Repair cost estimation | ❌ Missing | Not started |

---

## Servers — No Restart Required

Both are already running:
- **Backend** `http://127.0.0.1:8080` → `200 OK` (confirmed in health check)
- **Frontend** `http://localhost:5173` → Vite dev server active

The last "Exit Code 1" was `[Errno 10048] EADDRINUSE` — a *second* uvicorn tried to bind to an
already-occupied port. The **original process is healthy**. Do not restart.

If a restart is ever needed:
```powershell
# Kill existing
Stop-Process -Name python -Force -ErrorAction SilentlyContinue
Start-Sleep 2

# Restart backend
$env:DATABASE_URL  = 'sqlite+pysqlite:///C:/AI/ShopSquire/tmp/e2e.sqlite'
$env:DISABLE_UI_ROUTES = '0'; $env:API_PORT = '8080'
$env:COPYWRITING_ENABLED = '1'
& 'c:/Users/leoma/AppData/Local/Programs/Python/PYTHON311/python.exe' `
    -m uvicorn src.app.main:create_app --host 127.0.0.1 --port 8080 --factory

# Restart frontend (separate terminal, from frontend/)
cd frontend; npm run dev
```

---

## Sprint 1 — Escalation Room: Human-to-Human Demo

### What it is today
The escalation room (`src/app/routers/escalation_room.py`) opens when:
1. CV triage returns `human_review=True` (damage detected, or order not found)
2. User clicks "Chat with Admin" in the right panel
3. A modal overlay opens on top of the storefront
4. Buyer and staff share a real-time channel via WebSocket → SSE → poll fallback

### How to demo it right now
```
1. Open localhost:5173
2. Type: "My MacBook screen is cracked, I want warranty repair"
3. Upload: dump/test-cv/cracked-mac.jpg + dump/test-cv/windows-11-bsod.avif
4. Fill Order ID: ORD-TEST-001  (any string — soft-verify if not in DB)
5. Click: Submit Complaint
6. After verdict appears → click: [Chat with Admin]
7. Escalation Room modal opens
8. Open localhost:8080/ui/merchant in a second browser tab
9. Merchant sees the incident in the list → clicks in
10. Staff types a reply → buyer sees it in real-time
```

### What's missing for a clean demo

**File to edit:** `frontend/src/components/EscalationRoom.tsx`

| # | Gap | Lines to Change | What to Add |
|---|---|---|---|
| 1 | No buyer identity label in chat | ~line 155 (render loop) | Show `[You]` vs `[Support]` by comparing `role` to buyer token |
| 2 | No typing indicator | After line 160 | SSE "typing" event → animated dots |
| 3 | No incident summary card collapse | Line 95-130 | Default collapsed, expand on click |
| 4 | No "case resolved" banner | Line 180+ | Poll incident status → show green banner when `status=resolved` |
| 5 | Merchant send path needs role=staff | `POST /{id}/room/message` caller | Pass `role=staff` so label is correct in buyer view |

**File to edit:** `src/app/routers/escalation_room.py`

| # | Gap | Lines | What to Add |
|---|---|---|---|
| 6 | No warranty context in seed message | `_seed_incident_chat_context()` ~line 1200 | Append `issue_type`, `damage_types`, `warranty_candidate` from case context |
| 7 | No "typing" broadcast | `_append_chat()` ~line 465 | Add `event_type=typing` path that only publishes to SSE queue, no disk write |
| 8 | No case summary endpoint for buyer | New `GET /{id}/summary/public?token=` | Returns title, severity, created_at, status — no internal fields |

**AdminShell.jsx changes** (`frontend/src/AdminShell.jsx` lines 100-120):
- Pass `onResolve` callback into `<EscalationRoom>` so merchant can mark resolved from within the room without leaving the page

---

## Sprint 2 — Min/Recommended Tier Split in Product Cards

### What exists in backend
`_build_minimum_recommended_tiers()` in `src/app/routers/recommend.py` line 1289 already splits
products into:
- `minimum[]` — affordable, entry-spec items that meet the use-case floor
- `recommended[]` — mid-to-high spec items with better longevity

The split is returned inside `right_panel.lower_tier` / `right_panel.higher_tier` from
`_build_right_panel_contract()` in `src/app/routers/chat.py` line 465.

### What's missing in frontend

**File:** `frontend/src/App.tsx`

Lines ~1453-1490 render `anchor_sections` from `rightPanelContract` but do NOT render
`lower_tier` / `higher_tier`. Add a tier banner above the product grid:

```tsx
// After anchor_sections block (~line 1470), add:
{rightPanelContract?.show_tiers && (
  <div className={styles.tierBlock}>
    <div className={styles.tierLabel}>
      {rightPanelContract.budget_status === 'low'
        ? '⚠️ Budget is tight — showing best value options first'
        : 'Showing budget-fit + performance-fit options'}
    </div>
    <div className={styles.tierPills}>
      <button onClick={() => setTierFilter('lower')}
        className={tierFilter === 'lower' ? styles.tierPillActive : styles.tierPill}>
        💰 Budget fit ({rightPanelContract.lower_tier?.items?.length ?? 0})
      </button>
      <button onClick={() => setTierFilter('higher')}
        className={tierFilter === 'higher' ? styles.tierPillActive : styles.tierPill}>
        🚀 Performance fit ({rightPanelContract.higher_tier?.items?.length ?? 0})
      </button>
      <button onClick={() => setTierFilter('all')}
        className={tierFilter === 'all' ? styles.tierPillActive : styles.tierPill}>
        All results
      </button>
    </div>
    {tierFilter !== 'all' && (
      <div className={styles.tierExplanation}>
        {tierFilter === 'lower'
          ? rightPanelContract.lower_tier?.explanation
          : rightPanelContract.higher_tier?.explanation}
      </div>
    )}
  </div>
)}
```

**State to add** (`App.tsx` line ~310):
```tsx
const [tierFilter, setTierFilter] = useState<'all'|'lower'|'higher'>('all');
```

**Filter `displayProducts`** downstream in the product grid render:
```tsx
const filteredProducts = tierFilter === 'lower'
  ? (rightPanelContract?.lower_tier?.items?.map(p => ...) ?? displayProducts)
  : tierFilter === 'higher'
    ? (rightPanelContract?.higher_tier?.items?.map(p => ...) ?? displayProducts)
    : displayProducts;
```

**CSS to add** (`frontend/src/App.module.css`):
```css
.tierBlock { margin: 8px 0 12px; padding: 10px 12px; background: #f0f4ff; border-radius: 8px; }
.tierLabel { font-size: 12px; color: #4b5563; margin-bottom: 6px; }
.tierPills { display: flex; gap: 6px; flex-wrap: wrap; }
.tierPill { padding: 4px 12px; border-radius: 999px; border: 1px solid #d1d5db; font-size: 12px; cursor: pointer; background: #fff; }
.tierPillActive { background: #2563eb; color: #fff; border-color: #2563eb; }
.tierExplanation { font-size: 11px; color: #6b7280; margin-top: 6px; }
```

---

## Sprint 3 — Decision Trace: "Why These Products?" Tab

### Current state
The Decision Trace modal has tabs: Timeline | Security Matrix | Explain | Intent | Quality.
None of them show a human-readable "why was THIS specific product ranked #1?"

### What exists in backend (already returned)
Each product in `data.products[]` already has:
```json
{
  "sku": "LN-YOGA9",
  "name": "Lenovo Yoga 9i",
  "price": 1299,
  "reasons": ["matches gaming use-case", "16GB RAM", "RTX GPU"],
  "reason_codes": [{"code": "use_case_match", "confidence": 0.91}],
  "score_norm": 87,
  "factors": { "positive": ["budget_fit", "brand_affinity"], "negative": [] }
}
```

And `right_panel.anchor_sections[].summary` has the image-to-product reasoning:
```json
{
  "summary": "Best 3 matches for this image in $800-$1500. Prioritized for gaming...",
  "match_basis": ["budget_fit", "query_intent", "image_brand_hint", "persona_profile"]
}
```

### What to add in DecisionTrace.tsx

**File:** `frontend/src/components/DecisionTrace.tsx`

Add a **"Why Recommended"** tab (after the existing tabs, ~line 460):

```tsx
// New tab button:
<button onClick={() => setActiveTab('why')}
  className={`${styles.tab} ${activeTab === 'why' ? styles.tabActive : ''}`}>
  Why Recommended
</button>

// New tab content (~line 750):
{activeTab === 'why' && (
  <div className={styles.whySection}>
    {/* Anchor sections from right_panel_contract */}
    {Array.isArray(traceData?.right_panel?.anchor_sections) &&
      traceData.right_panel.anchor_sections.map((sec: any, i: number) => (
        <div key={i} className={styles.anchorBlock}>
          <div className={styles.sectionTitle}>{sec.title || `Image ${i+1}`}</div>
          <div className={styles.kvRow}>
            <span>Match basis</span>
            <span>{(sec.match_basis || []).join(' · ')}</span>
          </div>
          <div className={styles.narrative}>{sec.summary}</div>
          {(sec.top_products || []).slice(0, 3).map((p: any) => (
            <div key={p.sku} className={styles.productReasonRow}>
              <strong>{p.name}</strong>
              <span className={styles.scoreChip}>score {p.score_norm ?? '—'}</span>
              <div className={styles.pillRow}>
                {(p.reasons || []).slice(0, 3).map((r: string) =>
                  <span key={r} className={styles.pill}>{r}</span>
                )}
              </div>
            </div>
          ))}
        </div>
      ))
    }

    {/* Per-product reason codes from displayProducts */}
    <div className={styles.sectionTitle}>All Ranked Products</div>
    {(traceData?.products || []).slice(0, 8).map((p: any) => (
      <div key={p.sku} className={styles.productReasonRow}>
        <div className={styles.rowLeft}>
          <strong>{p.name}</strong>
          <span className={styles.sku}>{p.sku}</span>
        </div>
        <div className={styles.rowRight}>
          <span className={styles.scoreChip}>{p.score_norm ?? '—'}</span>
        </div>
        {p.reason_codes?.length > 0 && (
          <div className={styles.pillRow}>
            {p.reason_codes.slice(0, 3).map((rc: any) => (
              <span key={rc.code} className={styles.pill}>
                {rc.code} ({Math.round((rc.confidence||0)*100)}%)
              </span>
            ))}
          </div>
        )}
      </div>
    ))}
  </div>
)}
```

**Where to get `traceData`:** The DecisionTrace component already fetches from
`GET /api/v1/decisions/{traceId}`. The `products` and `right_panel` fields need to be
**stored in the decision trace record** when the suggest() call completes.

**Backend change needed** (`src/app/routers/recommend.py` ~line 7280 in `suggest()` final
response assembly, and `src/app/routers/chat.py` ~line 1510):

```python
# In the log_trace_event call for "recommendation_result", add:
"products_summary": [
    {
        "sku": p.get("sku"),
        "name": p.get("name"),
        "score_norm": p.get("score_norm"),
        "reasons": (p.get("reasons") or p.get("factors", {}).get("positive") or [])[:3],
        "reason_codes": (p.get("reason_codes") or [])[:3],
        "price": p.get("price"),
    }
    for p in (results or [])[:8]
],
"right_panel_contract": right_panel_dict,  # the full anchor_sections block
```

This way the DecisionTrace modal can render product rankings even when `displayProducts` has
been replaced by a later query.

---

## Sprint 4 — Warranty / Purchase Verification Flow

### The Gap
Order ID field exists in CV triage but:
- No receipt/proof-of-purchase image scan path
- No purchase date → warranty expiry calculation
- No repair cost estimate
- ERP connectors are built but not called during triage

### Files to Touch

#### `src/app/routers/support_complaints.py` — Add warranty eligibility check

After `_order_exists()` returns True (~line 430), add:

```python
# NEW: warranty_check block
_warranty = _check_warranty_eligibility(db, order_id=order_id, issue_type=issue_type)
# Returns: {eligible: bool, expires: str, gap_days: int, advice: str}
if _warranty.get("eligible") is False:
    add("CV12", "warranty_lapsed")  # already defined tag
    signals["warranty_lapsed"] = True
    signals["warranty_expiry"] = _warranty.get("expires")
```

New helper to add (~line 340):
```python
def _check_warranty_eligibility(db, order_id: str | None, issue_type: str | None) -> dict:
    """Look up order purchase date and compute warranty window."""
    if not order_id:
        return {"eligible": None, "reason": "no_order_id"}
    try:
        row = db.execute(
            _text("SELECT purchase_date, warranty_months FROM orders WHERE id = :id LIMIT 1"),
            {"id": order_id},
        ).fetchone()
        if not row:
            return {"eligible": None, "reason": "order_not_found"}
        from datetime import date, timedelta
        purchase = date.fromisoformat(str(row[0])) if row[0] else None
        months = int(row[1] or 12)
        if not purchase:
            return {"eligible": None, "reason": "no_purchase_date"}
        expiry = purchase + timedelta(days=months * 30)
        today = date.today()
        gap = (expiry - today).days
        return {
            "eligible": gap >= 0,
            "expires": expiry.isoformat(),
            "gap_days": gap,
            "advice": (
                f"Warranty valid until {expiry} ({gap} days remaining)."
                if gap >= 0
                else f"Warranty expired {abs(gap)} days ago ({expiry})."
            ),
        }
    except Exception:
        return {"eligible": None, "reason": "lookup_error"}
```

#### `frontend/src/components/RightPanelExtras.tsx` — Show warranty outcome

After result verdict block (~line 720), add:

```tsx
{result && (result as any).warranty_eligibility && (
  <div style={{ marginTop: 8, background: (result as any).warranty_eligibility.eligible
    ? '#ecfdf5' : '#fef2f2',
    border: `1px solid ${(result as any).warranty_eligibility.eligible ? '#86efac' : '#fca5a5'}`,
    borderRadius: 8, padding: '8px 10px' }}>
    <strong>
      {(result as any).warranty_eligibility.eligible
        ? '✅ Warranty valid'
        : '❌ Warranty expired'}
    </strong>
    <div style={{ fontSize: 12, marginTop: 4 }}>
      {(result as any).warranty_eligibility.advice}
    </div>
    {!(result as any).warranty_eligibility.eligible && (
      <div style={{ marginTop: 6, fontSize: 12 }}>
        Options: <a href="#">Request repair quote</a> ·{' '}
        <a href="#">Find service centre</a> ·{' '}
        <a href="#">View trade-in value</a>
      </div>
    )}
  </div>
)}
```

#### DB schema — add `warranty_months` and `purchase_date` to orders table

`alembic/versions/` — new migration:
```python
# Add columns to orders if they don't exist
op.add_column('orders', sa.Column('purchase_date', sa.Date(), nullable=True))
op.add_column('orders', sa.Column('warranty_months', sa.Integer(), nullable=True,
                                   server_default='12'))
```

---

## Sprint 5 — Cart UX + Checkout Flow

### Current Cart State
- `CartPanel.tsx` already calls `GET /checkout_upsell` ✅
- Shows "Recommended Add-Ons" + carousel ✅
- `Checkout` button: `window.location.href = '/ui/checkout'` (Vite proxy → backend)

### What to improve

**File:** `frontend/src/components/CartPanel.tsx`

| # | Change | Lines | What |
|---|---|---|---|
| 1 | Show warranty upsell chip | ~line 140 | If product SKU matches `classify_warranty_candidate`, show "Add protection plan $X" |
| 2 | Persist cart snapshot | ~line 95 `goToCheckout()` | Already does `sessionStorage.setItem` ✅ |
| 3 | Show savings callout | ~line 170 | For upsells cheaper than item: "Save 20% vs buying separately" |
| 4 | Cart item image | `CartItem` type + render | Add `image_url` to CartItem and show 40px thumbnail |
| 5 | Empty cart CTA | ~line 108 | Replace "Cart is empty" with "No items yet — try asking for a product recommendation" + button |

**File:** `frontend/src/App.tsx`

Add `image_url` to `addCartItem` call so CartPanel can thumbnail it:
```tsx
// When user clicks "Add to cart" in product card, pass image_url
onAdd={(sku) => addCartItem(sku, { image_url: prod.image_url, name: prod.name, price_cents: Math.round(prod.price * 100) })}
```

---

## Sprint 6 — Right Panel: What It Does and What's Missing

### How the right panel works today

```
rightPanelMode state (App.tsx line 306):
  'none'         → nothing shown
  'grid'         → product grid (Product[]) 
  'list'         → product list view
  'compare'      → side-by-side compare
  'cv'           → RightPanelExtras mode=cv (complaint triage)
  'cart'         → CartPanel
  'faq'          → RightPanelExtras mode=faq
  'security'     → Decision Trace hint area
  'visual_search'→ RightPanelExtras mode=visual_search → ImageRecommendPanel
  'image_context'→ RightPanelExtras mode=image_context → ImageRecommendPanel

auto-routing via detectPanelMode(query) @ App.tsx line 247:
  "warranty" | "return" | "broken" → mode = 'cv'
  "compare" → mode = 'compare'
  laptop/gaming keywords → mode = 'grid'
  image uploaded → mode = 'visual_search'
```

### Missing modes to add

| Mode | Trigger | Component | Why |
|---|---|---|---|
| `'warranty_outcome'` | After CV verdict w/ warranty check | New `WarrantyOutcomePanel` | Shows eligible/expired + options, replaces generic result block |
| `'repair_quote'` | User clicks "Request repair quote" | Inline fetch to `GET /api/v1/repairs/quote?model=&damage_type=` | Needed for Sprint 4 |
| `'order_history'` | "show my orders" intent | New `OrderHistoryPanel` → `GET /api/v1/orders?uid=` | Context for warranty checks |

### Anchor sections (currently rendered in right panel header)

The right panel already renders `rightPanelContract.anchor_sections` at App.tsx line 1453.
Each anchor section is:
```
title: "MacBook-type laptop (Apple hint)"
summary: "Best 3 matches in $800-$1500. Prioritized for university..."
top_products: [{sku, name, score_norm, reasons}, ...]
match_basis: ["budget_fit", "query_intent", "image_brand_hint", "persona_profile"]
```

These are generated when the user uploads an image AND queries. They provide a transparent
"why these products match this image" explanation. Currently rendered as expandable tiles.

**What to add:** A "View full reasoning" link under each anchor section that opens the
Decision Trace modal pre-focused on the "Why Recommended" tab (Sprint 3).

---

## Sprint 7 — UX Polish for Seamless Shopping

### High-impact, low-effort fixes

**File: `frontend/src/App.tsx`**

| # | Issue | Lines | Fix |
|---|---|---|---|
| 1 | Budget note `⚠️` appears even when budget is fine | ~line 1057 | Only prepend if `budgetAdvice` is non-null AND products are fewer than 3 |
| 2 | `handleSend` needs debounce on clarify chips | ~line 1603 `onClarify` | Add `disabled` state during `isThinking` to prevent double-sends |
| 3 | `setInputValue(q)` shows text in box before send | ~line 1603 | Clear after send completes: `setInputValue('')` in finally block |
| 4 | Right panel label says "Security" for all non-support modes | ~line 1421 | Use `rightPanelContract?.mode` to pick a correct label |
| 5 | Anchor section tiles don't show product prices | ~line 1460 | Add price display to anchor section product list |
| 6 | `tierFilter` state doesn't reset between queries | New `useEffect` watching `displayProducts` | `setTierFilter('all')` on new results |

**File: `frontend/src/components/ImageRecommendPanel.tsx`**

| # | Issue | Lines | Fix |
|---|---|---|---|
| 7 | "Widen search" button has no feedback | ~line 230 | Show loading spinner during widenState fetch |
| 8 | Products show $0 when `price_cents = 0` | ~line 280 `formatPrice()` | Return "Price on request" if price ≤ 0 |
| 9 | No "Add to cart" on ImageRecommendPanel products | Product card render | Add `onAdd` prop (passed from RightPanelExtras → App.tsx addCartItem) |

**File: `frontend/src/components/CartPanel.tsx`**

| # | Issue | Lines | Fix |
|---|---|---|---|
| 10 | "Recommended Add-Ons" loads on every cart render | Line 85 `useEffect` | Already has debounce on `cartSkus` ✅, but add `loadingUpsell` spinner in place of "No suggestions yet" |
| 11 | Carousel cards have no "Add" button | ~line 195 | Add `onClick={() => onAdd(p.sku)}` to each carousel card |

**File: `frontend/src/components/DecisionTrace.tsx`**

| # | Issue | Lines | Fix |
|---|---|---|---|
| 12 | Modal has no keyboard close | ~line 20 | Add `useEffect(() => { const h = (e) => e.key==='Escape' && onClose(); window.addEventListener('keydown',h); return ()=>window.removeEventListener('keydown',h); }, [])` |
| 13 | Security Matrix tab loads stale data if trace changes | Tab render | Re-fetch when `traceId` prop changes |

---

## What the Bitemporal Decision Trace Proves

Every product recommendation and every triage decision is stored with four timestamps:

```
valid_from   → when this decision was VALID in the real world (query time)
valid_to     → 'infinity' until superseded (e.g. product removed from catalogue)
system_from  → when the DB record was written
system_to    → 'infinity' until corrected
```

This means:
- **Regulators** can ask "what did the system recommend to user X at 14:03 on March 10?" — exact answer, immutable.
- **Merchants** can re-open a warranty dispute 6 months later and see the original CV triage result, the exact images, the damage scores, and the routing decision — unchanged.
- **ML teams** can train on "what did we recommend vs what did the user actually buy?" without data leakage from later corrections.

TheTrace modal currently shows this in the **Timeline tab** (event_type rows with timestamps).
The **"Why Recommended" tab (Sprint 3)** will add product-level reasons to the same immutable record.

---

## What We're Building Next and Why

### Priority Order

| Priority | Sprint | What | Why |
|---|---|---|---|
| P0 | Sprint 1 | Escalation room demo polish | Demo blocker — human-to-human chat is the hardest thing for competitors to copy and the most compelling demo moment |
| P1 | Sprint 2 | Min/Recommended tier split UI | Direct revenue impact — showing "this is the minimum that works, here's what you should really buy" increases AOV |
| P2 | Sprint 3 | "Why Recommended" trace tab | Trust builder for enterprise buyers and compliance teams — differentiator against black-box recommenders |
| P3 | Sprint 4 | Warranty eligibility + repair options | Closes the "what happens next?" gap that undermines the whole CV triage value prop |
| P4 | Sprint 5 | Cart polish (images, savings callout, warranty chip) | Conversion rate — small improvements compound |
| P5 | Sprint 6 | New right panel modes (warranty_outcome, order_history) | Needed for Sprint 4 to feel complete |
| P6 | Sprint 7 | UX polish pass | Quality of life — reduces demo friction |

### The demo narrative we're building toward

```
[Shopper]
  "I need a laptop for university gaming, budget around $800"
  → NQE asks: "Do you need Windows or open to Mac?"
  → Shows tier split: Budget fit ($749 Asus) | Performance fit ($999 Lenovo)
  → Shopper adds Lenovo to cart
  → Cart shows: "Recommended Add-Ons: laptop bag, extended warranty plan"
  → Decision Trace shows: "Ranked for gaming+university, matched $800 budget, RTX GPU signal"

[Same Shopper, 3 months later]
  "The screen cracked"
  → Uploads: cracked-mac.jpg
  → CV triage: damage_score 0.85, screen_crack
  → Order ID ORD-XXX: purchase_date 2025-12-15, warranty_months 12
  → Warranty eligible: ✅ 9 months remaining
  → Routing: human_review (accidental damage — policy decision needed)
  → Escalation room opens
  → Support agent: "Hi, was this accidental or a manufacturing defect?"
  → Agent resolves: replacement authorised / repair referral / InsureTech handoff
  → Trace shows the original recommendation + triage + resolution in one immutable record
```

**That is the pitch.** No competitor has the full chain: guided selling → CV triage →
warranty eligibility → escalation → resolution → audit trail.

---

## File Index: Everything to Touch

```
frontend/src/App.tsx
  ~line 310        → add tierFilter state
  ~line 1016       → extract right_panel.lower_tier / higher_tier
  ~line 1057       → budget note condition (only when prods < 3)
  ~line 1453       → add tier split UI block
  ~line 1603       → onClarify: disable during isThinking

frontend/src/App.module.css
  EOF              → add .tierBlock, .tierLabel, .tierPills, .tierPill, .tierPillActive,
                     .tierExplanation

frontend/src/components/EscalationRoom.tsx
  ~line 40         → add incident summary collapse
  ~line 120        → add typing indicator subscription
  ~line 155        → buyer vs staff label logic
  ~line 180        → poll status → resolved banner

frontend/src/components/AdminShell.jsx
  ~line 110        → pass onResolve prop to EscalationRoom

frontend/src/components/DecisionTrace.tsx
  ~line 20         → add Escape key close handler
  ~line 460        → add "Why Recommended" tab button
  ~line 750        → add "Why Recommended" tab content (anchor_sections + per-product reasons)

frontend/src/components/ImageRecommendPanel.tsx
  ~line 42         → add onAdd?: (sku: string) => void to Props
  ~line 280        → "Price on request" when price ≤ 0
  ~line 340        → Add to Cart button per product card

frontend/src/components/CartPanel.tsx
  ~line 6          → add image_url to CartItem type
  ~line 108        → empty cart CTA with recommendation prompt
  ~line 140        → warranty upsell chip
  ~line 195        → carousel Add button

frontend/src/components/RightPanelExtras.tsx
  ~line 720        → warranty_eligibility result block

src/app/routers/support_complaints.py
  ~line 340        → add _check_warranty_eligibility() helper
  ~line 430        → call warranty check after _order_exists()
  ~line 610        → add warranty_eligibility to response dict

src/app/routers/escalation_room.py
  ~line 1200       → enrich seed message with issue_type + damage_types + warranty advice
  ~line 465        → add typing event_type short-circuit

src/app/routers/recommend.py  (chat.py via proxy)
  ~line 7280       → add products_summary + right_panel_contract to recommendation_result trace event

src/app/routers/chat.py
  ~line 1510       → include right_panel dict in the trace event payload

alembic/versions/
  new file         → add purchase_date + warranty_months columns to orders table
```
