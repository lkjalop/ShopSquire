# ShopSquire — LLM Decomposition Power, VLM Speed, Returns Legitimacy & ACL Alignment
**Date:** 2026-07-07 · **Status:** assessment + reordered roadmap (code-verified file:line refs)
**Scope:** (1) reordered lever sets A/B, (2) five additional critical gaps, (3) unrelated-image policy,
(4) FAQ unification, (5) returns/warranty legitimacy vs purchase records, (6) Australian Consumer Law map,
(7) third-party warranty / repair / brick-and-mortar flow. **Not legal advice** — ACL items need counsel sign-off.

---

## 1. REORDERED ROADMAP (what changed and why)

The returns investigation moved two items ABOVE the LLM-planner work: the claim→refund disconnection is a
business-correctness P0 (an "approved" claim goes nowhere), and the purchase-corroboration gaps are both a
fraud hole and the foundation ACL compliance needs. LLM power is still the intelligence-ceiling jump, but it
should land on top of a returns pipeline that actually completes.

| # | Unit | Why this position | Size |
|---|------|-------------------|------|
| **P0** | **B1 — `keep_alive` on every Ollama call** | 30-min change, speeds up EVERYTHING below (incl. damage-triage VLM). Zero risk. | XS |
| **P1** | **R1 — Connect claims → governed refund rail + escalation room** | `returns.submit` auto_approve calls `enforce_action_authority("refund")` (returns.py:305) but NEVER creates a `POST /refunds/request`; `escalation_room` accepts `warranty_candidate` context (escalation_room.py:1507) but returns never invokes it. The pipeline is severed at the money step. | S |
| **P2** | **R2 — Purchase corroboration hardening** (return-window, price match, receipt/proof, purchase date) | `_corroborate_order` (returns.py:43) only checks user+SKU existence. No date/window/price/receipt. Fraud hole AND the ACL foundation (remedy rights hinge on purchase facts). | M |
| **P3** | **R3 — Warranty/returns policy → StoreProfile config** | Warranty prose is hardcoded in recommend.py:8072-8087 ("screen damage not covered") — an agnostic-core liability and un-editable per store. Becomes the single source for FAQ answers, claim assessment, and ACL-mandated notices. | M |
| **P4** | **A1 — Confidence-gated LLM planner in `query_decomposer`** | The intelligence jump. `decomposition_confidence` computed (query_decomposer.py:739) but unconsumed; reuse `intent_decomposer._bind_with_llm` machinery. | M |
| **P5** | **B2+B3 — collapse/parallelize VLM calls + async httpx** | 52-86s multimodal → ~1/3. After keep_alive so gains stack. | M |
| **P6** | **A5 — image facts INTO decomposition** ("like this but cheaper" + photo) | Depends on A1 landing. The multimodal-smartness unlock. | M |
| **P7** | **A2/A3 — LLM ref-binding + NQE use-case inference; B4-B6 cache prewarm, small VLM, num_ctx** | Valuable, not blocking. | S-M |

Lever-set details (A1-A5, B1-B6) with file:line: see §2 of the 2026-07-07 chat assessment; unchanged except order.

---

## 2. FIVE ADDITIONAL CRITICAL ITEMS (code-verified)

1. **Claims→refund disconnection (P1 above).** The governed two-step refund rail exists and is good
   (payments.py:517 request → :545 OWNER-only approve → Stripe; CRITICAL log if money moves unapproved).
   Returns just never calls it. Fix: `auto_approve` → create refund REQUEST (still human-approved at GATE-2);
   `require_human` → escalation_room with `warranty_candidate` + damage context.
2. **Two disconnected fraud systems.** `compute_return_score` (services/returns.py:405) is a lightweight
   delta-sum; the rich `FraudScorer` (fraud_scorer.py:110) has `return_pattern_abuse` (>3 returns/30d, :548),
   `serial_mismatch`, `price_manipulation`, `claim_before_delivery` (:521) — none called by returns. Fix:
   feed FraudScorer's return-relevant signals into the claim score.
