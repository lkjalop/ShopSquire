# ShopSquire — Comprehensive Roadmap & System Assessment (2026-07-13, HEAD 5d69379)

Synthesis of a full codebase sweep: V2 recommendation core (internal), + 4 parallel deep-dives
(procurement E2E, knowledge pool, external search, tech-debt/hang/swallow). Every finding below
was verified at file:line. This supersedes the per-domain roadmap docs where they conflict.

---

## 0. WHERE WE ARE
- **V2 recommendation core: build-complete, 9 review cycles, 0 findings reopened.** Label-free
  quality gate green (constraint-sat ~78%, empty 0%, unauthorized 0%, diversity ~73%). Only the
  LABELED gate (precision@10/NDCG@10) is red — blocked on human labels (USER).
- **Everything else below is the surrounding platform** — mostly built, much flag-gated, with a
  small set of genuinely urgent live bugs found this sweep.

## HOW TO READ THE PRIORITIES
Two axes: **(a) live-and-risky** (ships today, security/money) vs **(b) build-forward** (features
behind flags). Live-and-risky wins regardless of the V2 timeline.

---

## TRACK A — URGENT LIVE BUGS (not V2; verified; ship TODAY) ⚠️
A fail-OPEN cluster: a security/fraud/money signal silently does NOT fire on a DB error, so the
failure looks identical to "all clear." These are in live routers, not flag-gated.

| # | file:line | Bug | Fix |
|---|---|---|---|
| A1 | routers/auth.py:302 | `_check_forced_reauth` returns `False` in `except` → a user you FLAGGED for re-auth is let through on any DB blip (fails OPEN) | fail-CLOSED (return True / require reauth) or log+alert |
| A2 | services/payment_ledger.py:85 | `record_txn` returns `None` on INSERT failure ("best-effort") → the refund-fold ledger under-counts → double-refund/reconciliation risk | money-path append must COMMIT-or-RAISE, not best-effort |
| A3 | routers/fraud.py:93 (+:105,:111,:127) | known-fraud image phash (+80) and velocity/address/trust signals wrapped in `except: pass` → a KNOWN repeat-fraud image scores clean on DB error | log+degrade with explicit alert, or fail-closed to review |
| A4 | services/fraud_scorer.py:360 | `check_phash` returns `(False,0,False)` on DB error — same defect at the service layer | same |
| A5 | routers/auth.py:66 | `_is_https_request` returns `False` on exception → drops the `Secure` cookie flag (session cookie downgradeable to HTTP) | default True / fail-secure |
| A6 | workers/email_connector_worker.py:54,90 | inbound email-security eval swallowed to a metric → a crafted email that crashes the evaluator is NOT quarantined (fails open) | quarantine-on-error |
| A7 | services/payments.py:17-75 | Stripe/PayPal endpoint-integrity / response-anomaly checks swallowed (advisory — does NOT block payment, but a detected tamper emits NO security event) | emit the security event even when advisory |

**Recommended structural fix (closes the whole class):** add a ratchet rule (like the V2
no-silent-except) that BANS `except Exception:` immediately followed by `return False/None/[]/{}`
in `auth.py`, `fraud*.py`, `payment*.py` — forcing log+alert or fail-closed. ~1 session for
A1-A4 + the ratchet.

**Judgement note:** some fraud fail-opens MAY be a deliberate "don't block checkout on a fraud-DB
blip" product choice. That's defensible — but then it must LOG+ALERT, not silently pass. Decide
per-signal: fail-closed (block/review) vs fail-loud (allow + alert). Never fail-silent.

---

## TRACK B — V2 to PRODUCTION (the primary track; mostly calendar, not build)
1. **B1 — Labels (USER).** Fill `tests/golden/relevance_labels.json` (`case_id:turn` keys, grades
   0/1/2, dev/test split, 2 reviewers). Unblocks precision@10/NDCG@10 — the last red gate metric.
2. **B2 — Run the shadow soak.** `RECOMMEND_CORE_MODE=shadow` + run the worker
   (`python -m src.app.workers.recommendation_shadow_worker`) against real/replayed traffic. Exit:
   0 queue loss, stable pending (`XLEN`), bounded p95, unauthorized 0, authz MEASURED on every
   slate (fail-closed if not), labels green. **Run the 5 real-Redis integration tests against the
   soak's Redis first** (they skip without one).
3. **B3 — Canary ladder.** `canary:1 → 5 → 20 → 50 → primary`, each with an auto-rollback
   threshold on the soak metrics. Stable per-tenant:uid bucketing already built
   (recommendation_facade.py `_in_canary_bucket`).
