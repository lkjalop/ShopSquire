# ShopSquire — Decision Deck v3 (3 slides) + PPTX Build Brief

**Date:** 2026-06-22  **Author:** Claude (Opus 4.8 session)  **Supersedes:** "ShopSquire Decision matrix v2" (4-slide)

This file is a **self-contained handoff**: the three slides (content + ASCII layout +
speaker notes), an honest **platform capability status**, and a **PPTX build brief**
(design tokens, per-slide element spec, and a python-pptx scaffold) so Opus 4.8 — or any
builder — can produce the `.pptx` directly.

> Why 3 slides (down from 4): every architect/buyer asks exactly three questions —
> **Why this approach? · How does it run autonomously without going rogue? · Prove it + what's left?**
> The old "Under Attack" slide folds into Slide 2 as *evidence the boundary holds under hostile
> input* (it argues FOR bounded autonomy; it isn't a separate topic). 4 → 3, no loss of the security moat.

> Reconciliation with David's decks ("Machine-Operated Retail Enterprise" + "Autonomous Retail:
> Candidate Physical Architecture"): those are the **full enterprise blueprint**. ShopSquire is the
> **"Build" column** of David's own Build-vs-Buy map — the **Control Layer + AI Decision Layer**
> (Policy/Authorization Engine, Decision Audit, Fraud, Recommender, Catalog intel, Exception recovery).
> The commodity (Shopify/Stripe/Shippo/ShipBob/Intercom/AWS) is **bought**, not built. The deck adopts
> David's *machine-operated, zero-human-closure* framing and shows ShopSquire as its proven core.

---

## DESIGN TOKENS (for the .pptx)

```
Aspect ratio     16:9  → 13.333in × 7.5in  (EMU: 12192000 × 6858000)
Background       #0B1020  (near-black navy)         — every slide
Card (light)     #F2E6C9  (cream)   text #16213A    — "buy/strong/path" cards
Card (dark)      #111A2E  (slate)   text #E7ECF5    — agent/loop/code cards
Muted sublabel   #8A93A6                            — captions, tags
Accent · Orange  #E8893A   — ShopSquire wordmark, "◄ HERE", Path C, footers, RANKED OUTPUT
Accent · Indigo  #7C6CF0   — POLICY GATE, BITEMPORAL, "bounded autonomy" highlights
Accent · Green   #3FB950   — LIVE / ✓ / "event-driven" callouts, "LIVE WS" dot
Warn · Maroon    #5A1A1A bg / #F2B8B8 text          — "NEVER AI → direct action" box
Caution · Olive  #4D4711 bg / #E9DE9A text          — "manual review later = defect" box
Divider rule     #2A3550  (1pt)
Fonts
  Heading/Display : Space Grotesk (or Clash Display / Familjen Grotesk) — Bold
  Body            : Inter (or Helvetica Neue) — Regular/Semibold
  Mono/Code/Agents: JetBrains Mono (or IBM Plex Mono)
Status glyphs    ✓ done · ~ partial · ✗ not yet · ▶ flow · ▸ step · ◄ marker
```

---

## SLIDE 1 — THE DECISION

**Title:** The Decision  **Subtitle:** *Not a chatbot. Not a SaaS bolt-on. The policy-bounded core of a machine-operated store.*

```
┌──────────────────────────────────────────────────────────────────────────────────────────────┐
│ ShopSQUIRE                                                                            1 / 3     │
│                                                                                                │
│  THE DECISION                                                                                  │
│  Not a chatbot. Not a SaaS bolt-on. The policy-bounded core of a machine-operated store.       │
│                                                                                                │
│  ┌── PATH A ─────────────┐  ┌── PATH B ─────────────┐  ┌── PATH C ───────────────◄ HERE ───┐  │
│  │ Turnkey SaaS          │  │ Configurable          │  │ Machine-Operated Core              │  │
│  │ Zendesk · Einstein    │  │ Ada · Kore.ai         │  │ ShopSquire                         │  │
│  │ ✗ human-gated         │  │ ✗ architecture ceiling│  │ ✓ AI runs it, policy bounds it     │  │
│  │ ✗ no audit trail      │  │ ✗ no bitemporal audit │  │ ✓ every action traced + replayable │  │
│  │ ✗ PII leaves env      │  │ ✗ augments humans only│  │ ✓ PII stays COLO · self-healing    │  │
│  └───────────────────────┘  └───────────────────────┘  └────────────────────────────────────┘ │
│                                                                                                │
│  DOCTRINE   AI is the workforce · Autonomy is BOUNDED · No human closure                       │
│             ("manual review later" = design defect) · Full attributability                     │
│                                                                                                │
│  ┌── BUY THE COMMODITY ───────────────────────┐     ┌── BUILD THE MOAT (ShopSquire) ────────┐ │
│  │ Shopify · Stripe · Shippo · ShipBob ·       │  ▶  │ Policy / Authorization Engine          │ │
│  │ Intercom Fin · AWS managed core · SIEM      │     │ Decision audit (bitemporal WORM)       │ │
│  │   scale · payments · security handled FOR you│     │ Fraud (43 signals) · Recommender ·    │ │
│  └─────────────────────────────────────────────┘    │ Catalog intel · Exception recovery     │ │
│                                                       └────────────────────────────────────────┘│
│                                                                                                │
│                         Buy the commodity. Build the autonomy core.                            │
└──────────────────────────────────────────────────────────────────────────────────────────────┘
```

**Speaker notes (S1):** Three ways to add AI to commerce. Turnkey SaaS keeps a human in
every loop and ships your PII to their cloud. Configurable bots hit an architecture ceiling and
only *augment* staff. Path C is different in kind: the machine *operates* the store, and a
deterministic policy engine bounds every consequential action. We don't rebuild commodity —
Shopify/Stripe/Shippo/AWS are bought. We build the part that differentiates: the control +
decision core. This is literally the "Build" column of David's Build-vs-Buy map.

---

## SLIDE 2 — BOUNDED AUTONOMY IN MOTION

**Title:** Bounded Autonomy in Motion  **Subtitle:** *AI infers & recommends · Policy decides · Execution acts · Audit records — never AI → direct action.*

```
┌──────────────────────────────────────────────────────────────────────────────────────────────┐
│ ShopSQUIRE                                                                            2 / 3     │
│                                                                                                │
│  BOUNDED AUTONOMY IN MOTION                                                                    │
│  AI infers & recommends · Policy decides · Execution acts · Audit records.                      │
│                                                                                                │
│  EVENT / QUERY        QUERY DECOMPOSER          CONCURRENT AGENT SWARM       5-STEP EXEC GATE   │
│  "gaming laptop  ─►  multi-intent split   ─►   each agent PROPOSES, none ─► 1 intent           │
│   $1500-2100" │      → sub-questions            acts: NLP · Fusion ·        2 policy            │
│   OrderCreated │                                Fraud(43) · Ranking ·       3 authorization     │
│   event        │     RETRIEVAL (scatter-       Security_Observer           4 execution         │
│                └──►  gather): DB + vector  ────────────────────────────►   5 audit-log         │
│                      + caption  ⇒ RRF merge    [+ External search:                              │
│                      (per-leg traced)           allowlisted · labeled ·   ─► EXECUTE (if allowed)│
│                                                 OFF by default]            ─► IMMUTABLE TRACE    │
│                                                                                                │
│  4 BOUNDED AI ROLES    Conversational · Predictive · Decision-Support · Optimization            │
│                                                                                                │
│  ╔══ NEVER:  AI ──► direct refund / order / supplier action ════════════════════════════════╗ │
│  ╚════════════════════════════════════════════════════════════════════════════════════════╝ │
│                                                                                                │
│  ┌── UNDER ATTACK: the boundary holds (sale never stops) ───────────────────────────────────┐ │
│  │ Hostile image ► hash·validate·quarantine ► shop path = hints only | sec path = QR/OCR/    │ │
│  │                 steg/GAN ► evidence T1041·T1566.002·T1078                                  │ │
│  │ Supplier BEC   ► SPF·DKIM·DMARC·BIMI ► 15-rule scan ► 5 wire-fraud intents ► verdict      │ │
│  │ CORE RULE  Image = hints only · OCR is data · QR is evidence · Model ≠ authority           │ │
│  └───────────────────────────────────────────────────────────────────────────────────────┘ │
│                                                                                                │
│  EXCEPTION RECOVERY (no human queue)  retry · switch provider · fallback to rules · defer ·     │
│                                       substitute · quarantine · cancel/refund WITHIN policy     │
│                                                                                                │
│            Every consequential action: proposed by AI, decided by policy, recorded forever.    │
└──────────────────────────────────────────────────────────────────────────────────────────────┘
```

**Speaker notes (S2):** A query (or a business event like `OrderCreated`) first hits the
**query decomposer** — multi-intent requests are split into sub-questions so each gets a real
answer. Retrieval is **scatter-gather**: keyword DB + vector + multimodal caption search merged
with Reciprocal Rank Fusion, and every leg is timeout-bounded and **error-traced** (a degraded
leg shows up in the trace, never silently). **External web search** is available but governed —
allowlisted, labeled "not sold here," never auto-cartable, off by default. A swarm of agents each
*propose*; none act. The single most important rule: AI never executes — every refund, order,
or supplier action passes the **5-step gate** (intent → policy → authorization → execution →
audit). The "Under Attack" band proves the boundary holds even on hostile image/email input —
the sale continues while evidence is captured. And exceptions resolve **autonomously** —
"manual review later" is a design defect, not an outcome.

---

## SLIDE 3 — GOVERNANCE & HONEST STATE

**Title:** Governance & Honest State  **Subtitle:** *Provable, replayable, bounded — and clear-eyed about built vs. next.*

```
┌──────────────────────────────────────────────────────────────────────────────────────────────┐
│ ShopSQUIRE                                                                            3 / 3     │
│                                                                                                │
│  GOVERNANCE & HONEST STATE                                                                     │
│  Provable, replayable, bounded — and clear-eyed about what's built vs. what's next.            │
│                                                                                                │
│  GOVERNANCE PLANE   Policy/Authz Engine ▸ MAESTRO agent boundary ▸ Security matrix             │
│  (ATT&CK+ATLAS+OWASP+STRIDE) ▸ Bitemporal WORM (valid+system · 5yr · replay) ▸ Escalation room │
│  Owner = GOVERNANCE SURFACE, never a runtime dependency.                                        │
│                                                                                                │
│  9 MACHINE-OWNED DOMAINS                                                                        │
│   ✓ Storefront   ✓ Orders&Payments (webhook fail-closed)   ~ Catalog   ~ Inventory             │
│   ~ Supplier (draft-first, not yet M2M PO)   ✗ Shipping (unwired)                              │
│   ✓ Support/Returns/Refunds   ✓ Fraud&Trust (43 signals)   ✓ Governance&Audit                  │
│                                                                                                │
│  CAPABILITY STATUS   ✓ Query decomposition LIVE   ~ Scatter-gather retrieval SHADOW (parity-   │
│   gated)   ◷ External search GOVERNED-OFF   ✓ Vision product-identity LIVE (image-hash cached)  │
│   ✓ Agnostic core/adapter (electronics·fashion·pharmacy)                                        │
│                                                                                                │
│  ┌── STRONG TODAY ───────────┐ ┌── KNOWN GAPS ──────────────┐ ┌── MITIGATION ─────────────┐   │
│  │ ✓ Policy + execution gate │ │ ~ Shipping unwired          │ │ → Feature flags           │   │
│  │ ✓ MAESTRO boundaries      │ │ ~ Checkout partial          │ │ → Rules-first routing     │   │
│  │ ✓ Bitemporal WORM audit   │ │ ~ Exception recovery not    │ │ → Staged rollout          │   │
│  │ ✓ Fraud 43 · Recommender  │ │   yet autonomous (the one   │ │ → Buy-wrap commodity      │   │
│  │ ✓ Query decomp · RRF      │ │   doctrine gap to close)    │ │ → Phased to full machine- │   │
│  │ ✓ Agnostic core/adapter   │ │ ~ Supplier M2M · forecasting│ │   operation               │   │
│  └───────────────────────────┘ └─────────────────────────────┘ └───────────────────────────┘  │
│                                                                                                │
│          ShopSquire = the BUILD column of the architecture. Commodity bought; moat real.       │
└──────────────────────────────────────────────────────────────────────────────────────────────┘
```

**Speaker notes (S3):** Everything is provable. Every decision is policy-evaluated, written to a
bitemporal WORM log (what happened vs. when we recorded it — divergence = tampering), and
replayable for five years. Agents are scope-bounded (MAESTRO); threats map to ATT&CK + ATLAS +
OWASP + STRIDE. The owner governs — they're never in the runtime. We're honest about state: the
control + decision core is real and tested; shipping, checkout, supplier M2M, and forecasting are
roadmap. The **one doctrine gap** we name explicitly: exception recovery isn't fully autonomous
yet — there are still human-closure paths, which David's doctrine (rightly) calls a defect.
That's the exact distance to full machine-operation, and we're closing it phased.

---

## PLATFORM CAPABILITY STATUS (honest — for grounding the deck / Q&A)

| Capability | Status | What it does | Wiring (file) | Default |
|---|---|---|---|---|
| **Query decomposition** | ✅ LIVE | Splits multi-intent queries → sub-questions, profile-backed patterns; feeds `answer_composer` so each intent is answered | `services/query_decomposer.py::decompose` (4 call sites in `routers/recommend.py`) | on |
| **Scatter-gather retrieval** | 🟡 SHADOW | Parallel DB + vector + caption(multimodal) retrieval, **RRF** merge, per-leg timeout + **error-traced** | `services/recommend_pipeline.py` via `recommend_retriever_stage.run_retrieval_mode_stage` | `RECOMMEND_RETRIEVAL_MODE=shadow` (promote to `fusion`/`primary` only on live parity proof) |
| **External / internet search** | 🟦 GOVERNED-OFF | Safe web research as a **separate labeled source**; allowlist-only, no PII outbound, SKU-gated, never auto-cart/supplier, web text is data not instructions | `services/external_product_research_service.run_external_research_stage` | `EXTERNAL_RESEARCH_ENABLED=false` |
| **Vision product-identity** | ✅ LIVE | VLM extracts specs/brand from an uploaded image → constraints; image-hash cached (2.5s→0ms on repeat) | `services/product_identity_agent.py`, `services/vision_cache.py` | on (degrades gracefully w/o Ollama) |
| **Policy + execution gate** | ✅ LIVE | `execution_gate.decide()` + action-authority matrix: ALLOW / DUAL_CONTROL / HUMAN_REVIEW / BLOCK; fail-closed | `policy/execution_gate.py`, `policy/action_authority_matrix.py` | on |
| **MAESTRO agent boundaries** | ✅ LIVE | Per-agent role/tool/data scope validation + audit | `security/maestro_boundaries.py` | audit mode default |
| **Bitemporal WORM audit** | ✅ LIVE | valid_time vs system_time, 5yr, replay; decision trace (live WS) | decision-trace + audit-chain modules | on |
| **Fraud scoring** | ✅ LIVE | 43-signal scorer incl. JA3/JA4, GeoIP/ASN; adaptive weights flag-gated | `services/fraud_scorer.py` | adaptive weights off |
| **Agnostic core/adapter** | ✅ LIVE | StoreProfile slots drive electronics/fashion/pharmacy; checkout upsell now profile-backed | `platform/store_profile.py`, `services/checkout_upsell.py` | electronics fallback |
| **Stripe webhook** | ✅ LIVE | **Fail-closed** in non-dev when `STRIPE_WEBHOOK_SECRET` absent (forged event can't mark paid) | `routers/payments.py` | secret required outside dev |
| **Shipping / checkout / supplier M2M / forecasting** | 🔴 ROADMAP | shipping unwired, checkout partial, supplier is draft-first (not autonomous PO), forecasting pending | — | — |

Legend: ✅ live · 🟡 shadow (parity-gated) · 🟦 available, governed-off · 🔴 roadmap

---

## PPTX BUILD BRIEF (for Opus 4.8)

**Goal:** produce `ShopSquire_Decision_Deck_v3.pptx`, 3 slides, 16:9, dark theme per DESIGN TOKENS.
Render the **content blocks** above as styled shapes (do NOT paste the ASCII boxes as text —
the ASCII is a layout guide). Put each slide's **speaker notes** into the slide's notes pane.

**Per-slide element spec**

- **S1:** title + subtitle (top); a 3-column row of equal cards (A/B/C) — A & B cream cards with
  ✗ rows in muted text, **C is the hero**: orange 2pt border + small orange "◄ HERE" tab top-right,
  ✓ rows; a full-width **DOCTRINE** strip (indigo text on slate); a 2-card **BUY ▶ BUILD** row
  (left cream, right slate with orange title) joined by an orange ▶; orange footer tagline centered.
- **S2:** title + subtitle; a left-to-right **pipeline** of 4 slate cards
  (Event/Query → Query Decomposer → Agent Swarm + Retrieval(RRF) [external-search sub-note] →
  5-Step Exec Gate) connected by ▶ arrows; a full-width **maroon "NEVER: AI → direct action"** bar;
  an **UNDER ATTACK** cream panel (2 attack lines + CORE RULE); an **EXCEPTION RECOVERY** slate
  strip; green footer tagline.
- **S3:** title + subtitle; **GOVERNANCE PLANE** strip (indigo ▸ separators); **9 DOMAINS** block
  with ✓/~/✗ glyphs (green/amber/red); **CAPABILITY STATUS** line; a 3-column
  **STRONG / GAPS / MITIGATION** row (green-tint / amber-tint / indigo-tint card headers);
  orange footer tagline.

**python-pptx scaffold (palette + helpers; fill content from the specs above):**

```python
from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR

BG      = RGBColor(0x0B,0x10,0x20); CREAM = RGBColor(0xF2,0xE6,0xC9)
SLATE   = RGBColor(0x11,0x1A,0x2E); INK   = RGBColor(0x16,0x21,0x3A)
LIGHT   = RGBColor(0xE7,0xEC,0xF5); MUTE  = RGBColor(0x8A,0x93,0xA6)
ORANGE  = RGBColor(0xE8,0x89,0x3A); INDIGO= RGBColor(0x7C,0x6C,0xF0)
GREEN   = RGBColor(0x3F,0xB9,0x50); MAROON= RGBColor(0x5A,0x1A,0x1A)
OLIVE   = RGBColor(0x4D,0x47,0x11)
HEAD="Space Grotesk"; BODY="Inter"; MONO="JetBrains Mono"

prs = Presentation(); prs.slide_width=Emu(12192000); prs.slide_height=Emu(6858000)
BLANK = prs.slide_layouts[6]

def slide():
    s = prs.slides.add_slide(BLANK)
    bg = s.shapes.add_shape(1, 0,0, prs.slide_width, prs.slide_height)
    bg.fill.solid(); bg.fill.fore_color.rgb=BG; bg.line.fill.background()
    s.shapes._spTree.remove(bg._element); s.shapes._spTree.insert(2, bg._element)
    return s

def box(s, x,y,w,h, fill=None, line=None, line_w=1.0, radius=True):
    shp = s.shapes.add_shape(5 if radius else 1, Inches(x),Inches(y),Inches(w),Inches(h))
    if fill: shp.fill.solid(); shp.fill.fore_color.rgb=fill
    else: shp.fill.background()
    if line: shp.line.color.rgb=line; shp.line.width=Pt(line_w)
    else: shp.line.fill.background()
    return shp

def text(s, x,y,w,h, runs, size=14, font=BODY, color=LIGHT, bold=False,
         align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP):
    tb=s.shapes.add_textbox(Inches(x),Inches(y),Inches(w),Inches(h)); tf=tb.text_frame
    tf.word_wrap=True; tf.vertical_anchor=anchor
    items = runs if isinstance(runs, list) else [(runs,color,bold)]
    for i,(t,c,b) in enumerate(items):
        p = tf.paragraphs[0] if i==0 else tf.add_paragraph(); p.alignment=align
        r=p.add_run(); r.text=t; f=r.font; f.size=Pt(size); f.name=font; f.bold=b; f.color.rgb=c
    return tb

def notes(s, txt):
    s.notes_slide.notes_text_frame.text = txt

# Build S1, S2, S3 by composing box()/text() per the per-slide element spec + content blocks.
# Use HEAD for titles (~34pt bold), BODY for subtitles (~15pt MUTE) and card text (~12-13pt),
# MONO for agent names / code-like tokens / the pipeline. Footer taglines centered in ORANGE/GREEN.
prs.save("ShopSquire_Decision_Deck_v3.pptx")
```

**Build checklist:** title 32–36pt HEAD bold · subtitle 14–16pt MUTE · card titles 14pt bold ·
body 11–13pt · mono tokens 11–12pt · footer 13pt accent centered · keep ≥0.4in margins ·
✓ GREEN, ~ ORANGE, ✗ MAROON-text · put speaker notes in each slide's notes pane.

---

## SOURCE RECONCILIATION (David's decks → where each concept landed)

| David's concept | Slide |
|---|---|
| Doctrine: AI workforce / bounded / no human closure / full attributability | S1 (Doctrine strip) |
| Build-vs-Buy map ("only build what differentiates") | S1 (Buy ▶ Build) |
| 5-step execution gate (intent→policy→authz→execution→audit) | S2 (gate column) |
| Critical control boundary ("never AI → direct action") | S2 (maroon bar) |
| 4 bounded AI roles | S2 (roles line) |
| Event-driven (OrderCreated / PaymentAuthorized …) | S2 (event input) |
| Autonomous exception recovery (retry/switch/fallback/defer/quarantine) | S2 (recovery strip) |
| 9 machine-owned domains | S3 (domains block) |
| Owner = governance surface, never a runtime dependency | S3 (governance plane) |
| Autonomy-support data (decision_log, policy_evaluation_log, …) | S3 (bitemporal WORM / governance) |
| ShopSquire security moat (image-injection, BEC, ATT&CK/ATLAS) — *ShopSquire-unique, absent from David's decks* | S2 (Under Attack) |
```