3. **`claim_grounding.ground_claim` is designed but unwired** (claim_grounding.py:80 — supported /
   needs_evidence / contradicted with evidence-reliability weighting; docstring says "wiring into the live
   returns flow is the next step"). It is the natural ACL legitimacy engine: wire it as the claim's
   evidence-assessment stage.
4. **No return-window / claim-too-late signal anywhere** — not in returns, not in FraudScorer. Requires R2's
   purchase-date + R3's configurable windows.
5. **Evidence-relevance not explicit in returns.** An off-topic photo (apples on a laptop claim) only surfaces
   indirectly as a CV brand-mismatch delta. `classify_image_relevance` (cv_triage_basic.py:25) exists and is
   profile-driven — call it per evidence image in `capture_evidence`; `off_topic` evidence ⇒ explicit
   `invalid_evidence` signal + "please photograph the actual product" prompt (not a silent score bump).

---

## 3. UNRELATED IMAGES — POLICY BY CONTEXT (test: `apple-red.jpg`)

One classifier (`classify_image_relevance`, profile-driven tokens), three context-dependent behaviours:

| Context | Behaviour | Status |
|---|---|---|
| **Product search** | `off_topic` ⇒ zero ranking influence (recommend_image_similarity_stage.py:80 ✅), honest narration note (recommend_narration_stage.py:253 ✅), + OFFER text-only continuation ("that looks like produce, not something I stock — describe what you need and I'll search by text") | Mostly built; message polish |
| **Returns evidence** | `off_topic` ⇒ explicit `invalid_evidence` claim signal + re-request real photo; repeated off-topic evidence = fraud escalation | **GAP (item 5 above)** |
| **Security (always)** | Steg/QR/adversarial scans run REGARDLESS of relevance — an "innocent" apples pic can carry a payload; off-topic never skips the security lane | Built ✅ (vision.py scans unconditionally) |

Never: hallucinate products from an off-topic image, or silently ignore the upload.

---

## 4. FAQ / POLICY QUERIES — UNIFY ON ONE SOURCE

Current: `policy_faq_answer` (answer_quality.py:100) wired into chat.py:2281 ONLY — /suggest lane misses it.
Topics: shipping/returns/payment/contact from StoreProfile `policy_faq`. Meanwhile warranty answers are
hardcoded prose in recommend.py:8072-8087. Plan:
1. R3 makes StoreProfile the single policy source (returns window, warranty durations, repairer, store locations).
2. `policy_faq_answer` reads it; add `warranty`, `repair`, `store_locations` topics.
3. Wire the same answerer into the /suggest routing lanes (it already has greeting/off-domain lanes — add FAQ).
4. **BSOD-class support queries:** image OCR detecting an error screen (BSOD text) should route to the
   SUPPORT/FAQ lane, not product search and not returns — "this looks like a software fault; try X; if it
   persists it may be a warranty claim" (troubleshoot-first is also the correct ACL posture for suspected
   minor failures). Existing e2e trace: dump/ecommerce/e2e-bsod-faq-trace.png.

---

## 5. TEST-IMAGE PLAYBOOK (dump/test-cv/)

| Image | Exercises | Expected end-to-end |
|---|---|---|
| `apple-red.jpg` | Off-domain gate | relevance=off_topic → no ranking influence → honest note + text-only offer. In returns: invalid_evidence + re-request. Security scans still run. |
| `cracked-mac.jpg` | Damage triage + claim legitimacy | analyze_damage → cracked_screen/high → corroborate purchase (uid+SKU+date+price+window) → policy: physical damage vs defect → `require_human` → escalation room w/ damage context → if approved, governed refund request (OWNER approves). phash recorded; re-submission of the same photo on another claim ⇒ image_reuse +70. |
| `windows-11-bsod.avif` | Support-vs-return routing | OCR → error-screen class → SUPPORT lane (troubleshoot steps), warranty-claim offer if persistent; NOT a product search, NOT an automatic return. |

