# ShopSquire — Comprehensive Next Roadmap (2026-07-01)

## The one-line thesis
The platform has strong **"AI proposes → Policy authorizes → Automation executes → Audit records."**
The intelligence is **built and governed** — but its value is currently **trapped behind frontend surfaces
and replay data**. So the roadmap is ordered by *unlocking value already built* → *making it real* →
*production connectors* → *autonomy*. Do the cheap, high-visibility, no-secrets work first; gate the
expensive/risky work on secrets and on measurement being real.

Guiding principle (David's deck, verbatim): **build confidence, instrumentation, and governance BEFORE
granting increasing autonomy.** Autonomy (Track 4) must not precede real measurement + identity + the email
loop (Track 3).

---

## Where we are (verified this session)
- **Backend decision surface (M4/M5) COMPLETE**: `sales_response_policy` (discount/price/promotion/reorder/
  emphasis) + M5 consume #1 (margin panel, live) + #2 (ranking nudge, live, gated+reversible+audited) +
  storefront-emphasis endpoint + support-response endpoint + **M2 store** (trend/competitor/offer history,
  auto-populated from the analysis run).
- **Procurement flow SOLID**: quantity parse, widen context, over-budget suppression, cart stepper (backend),
  sourcing product-name, auto-draft on commit, draft visible in admin. Blob→paragraphs fixed.
- **Marketing-BI + security**: traffic-source/channel, verified-human visits, coarse network fingerprint,
  redraft-DDoS guard, poison-resistance (distinct-user gate + neutralisation + AML.T0043 red-team).
- **Deck**: M1/M3/M4/M6/M7 ✅ · M2 ✅ · M5 *decisions* ✅ (surfaces pending). **Phases 1✅ 2✅ 3 substantially
  live · 4–5 pending.**

## What's NOT done (the honest gap)
The **visible surfaces** (frontend) and the **real data** (live ingestion vs replay). Everything the intelligence
decides is either invisible to the buyer/admin, or driven by synthetic replay data. PLUS the newly-identified
**multi-intent gap** (below) — the single biggest "make it not dumb" lever.

---

## PRIORITY 0 — Multi-intent turn handling (the "not-dumb" build) · DO FIRST
**Why bumped to the top:** it's no-secrets, testable end-to-end WITHOUT a browser, and it's the highest-leverage
"make the platform not dumb" work — higher than the remaining frontend polish. A real buyer turn carries several
intents at once ("nah too expensive, actually **15** instead, and what **headsets + hard drives** can I get for
**$1200 for those**?"). Today the platform loses the laptop, applies one global budget, or turns "15" into a new
line. This closes that.

**The gap (from the design discussion):**
- amend the qty of an ALREADY-CHOSEN item via NL ("15 instead") — bind to the last shortlist, not a new line;
- SCOPE a budget to specific lines ("$1200 for those" → accessories only, laptop keeps its context);
- decompose MULTIPLE intents in ONE turn (amend + add-lines + scoped-budget + objection);
- an **adversarial scatter-gather guard** that rechecks the assembled plan before it's shown.

**Architecture — "AI proposes, deterministic authorizes" applied to parsing (hybrid, not pure-LLM/pure-regex):**
1. Deterministic extractor pulls structural primitives (extends query_decomposer/order_split).
2. A constrained LLM (or classifier) resolves the ambiguous BINDING → forced schema
   `{amendments:[{ref,new_qty}], new_lines:[{category,qty}], budget_scopes:[{applies_to,min,max}]}`.
3. Deterministic layer VALIDATES the plan (grammar rules: budget-after-category binds to those categories;
   "N instead" binds to the last-referenced item; qty 1–500) → violate a rule ⇒ fall back or ASK.

**Build (agnostic-core, testable):**
- `intent_decomposer.py` — turn → {amendments, new_lines, budget_scopes}; deterministic primitives + optional
  schema-validated LLM binding. Vertical-blind.
- `scatter_gather_guard.py` — per-line verification: category match, budget scope, qty sanity, context survival,
  no cross-contamination. Pure, agnostic. Fail ⇒ re-ask/fallback, never assemble a wrong plan.
- Wire scoped budgets into `order_split` (per-line budget) + bind qty-amendments to the last shortlist.

**Guardrails:** never silently drop a line/qty; never guess on money/qty (confirm card on low confidence);
reversible via the existing supersede ladder; confidence-gated. **Effort ~2–3 days; risk low; no browser needed.**

---

## TRACK 1 — Demo Completeness (make the built intelligence VISIBLE) · 1a/1c/1d DONE · 1b/1e = browser
**Why first:** highest ROI, lowest risk, **no secrets**. A demo is judged by what's on screen; the value is
built but invisible/rough. This is a **paired browser session** (the `.tsx` surfaces can't be verified blind).

| # | Item | Why | Reads |
|---|---|---|---|
| 1a | **Storefront emphasis banner** | Shows the market-intel loop changing the *customer-facing* storefront — the deck's whole point (value/urgency/features copy) | `GET /market/storefront-emphasis` |
| 1b | **Support-response surface** | Makes the M5 support lane visible ("price objection → lead with value") | `GET /market/support-response` |
| 1c | **Cart qty × unit display** | Kills the "$7,154 mystery" — the #1 "looks-dumb" screenshot complaint | cart bundle rows |
| 1d | **Image off-domain wording (D)** | Rejected image → "text-query results; image was off-topic", not "matches for this image" | `image_relevance=="off_topic"` |
| 1e | **Decision-Trace procurement visibility (E)** | The 006 complaint — surface the procurement journey by default, not hidden behind a tab | existing durable events |
| 1f | **Show the ranking nudge + demand-aware discount live** | Proves Phase-3 is *live*: with replay on, the list reshuffles for surplus/OOS and the margin panel shows the "Demand-aware call" | already wired |

**Effort:** ~1–2 days paired. **Risk:** low. **Blocks nothing; unblocks a compelling demo.**

---

## TRACK 2 — Demo Realism (signals, not just replay) · DO SECOND
**Why:** the adaptation is driven by synthetic replay; the marketing-BI panels (`network-breakdown`) are empty.
Make it *feel* real without secrets.

| # | Item | Why |
|---|---|---|
| 2a | **Seed synthetic traffic-source captures w/ network fingerprints** | `network-breakdown` + verified-human + channel BI currently show `coverage_ratio: 0.0` — no captured signals. Seed a handful so the panels are non-empty for the demo |
| 2b | **Buyer storefront emits `consumer_signals` on real clicks (UTM capture)** | Closes the loop: real browsing → demand/channel/network populate from actual demo interactions, not replay |
| 2c | **Set `ADAPTIVE_MIN_CONFIDENCE` (confidence floor)** | Deck Module-7 "Confidence Thresholds" — a real bar before the ranking/discount gate fires. Deployment config, not code |

**Effort:** ~1–2 days. **Risk:** low–medium.

---

## TRACK 3 — Production Foundations · GATED ON SECRETS/PARTNERS
**Why:** to go beyond sandbox. Each is effortful and **needs the user's credentials/partners** — can't be
done in-session. Order within the track by dependency.

| # | Item | Why / unblocks |
|---|---|---|
| 3a | **Real SMTP + SPF/DKIM/DMARC** | The procurement loop's external leg — real supplier RFQ send (still behind GATE-2 human approval). Deliverability + anti-spoof |
| 3b | **Inbound supplier reply loop (IMAP/Gmail OAuth + parse)** | Closes RFQ↔quote → enables quote comparison + the *full* procurement journey end-to-end (#8 inbound closed-loop) |
| 3c | **Real catalog/pricing/inventory ingestion** (Shopify/ERP/CSV) | Replaces seeded stock → real availability, real margin, real over-budget/transfer logic |
| 3d | **Real market-intel ingestion** (GA4/Segment/competitor feeds) | Replaces replay → real demand/competitor/seasonal signals feeding M3→M2→M4/M5 |
| 3e | **Auth/SSO/IdP (durable per-user identity)** | Unblocks the **#3 Tier-1 SoD gate** (was blocked on identity), production-grade memory (per the memory-persistence gap), and real audit attribution |
| 3f | **Payment/checkout (Stripe)** | Only if going beyond sandbox commerce |

**Effort:** weeks. **Risk:** medium. **Dependency:** 3b needs 3a; 3d strengthens Track 4.

---

## TRACK 4 — Autonomy Rollout (Phases 4–5) · GATED ON TRACKS 1–3 + governance
**Why last:** the deck is explicit — measurement + governance + identity must be real before autonomy.
Autonomy on synthetic data or without identity/rollback proof is the deck's "confidently make things worse."

| # | Item | Why / guardrail |
|---|---|---|
| 4a | **Keep autonomous supplier send OFF** until 3a/3b verified | Safety — no external commitment without a verified send + reply loop |
| 4b | **Phase 4 — bounded autonomous offers/bundles/segment campaigns** | Deck Phase 4; each under the existing gate + kill switch + experiment measurement (M6) |
| 4c | **Phase 5 — closed-loop learning** (provenance-weighted reward from conversion / supplier-reply / stock / objection outcomes), THEN close the citation-trust loop | Deck Phase 5 — the learning flywheel. **The citation loop stays INERT until anti-poison guards exist** (closing it lets fake outcomes move agent trust — a poisoning surface). Do NOT "fix the dead code" |

**Effort:** large, sequential.

---

## Cross-cutting / Ops (do continuously)
- **`config/feature_flags.json` is a fragility hotspot** — truncated twice this session by parallel edits,
  silently disabling procurement. Treat it as source-of-truth: commit every change, avoid parallel edits,
  `git checkout HEAD -- config/feature_flags.json` restores it.
- **Keep agnostic-core discipline** — new modules graduate into `_CORE_MODULES`; ratchets stay green.
- **Autonomy stays default-OFF + flag-gated + kill-switched + audited** — never regress the governance.

---

## Recommended sequencing (next ~2 weeks) — REORDERED
0. **NOW — Priority 0: Multi-intent turn handling** (no browser, no secrets, highest "not-dumb" leverage):
   `intent_decomposer` + `scatter_gather_guard` + scoped-budgets + qty-amendment. → *the platform stops
   being dumb on real buyer turns.*
1. **DONE this session — Track 1 visible surfaces 1a/1c/1d**: storefront emphasis banner, cart qty×unit,
   off-domain image wording. **Remaining 1b/1e/1f = the paired-browser session** (support surface, trace
   visibility, show the live nudge/discount).
2. **Then Track 2**: seed network signals, wire real click capture, set the confidence floor. → *the demo
   feels real, panels non-empty.*
3. **Decision gate**: is this a *sandbox demo* or a *production pilot*? If pilot → start **Track 3** (secrets)
   in priority order 3a→3b→3c/3d→3e. If demo → stop after Track 2 and frame the rest honestly.
4. **Only after Track 3 is real** → **Track 4** autonomy, one phase at a time, measured by M6, governed by M7.

## Priority order at a glance
**P0 Multi-intent (now)** → **Track 1 browser 1b/1e/1f** → **Track 2 realism** → *[demo vs pilot fork]* →
**Track 3 secrets** (3a SMTP → 3b inbound → 3c/3d ingestion → 3e auth) → **Track 4 autonomy** (4a keep-off →
4b Phase-4 → 4c Phase-5).

## The single most important "why"
You've built the hard part — **governed intelligence that proposes, is authorized, executes bounded, and
audits**. The remaining value is **unlocking it on the surfaces** (Track 1) and **feeding it real signal**
(Tracks 2–3). Autonomy (Track 4) is the *payoff*, not the *next step* — it's earned once measurement and
identity are real. Rushing autonomy before that is the one move the deck explicitly warns against.
