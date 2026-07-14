# ShopSquire — IMAGE-Lane Pre-Archive Reassessment + Platform Completeness Gap-Check

*2026-07-15. Grounded in a live VLM battery (qwen3-vl:8b) + direct detector probes + a file:line
map of the recommend/vision path. Answers the two questions the user posed before archiving
`recommend.py`: (1) does the archive order change given what the image test found, and (2) what do
we need so we don't silently lose anything from the platform.*

---

## 0. What this test was for

The plan is to delete the 12,312-line legacy `recommend.py::suggest()` and run one engine (V2
`recommendation_core/`). IMAGE is the **one lane with no V2 implementation** — the facade
hard-refuses image at `recommendation_facade.py:455`, and `incoming_image_payload` is threaded
through ~20 conditionals in the legacy file. So before archiving we characterized the image lane
**live** — valid / wrong / security-compromised images × procurement journeys at changing unit
quantity — to learn exactly what behavior must not be lost.

**Verdict up front:** the test did its job. IMAGE must stay the **last** archive step, but the
reason sharpened: the legacy happy-path is *degraded* (rebuild should fix, not preserve), while the
*security posture* is *load-bearing and mostly correct* (must be pinned as tests before delete). And
the test surfaced **4 bugs that ship in production today, independent of the archive**, which should
land first.

---

## 1. What the live test found (evidence)

| Class | Fixture(s) | Observed behavior | Verdict |
|---|---|---|---|
| **VALID** | apple-mac.jpg | VLM labels `apple mac`; OCR reads `MacBook Pro 15.4"…`; identity=Apple/0.4. Text-only "macbook" → 43 products. | Recognition ✓. Happy-path product count degraded under model eviction (§2.3), not a logic bug — retrieval is model-independent. |
| **WRONG** | apple-red.jpg (food), cracked-mac.jpg | damage_score 0.76 on cracked-mac (correct); off-domain scoring present. | Detection ✓ (full no-hijack pin deferred with the big-image set). |
| **STEG** | 5 LSB payloads | **All 5 detected** — `steg_score=0.52` vs clean images 0.16–0.33. LSB payloads cannot bleed through VLM/OCR by construction. | Detection ✓. **Scale ✗** — 3 of 5 are 2–4 MP → triage hangs >600 s (§2.1). |
| **PCI/PII** | msi-SSN.png, QR-SSN.png | `qr_external_url_detected`+`ssn_detected(19)`+`pii_detected`; chat posture `platform_compromise=True, image_handling_mode=sanitized_visual, image_untrusted=True` + "reupload a clean photo". **Real card + SSNs never reached the shopper response.** | **No shopper bleed ✓.** Correct warn-and-refuse. Secondary issues in §2.6–2.8. |