4. **B4 — Retire legacy (deletion, not repair).** Only after primary is stable: delete `suggest()`
   (recommend.py, 12,312 ln), the App.tsx cart regex, `chat.py` double-classifier + internal HTTP
   hop. The split-brain disappears by REMOVAL.

## TRACK C — V2 CATEGORY-CHAIN INCREMENT (GPT-5.6's next taxonomy step; post-canary; DATA/onboarding)
The chain is ~70-80% there. Missing, and how to wire (in ONBOARDING + DATA, never recommend.py):
- **C1 — Node → allowed/required attributes.** Taxonomy nodes carry NO attribute schema today
  (`taxonomy_registry.py` — the `variant_axis` role exists in `attribute_registry` but isn't bound
  to nodes). Add `data/taxonomy_attributes/{vertical}.json` mapping node→{allowed_attrs, required_
  attrs, variant_axes}. Enforce required-attrs at onboarding (classifier already writes
  `product_classification`).
- **C2 — Product/variant identity.** `product_classification` keys on `(tenant_id, sku)` — every
  VARIANT is classified independently, no product-family grouping. Add a product_id grouping so
  "MacBook Air 8GB/16GB" are variants of one product; classify at product level, vary at axis level.
- **C3 — Typed variant axes** (color/size/storage/memory) as first-class options, not free specs.
- **C4 — classified_shown_rate is ALREADY a gate (review-9-followup #A3, ≥0.98)** — this is the
  coverage metric GPT-5.6 asked for; C1-C3 are what raise it honestly.

## TRACK D — PROCUREMENT E2E (genuine FSM built; every external edge sandboxed)
`src/app/services/fulfillment/` — bitemporal FSM via `workflow.transition`, gates 1/2/3 encoded.
**What blocks a live buyer→supplier→GR→invoice journey:**
- **D1 — No real inbound-quote path.** `external_comms.receive_reply:211` is called ONLY by the
  demo endpoint (`fulfillment_cases.py:981`, `FULFILLMENT_DEMO_ENABLED`). Prod dead-ends at
  QUOTE_SENT. Build a supplier-inbox poller OR at minimum a manual "record inbound quote" endpoint.
- **D2 — Sandbox transports.** Supplier send (`transport.py`, `FULFILLMENT_SUPPLIER_TRANSPORT=
  sandbox`) and PO write (`po_transport.py`, `FULFILLMENT_PO_TRANSPORT=sandbox`) transmit nothing;
  SMTP/ERP paths unexercised vs real servers. Wire + test one real transport each.
- **D3 — GR/Invoice have no automated ingestion** (operator-manual only; EDI-856/810 story unwired).
- **D4 — 3-way match + budget + approval-tier gates DEFAULT OFF** → a default demo enforces nothing.
- **D5 — SoD NOT enforced (enterprise blocker).** All guards key on role TYPE, not `user_id`
  (`domain.py:42`). One account can qualify+approve+send+validate+PO+GR+invoice+complete. `dispatch`
  fires approval_granted AND send_approved by the same actor (`fulfillment_cases.py:960`). Add a
  maker/checker guard reading `user_id` (already stamped at `workflow.py:137`).
**Real bugs in procurement (worth fixing even in sandbox):**
- **D6 — fail-OPEN outbound scanner:** `external_comms.py:127-131` — if the supplier-message scan
  raises, it defaults to ALLOW → unscanned message transmits. Fail closed.
- **D7 — budget cumulative bug:** `fulfillment_cases.py:790` `_COMMITTED_SPEND_STATES` lists states
  that DON'T EXIST in `domain.py` (`PO_PROPOSED`/`PO_ISSUED`) → under-counts committed spend → the
  cumulative budget cap can be bypassed. One-line data fix (use real state names).
- **D8 — SMTP no timeout:** `transport.py:74` `smtplib.SMTP` constructed with no timeout → real
  connect can hang (the http timeout ratchet doesn't cover smtplib).
- **D9 — broad swallow:** `workflow.py:165` wraps the whole `transition()` in `except → 409` with no
  log → masks defects.

## TRACK E — KNOWLEDGE POOL (rich but FRAGMENTED; the big cleanup)
- **E1 — FOUR use-case KB files, THREE incompatible schemas** (`data/use_case_kb.json` stale+dark;
  `config/use_case_kb.json` live nested; `config/use_case_knowledge_base.json` live flat game/sw
  workhorse; `config/use_case_knowledge.json` redundant floors). Non-reconciling key namespaces
  (`gaming` vs `gaming_casual`/`gaming_aaa_heavy`) and triple-defined budget floors with DIFFERENT
  values. **Consolidate into ONE normalized use-case registry** (mirror `attribute_registry`'s
  data-driven pattern) + a validation/lint test. Delete `data/use_case_kb.json` (dark).
- **E2 — Game/software detection regex duplicated** in `nqe.py:101` alongside the JSON (add a game
  = edit 2 files). Single source it.
- **E3 — Market-intel spine (~2,500 LOC, 10 modules) BUILT but DARK** by default (signal/analysis/
  pipeline flags off; competitor feed manual-only). Turning it on is a config+scheduler decision,
  not a build — but each detector needs its data source seeded first.
- **E4 — No KB validation/generation pipeline** (all hand-edited JSON, zero writers). Add a lint
  test that fails on cross-file drift + a schema check.

## TRACK F — EXTERNAL SEARCH (~80% built, flag-off; the "Steam auto-refresh" ask)
Governed web-research + SSRF defense + allowlist (`store.steampowered.com` ALREADY enrolled) +
provenance + injection-scan ALL EXIST (`external_research_httpx.py`, `evidence_orchestrator.py`,
`connectors/steam_requirements.py`), shipped FLAG-OFF. Game specs are static; the live Steam lane
is DEAD CODE (`recommend_workload_stage.py:169` calls without `allow_live=True`).
**To make governed spec-auto-refresh live (build the last mile, reuse the rest):**
- **F1 — Offline refresh job** (copy `scripts/pull_competitor_prices.py` pattern) that runs the
  Steam connector with `allow_live=True`, NEVER in the hot path.
- **F2 — Staging + diff + human-review queue** (mirror `competitor_source.record_observation`) — a
  proposed-vs-live spec diff an operator approves.
- **F3 — Write-back** to `use_case_knowledge_base.json`/`steam_fixtures.json` on approval.
- **F4 — Scheduler** (copy `playbook_scheduler`/`sbom_scheduler`). The risky network/governance
  layer is DONE; this is plumbing + a review surface.

## TRACK G — TECH DEBT (paydown; mostly R11-adjacent)
- **G1 — Giant files** = the R11 deletion targets: recommend.py 12,312 · chat.py 2,910 · App.tsx
  3,057. Don't refactor — DELETE at B4 (recommend.py's `suggest()`), decompose chat.py at B4.
- **G2 — Order path swallow cluster** (`routers/orders.py` ~16 broad swallows) + **returns/refund**
  (`routers/returns.py` 8) → a failed side-effect (ledger/reservation/CV-evidence) is invisible,
  orders/refunds can proceed partially-committed. Audit + narrow the catches.
- **G3 — Duplicated CHAOS latency block** `pricing.py:43` ≡ `recommend.py:5031` (+ `time.sleep` in
  an async route when CHAOS on — blocks the whole event loop). Extract to one helper; use
  `asyncio.sleep`.
- **G4 — OAuth token-fetch swallows** (`erp/connectors/http_inventory.py:58`, netsuite, provider_
  sync) → unauthenticated supplier API call on token failure. Fail-closed.
- **G5 — 116 `# type: ignore`** (densest in ML/CV numeric code — low risk, mark of blind spots).

## VERIFIED CLEAN (no action) ✅
- **HANGS:** zero naked-timeout external HTTP calls repo-wide (enforced by
  `test_no_untimed_outbound_http.py` + `http_defaults.outbound_timeout()`). Only exception:
  smtplib in D8. All `while True:` sleep+break; subprocess timeouts; no bare `thread.join()`.
- **CONCURRENCY:** inventory decrement is atomic CAS (`inventory_guard.py:96`), lost-update-safe.
  No naked read-then-write outside the (already-fixed) cart.
- **No TODO/FIXME/HACK** in routers/services/workers/flows.

---

## RECOMMENDED SEQUENCE
1. **NOW (me, ~1 session): TRACK A** urgent fail-open cluster (A1-A4 + the ratchet rule) — live
   security/money, cheapest-to-fix, highest-risk-if-ignored.
2. **NOW (you): B1 labels** — the one thing only you can do; unblocks the V2 gate; parallel to all.
3. **Next (me): D6/D7/D8 procurement real-bugs** (fail-open scanner, budget-state, SMTP timeout) —
   small, concrete, and they harden the procurement path before any demo.
4. **Then: B2 soak → B3 canary** (calendar-gated on B1) while starting **E1 KB consolidation** and
   **F1-F4 external-search last-mile** in parallel (both build-forward, no V2 dependency).
5. **After primary stable: B4 legacy deletion + G1** (they're the same act).
6. **Enterprise track (when multi-tenant prod is real): D1-D5 procurement E2E + D5 SoD + C1-C3
   category chain + orders/returns tenant identity.**

**One-line status:** V2 is build-done and calendar-gated on your labels; the surrounding platform
is mostly built-behind-flags; the single most urgent NON-V2 item is the verified fail-open
security/fraud/payment cluster in TRACK A.
</content>
