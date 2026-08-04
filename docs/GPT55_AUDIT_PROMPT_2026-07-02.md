# GPT-5.5 — Delta audit + browser clickthrough (2026-07-02)

Paste everything below the line to GPT-5.5. It bakes in the two caveats (known pre-existing test
failures; multi-intent is flag-gated) so the audit validates real work instead of re-discovering knowns.

---

You are auditing the ShopSquire branch `wip/docker-real-env-20260213` after a session that fixed a
7-item browser-audit backlog, wired the P0 multi-intent planner end-to-end (backend + buyer card), and
de-noised the test suite. Do a **delta audit** (verify claimed-done vs actually-done) + a **browser
clickthrough** of BOTH the shopper (5173) and admin (3001) surfaces + a **professional UI/UX assessment**,
then **reprioritize the remaining roadmap**.

## Environment / setup
- Backend: http://127.0.0.1:8080 · Shopper: http://localhost:5173 · Admin: http://localhost:3001
- Hard-refresh both frontends first (changes land via Vite HMR; stale bundles will mislead you).
- Auth: set the admin/owner key via the admin "Set API Key" modal (or `localStorage.ss_owner_key`). The
  merchant key is an operator for the market/support endpoints.
- **Multi-intent is flag-gated, default-OFF** (`MULTI_INTENT_PLANNER_ENABLED`). The running backend has it
  ON via env for this session; if `multi_intent` is null in responses, enable the flag (env or
  `config/feature_flags.json`) and restart :8080. Do NOT flip `FULFILLMENT_AUTONOMOUS_RFQ` or the supplier
  transport — supplier send stays OFF/sandbox.

## Caveat 1 — known pre-existing test failures (do NOT re-report as new)
A bare `python -m pytest` shows 7 pre-existing failures, all proven pre-existing (fail at commit
`e11f725`, in untouched code) and NOT demo-breaking. They are documented with root causes in
**`docs/KNOWN_TEST_FAILURES_2026-07-02.md`**. Treat those 7 as known; a regression = any NEW failure
beyond that list. The ratchets (`test_no_flavour_in_core`, `test_no_silent_except_in_core`,
`test_no_untimed_outbound_http`) and touched-area suites (chat, recommend-unit, fulfillment, planner)
are green. If you want a green unit run, note which of the 7 are order-flakes (pass in isolation).

## Caveat 2 — how to actually trigger the multi-intent card (#4)
1. On the shopper, add a laptop to the cart (e.g. search "business laptop", Add one).
2. Then send the mixed turn: *"nah too expensive, actually i need 15 instead. what headsets and hard
   drives for 1200 for those?"*
3. Expect a **MultiIntentCard** in the right panel: "Change [laptop] quantity to 15" [Confirm qty] +
   scoped Headsets/Hard-drives picks (each ≤ $1200) with [Add] + a "value" reframe note. Confirm the
   qty → cart line updates to 15; Add a pick → it joins the cart. Nothing should auto-apply.

## Verify these 8 (claimed done this session) — mark each PASS / PARTIAL / FAIL with evidence
1. **Buyer debug tags hidden** (ProductGrid): no `+in_stock`, `+ram_gb_min:8`, `+embedding_similarity`
   on shopper cards — only friendly labels ("In stock", "Within budget") or nothing.
2. **No bundled demo key** (DecisionTrace): the frontend carries no `local-merchant-key` fallback.
3. **Widen NQE chip** appears when a budget has no in-catalog match (e.g. "work laptops under 40").
4. **Multi-intent buyer card** (see Caveat 2) — the headline feature. Verify amend + scoped add + confirm.
5. **Support-response lane** (admin → Market Intelligence): a "Support response lane" card showing
   objection theme → angle (price→value) → guidance.
6. **Procurement tab badge** (DecisionTrace): a green ● on the Procurement tab when a decision opened a
   procurement journey (run a bulk/procurement query, open the trace).
7. **Admin 401 noise gone**: open the admin app before auth — panels don't fire a burst of 401s / draw
   empty cards; you see "Authenticating…" then the panel once authed.
8. **De-noise fix**: confirm `FULFILLMENT_DEMO_ENABLED`/`FULFILLMENT_AUTO_DRAFT_ON_COMMIT` no longer bleed
   from `.env` into tests (the 3 previously-failing "gated off by default" tests pass).

## UI/UX professional assessment (both surfaces)
- Shopper (5173): visual hierarchy, the multi-intent card's clarity, cart qty×unit display, mobile width,
  empty/zero-result states, security-warning surfacing, any raw tokens/jargon leaking to buyers.
- Admin (3001): panel consistency, the new Support/Market cards, loading/empty/auth states, whether an
  operator can find the procurement journey + decision trace quickly. Flag anything that looks unfinished
  or unprofessional for a pilot.

## Deliverable
1. A delta table: item → PASS/PARTIAL/FAIL → evidence (screenshot ref or exact response/DOM).
2. A prioritized UI/UX findings list (severity + file:line where you can identify it).
3. A reprioritized "what next" list across: multi-intent polish, Track 2b (real clickstream →
   consumer_signals), the market time-rot fix (see known-failures doc), and Track 3 (production
   connectors, gated on secrets). Say what's highest-leverage for a pilot demo vs. production.