*(Methodology note: an early "PAN bleed" alarm was a false positive — a greedy `\d{13,19}` regex
matched floats like `damage_score=0.16000000000000003`. The real card/SSN never appeared in a chat
response. Recorded so we don't repeat it.)*

---

## 2. Findings, ranked (file:line)

**Security positives (preserve these):** steg detection catches all 5 payloads; PCI/SSN never
bleeds to the shopper; the warn-and-continue posture (`chat.py:2749-2824`) is the right design.

**Bugs that ship today, independent of the archive:**

1. **Vision triage has no image-size cap → hangs >600 s on 2–24 MP.** No `resize`/downscale in
   `routers/vision.py` / `services/vision.py`; the VLM + OCR run on full-resolution pixels. Dell
   2000² timed out at 600 s; the BSOD fixture is 6000×4000 (24 MP). These are *normal* e-commerce
   photo sizes. **Trivial DoS** (upload a big image, tie up the triage worker) + functional gap
   (can't process real product photos). The **steg detector itself is fast** (numpy, ~2 s on 4 MP) —
   the cost is purely un-downscaled pixels through the model. *Fix: downscale a copy to ~1280 px for
   the VLM/OCR; keep the full-res original for steg/forensic LSB analysis.*
2. **Baseline triage ≈ 23 s even on a 225² image.** Stages run **sequentially** (VLM → OCR → steg →
   QR → adversarial), each its own model call. Over the 5–10 s budget before "large" is even in
   play. *Fix: parallelize the independent stages.*
3. **Router and VLM are the same evictable local model.** `OLLAMA_DEFAULT_MODEL=qwen3-vl:8b` is
   *both* the recommend router and the vision VLM; on a 12 GB GPU it gets evicted when triage loads
   `glm-ocr`. Result: the chat turn right after a triage silently returns **0 products in ~250 ms**
   (chat-hop degrade `chat.py:2109`). Reproduced repeatedly.
4. **Silent swallow + mislabel.** A failed LLM re-rank is caught and falls back to rule ranking with
   **products preserved but no error/retry/degraded flag** (`services/recommendations.py:2208`), and
   the response still reports `decision_mode:"agent_rerank"` when it actually ran rules
   (`recommend.py:9783`). Telemetry lies about which path ran. No `keep_alive`/preload on the rerank
   client, so eviction bites it hardest.
5. **UI collapses three different states into one blank grid.** Model-outage (`degraded:True`,
   `recommend.py:9744` / `chat.py:2109`), genuine no-match (`answer_quality._render_no_match`), and
   security-degraded (`sanitized_visual`) all render as an empty product grid. The flags exist at the
   API; the shopper can't tell "we're having a hiccup" from "nothing matches" from "we couldn't trust
   your image." *The streamed-narration surface (below) fixes the UI half.*
6. **Unredacted SSNs in the operator triage response + event store.** The detector correctly extracts
   19 SSNs into `security.linked_artifact.ssn_hits[]` and returns them verbatim (also persisted under
   `event_id`). Correct *detection*, but unmasked PII in API responses/logs is a compliance smell.
   *Fix: mask to `***-**-0027`, gate the full value behind access control.*
7. **OCR (glm-ocr) hallucinates/loops.** msi-SSN OCR = `"msi msi msi…"`; QR-SSN OCR =
   ```` ```json {text: QR Code}``` ```` repeated. Text extraction is unreliable on these images; the
   PII detection came from the QR/linked-artifact path, **not** OCR.
8. **`pci_card_exposed` not set for the printed card.** The visible card digits (`5481 1234 0987
   4121`) were neither OCR-read nor card-flagged; the image was caught via the SSN/QR path. **Potential
   gap:** a card-printed-ONLY image (no QR/SSN) may slip. *Unconfirmed — needs a card-only fixture.*

---

## 3. Archive-order reassessment

**Before:** "IMAGE is the last lane; rebuild it in V2, then delete `recommend.py`."
**After the test:** same shape, but with **preconditions that reorder the near-term work.**

The key realization: findings 1, 2, 4, 5, 6 are **bugs in code that ships today** — they are *not*
archive tasks, and fixing them does not depend on V2. Meanwhile the legacy image *happy-path* is
degraded enough that a V2 rebuild should **fix, not preserve** it. So:

**Tier 0 — ship now, independent of the archive (they're live bugs):**
- Large-file gate: MP+bytes predictor → downscale-copy-for-VLM (full-res for steg) → warn-consent
  (>10 MP / >8 MB) → reject (>30 MP / >25 MB). *(User directive; time is the budget, not the gate.)*
- Triage stage parallelization (hit the 5–10 s budget on the common case).
- SSN/PII redaction in the triage response + event store.
- `decision_mode` truthfulness + `keep_alive`/preload on the rerank client.
- Streamed-narration surface (loading-screen + severity-tuned warn-and-continue, verdict-templated,
  never payload) — fixes the UI-collapse half of finding 5.

**Tier 1 — IMAGE V2 rebuild (the actual archive prerequisite):**
- Rebuild the image lane inside `recommendation_core/` (quarantine + CV + vision), FIXING the
  degraded happy-path, PRESERVING the security posture, folding in the Tier-0 size-cap.
- **Pin every characterized behavior as a strict test first** (see §4).

**Tier 2 — archive proper (unchanged order, IMAGE last):**
- A step-0: hoist the facade dispatch out of `suggest()` (`recommend.py:4524`).
- Extract SUPPORT/POLICY lanes → canary ladder → relocate the 9 sibling endpoints → delete.
- IMAGE migrates last; `recommend.py` is deleted only after IMAGE V2 is at/above the pinned bar.

---

## 4. Platform completeness gap-check — the "did we miss anything" net

A 12 k-line engine that still ships **cannot be deleted on a code-reading alone.** The safety net is
a **behavioral regression net**: capture the *current* platform behavior at the contract boundary so
any archive/refactor that changes it **fails loudly**. Five layers, and what each stops us from
missing:

**A. Golden I/O corpus per lane.** For each lane (SEARCH, CART, INVENTORY, POLICY/FAQ, PROCUREMENT,
SUPPORT_CLAIM, IMAGE) a set of `input → expected response shape` cases at the `/suggest` +
`/chat/query` boundary. The image lane now has the raw material (this session's fixtures + observed
posture). *Misses without it: any lane whose behavior silently changes when the engine swaps.*

**B. Security invariants pinned as STRICT tests (not xfail).** The image-lane map found the pin for
the security-critical `text_only` context-wipe is an **`@pytest.mark.xfail(strict=False)`**
(`test_recommend.py:519`, `test_security_indirect_prompt_injection.py:71`) — it documents the
behavior in prose but **will not fail if a refactor removes the wipe.** Convert these to strict, and
add strict pins for: steg-detected → quarantine; qr_external → sanitized/refuse; PCI/SSN →
no-shopper-bleed; off-domain → no-hijack. *Misses without it: the security posture, which only fires
on hostile input and is the easiest thing to drop in a rebuild.*

**C. Endpoint contract tests.** Schema-level tests on the `/suggest` and `/chat/query` response so
the facade-vs-legacy dispatch can be swapped with confidence and the 4 frontend callers
(`ImageRecommendPanel.tsx`, storefront `App.jsx`, the widget, an e2e spec) don't break. *Misses
without it: the frontend contract, which must hold until the UI migrates.*

**D. The surface inventory (enumerate everything that dies with the file).** From the archive map:
the **9 sibling endpoints** living in `recommend.py` (`/checkout_upsell`, `/narration/{id}`,
`/why_product`, `/interaction`, `/feedback`, `/cf/train`, `/nqe_slots`, `/nqe_feedback`,
`/admin/nqe_feedback_summary`) die with the *file*, not the function; the chat→HTTP loopback
(`chat.py:1855/1995`); the ~40 tests importing module internals; the **PROCUREMENT/RFQ lane that is
deliberately KEPT legacy** (review-10 decision — advise-only V2 regresses RFQ) and must not be
deleted; and behaviors reachable only via specific flags (`SEMANTIC_ROUTER_MODE`, `RECOMMEND_CORE_MODE`,
`IMAGE_COMPROMISE_HARD_LOCK`, `IMAGE_SIMILARITY_ENABLED`). *Misses without it: an endpoint or a
flag-gated behavior nobody remembered was in the monolith.*

**E. Observability truthfulness.** The net can only measure what the system honestly reports. Finding
4 (`decision_mode` mislabel) and finding 5 (UI state-collapse) mean the system currently
*misreports* which path ran and *cannot distinguish* outage from no-match. Fix these **before**
trusting the net's green — otherwise the characterization pins a lie. *Misses without it: silent
regressions hidden behind inaccurate telemetry.*

**The one-line rule:** *don't delete a behavior you haven't first captured as a test that fails when
the behavior changes.* Everything the legacy image lane does that we want to keep — steg/QR/PCI
detection, no-bleed, no-hijack, damage routing, the quarantine wipe — must exist as a **strict** pin
before `recommend.py` goes.

---

## 5. Concrete next actions (in order)

1. **Tier 0 bug-fixes** (independent of archive, ship-able now): large-file gate, triage
   parallelization, SSN redaction, `decision_mode`/`keep_alive`, streamed narration.
2. **Build the characterization net** (layers A–C, convert the xfail security pins to strict) — this
   is the archive safety net; it must exist before the rebuild.
3. **IMAGE V2 rebuild** against the pinned net.
4. **Archive proper** (A step-0 dispatch-hoist → extract → canary → delete, IMAGE last).

Un-run / deferred (needs the big-image path or a new fixture): full off-domain no-hijack pins on the
2–24 MP set; a **card-only** PCI fixture to confirm finding 8; the quantity-escalation (B2C→RFQ)
measurement across all classes once the model-eviction fix lands and the numbers are trustworthy.