---

## 6. AUSTRALIAN CONSUMER LAW — OBLIGATION → PLATFORM MAP
*(ACL = Sch 2, Competition and Consumer Act 2010. Engineering map, not legal advice.)*

| ACL obligation | Platform implication | Status |
|---|---|---|
| **Consumer guarantees are automatic & cannot be excluded** (acceptable quality, fit for purpose, match description) — a "no refunds" stance is unlawful | Policy config + FAQ answers must never say "no refunds"; guarantees exist independent of any warranty period | R3 encodes; FAQ must reflect |
| **Major vs minor failure** — MAJOR: consumer CHOOSES refund/replacement/compensation; MINOR: supplier may repair within reasonable time | Claim assessment needs a major/minor classification output (damage triage + grounding feed it); remedy OPTIONS shown must depend on it — platform must not force "repair only" on a major failure | NEW — wire into claim decision |
| **Retailer cannot deflect to manufacturer** ("contact Apple" is an unlawful refusal) | Support/claims flows must never auto-reply "contact the manufacturer"; escalation is internal | Guard in response templates |
| **Proof of purchase — receipt is NOT the only acceptable proof** (bank statement etc. OK) | R2: receipt check must accept alternatives; absence ⇒ ask, don't auto-deny | R2 design constraint |
| **Warranty-against-defects documents need the mandatory ACL text** | If the store surfaces its warranty doc, template must include the prescribed wording | R3 template |
| **Third-party/extended warranties cannot displace ACL guarantees; mis-selling them is a breach** (enforcement precedents exist) | If 3rd-party warranty upsell is ever added: script must state ACL rights exist regardless; never imply remedies require the paid warranty | Guard BEFORE any warranty upsell feature |
| **Warranty period ≠ rights cap** ("reasonable durability" — a premium laptop failing at 13 months can still be a guarantee failure past a 12-month warranty) | Claim assessment must NOT auto-deny on "warranty expired"; expiry is one signal, price/age/durability expectation is another → human review | Claim-decision rule |
| **Repairers: mandatory repair notices** (refurbished parts possible; data may be lost) | Repair-path comms template needs both notices; 3rd-party repairer handoff includes them | R3 + repair flow |
| **Change-of-mind returns: NOT required by law** (store policy optional) | Config distinguishes `change_of_mind_window` (optional, store's choice) from guarantee claims (always) | R3 schema |

### Brick-and-mortar-first assessment + human escalation (the flow you asked about)
Store-first assessment is LAWFUL as triage — but must not become an unreasonable barrier to a remedy
(especially a major failure, where the consumer picks the remedy). Design:

1. Claim intake (photo + description) → CV damage triage + grounding + purchase corroboration (all existing/R1-R2).
2. Platform proposes the LEAST-friction lawful path:
   - clear minor failure → repair offer (with repair notices) at store or mail-in; 3rd-party repairer if configured (R3);
   - suspected major failure → remedy CHOICE (refund/replace) + optional store assessment for verification —
     offered, not mandated;
   - ambiguous/low-confidence/fraud-signals → **human escalation room** (existing, wire from returns) and/or
     store appointment for physical assessment.
3. Every step logged in the decision trace (the bitemporal audit spine) — which is exactly the evidence a
   retailer wants if an ACL dispute reaches the regulator or a tribunal.

The platform's role: assess legitimacy, classify severity, propose the lawful remedy set, and route to a
human for anything binding — the same "AI proposes, policy authorizes, human applies" ladder as pricing.

---

## 7. EXECUTION NOTES
- All returns/ACL work is agnostic-core-safe: policy lives in StoreProfile JSON (electronics.json first),
  code stays vertical-blind, ratchets enforced.
- Refund money-movement remains behind the existing OWNER-only approval gate — nothing here adds autonomy.
- Retention/undo work from 2026-07-06/07 (commits 4f1ec49…e0706b0) is complete except frontend wiring of
  reload-durable undo (cart.undo → persistent banner).
