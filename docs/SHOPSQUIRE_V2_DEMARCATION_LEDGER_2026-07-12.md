# V2 Demarcation Ledger — done vs. left, across all five planning docs (2026-07-12, HEAD e086335)

Reconciles: REBUILD_STATUS_AND_ROADMAP_2026-07-11 · IMPLEMENTATION_SPEC_2026-07-12 ·
CART_LANE_REVIEW_PACKET_2026-07-12 · WORKLOAD_PERSONA_INTENT_ANALYSIS_2026-07-12 ·
HIPPOGRAPH_MARKETINTEL_ASSESSMENT_2026-07-11. One table per doc; then effort, re-verification
battery, and the refactor/rewire/extract/excise verdicts.

## 1. REBUILD_STATUS_AND_ROADMAP (the master arc)

| Item | Status |
|---|---|
| Phases 0–3 (oracle, T0 read-model, T1 taxonomy, T2/T3 classifier) | ✅ DONE (7 commits, live-verified) |
| Phase 3.5 (9 GPT-5.6 findings, attribute layer, holdout, alembic, stock SoR) | ✅ DONE (d77de9b..eb15b28; classifier 82.5% exact / 95.6% lenient w/ semantic candidates) |
| Phase 4 §1 envelope+adapter · §2 evidence+fit · §3 brain (router+plan+core) | ✅ DONE (live acceptance 3/3 known_wrongs) |
| Phase 4 §4 wiring — suggest() dispatch via facade | ✅ DONE (`RECOMMEND_CORE_MODE`, default off) |
| Phase 4 §4 wiring — chat in-process (kill the HTTP hop) | ❌ LEFT → the thin-edge milestone |
| Phase 4 §5 acceptance (3 known_wrongs + zero BLOCKER census) | ✅ DONE (facade-mode census) |
| Phase 5 shadow→canary→primary; §3e retirements (off_catalog regex, _classify_turn_intent, hop, suggest()) | ❌ LEFT = M4; **nothing retired yet** (correct — retirement is gated on promotion) |
| Open items: 89-SKU stock drift before canonical flip · 2 PHM unclassifiable · contract-fork decision | ❌ LEFT (tracked; fork decision = (c) unify-internally, already implemented via legacy_adapter) |

**Superseded by events:** the doc's Phase-4 seed question (grow from recommend_pipeline?) — resolved: core.py grew clean, reuses extracted stages. The cart lane (not in this doc at all) was inserted ahead of M2 on screenshot evidence, user-approved.

## 2. IMPLEMENTATION_SPEC (phase-by-phase execution truth)

| Phase | Item | Status |
|---|---|---|
| A0 | Ungrounded-tenant guard | ✅ 24d7004 |
| A1 | Shadow worker + dead-letter (Redis Stream upgrade) | ✅ a4df40b (**stream upgrade still LEFT** — list queue today) |
| A2 | Facade-mode replay | ✅ a95d552 |
| A3 | Real telemetry (record_event + counters) | ✅ a26e707 |
| A4 | Green ratchets (**CI-mandatory still LEFT**) | ✅ a1c6599 / ❌ CI enforcement |
| B1 | constraints.py ranges + provenance + conflict-clarify | ✅ **e086335 (this session)** — pipeline standardized on predicate lists; conflicts surfaced + clarify |
| B2 | quality.py intrinsic gate (precision@10/NDCG@10/constraint-sat/diversity/empty/unauthorized) extending summarize_run gates_pass | ❌ **NEXT** — still no product-quality gate |
| B3 | Batch get_variants (90-query N+1) + deterministic ORDER BY | ❌ NEXT after B2 |
| C1 | Two-slot intent (requested_product_node + workloads + relationship); quick-win reroute-to-primary-sold-node | ❌ LEFT (quick-win also not done) |
| C2 | Session consumption (deletes FILTER-guard + sold-name-veto) | ❌ LEFT (envelope.session still dead-wired) |
| C3 | Flavour data-move (_SPEC_MAP/_GPU_TIER_VRAM → attribute-registry data) → enroll last 5 modules (intent_resolver, turn_router, core, fit, envelope) in no-flavour | ❌ LEFT |
| D | Soak → canary:1 → ramp → primary → archive | ❌ LEFT (gated: B done + C2 + A3 + A4 ✅) |

## 3. CART_LANE_REVIEW_PACKET (+ GPT-5.6 review-5) — the inserted milestone

All 10 review-5 blockers **closed or contained** across C0 (23c82f6), C1 (cb782be), C2 (dcb7791):
propose→authorize→confirm→execute boundary; risk tiers; atomic/idempotent/stale-guarded apply;
undo stash; DF scoring (electronics stoplist excised); caps/floors; server-side carried set;
chat short-circuit extracted+tested; frontend card+refresh+undo. **LEFT:** ① operator flip
`RECOMMEND_CART_SERVE=shadow` + worker (user, 5 min) ② live phrasing battery + `=on` + re-click
shots 23–27 (§6-D/E matrices) ③ retire App.tsx regex after soak ④ sourcing-consent confirm flow
⑤ cart-lane postflight/metrics on the serve path ⑥ tenant-key migration for draft_orders/undo
(platform debt — new plan artifacts already tenant-keyed).

## 4. WORKLOAD_PERSONA_INTENT_ANALYSIS (the resolver plan)

| Item | Status |
|---|---|
| 1. Typed shared postflight | ✅ (recommendation_postflight, facade-wired) |
| 2. Shadow worker | ✅ (M1) |
| 3. Intent→Requirements Resolver (KB + title salvage + budget-bleed fix + persona rows) | ✅ + **upgraded to ranges/provenance in B1** |
| 4. quality.py intrinsic gate | ❌ = M2-B2 (next) |
| 5. Requirements-grounded loop w/ trusted-source verify + supplier shortfall draft | ◐ PARTIAL (title salvage ✅; external web-leg verify on KB-miss + supplier-draft tie-in ❌ — post-M3 backlog) |
| 6. Decision-trace surfacing ("Why Recommended" incl. conflicts/provenance) | ◐ PARTIAL (extras.intent carries constraints+conflicts+profiles since B1; frontend trace-tab rendering ❌) |
| 7. Prior-subject resolution · offered-candidate clamp · result-count discipline · sealed benchmark | ❌ = M3-C2 territory |

## 5. HIPPOGRAPH_MARKETINTEL (deliberate backlog — nothing blocks the core)

All 7 items ❌ LEFT, by design: taxonomy backbone for recall (safe anytime, ~1 session) ·
findings on node handles · core evidence-leg integration (Phase-5 timing) · light-in-shadow ·
thresholds→data · silent→loud read sweep · model-proposed levers. **No change to sequencing:**
items 1–2 can ride along whenever a session has slack; 3–4 wait for the search lane's shadow.

## 6. How much more work (build-effort, honest)

| Block | Effort |
|---|---|
| M2 remainder: B2 quality.py + B3 batch retrieval | 1–2 sessions |
| Cart go-live ops: shadow soak review + battery + flip + re-click + regex retirement | 1 session (+calendar soak) |
| M3: C1 two-slot + C2 session + C3 flavour-move | 2–3 sessions |
| chat.py thin-edge (hop dies, single router authority, typed panel payloads) | 2–3 sessions |
| M4 soak/canary/ramp/archive | calendar-bound (weeks), ~0.5 session of tooling |
| Backlog: hippograph 1–2, sourcing-consent, Redis-stream, tenant migration, CI-mandatory ratchets | ~3 sessions total, schedulable |

## 7. Re-verification battery for the new roadmap (run at each milestone exit)

1. **Every milestone:** full core+cart suite (~380) + both ratchets (make CI-mandatory — still outstanding) + frontend tsc/vitest.
2. **M2 exit:** quality.py thresholds green on the SEALED labeled set (dev/test split); N+1 query-count assertion O(1); census re-run `shadow_replay --facade-mode` — zero BLOCKER, delegated stable; **conflict-clarify live probe** ("engineering laptop, nothing over 8GB" → asks, never inverts).
3. **Cart go-live exit:** packet §6-D screenshot matrix (23–27 + 3 regressions) + §6-E 20-phrasing Ollama battery + shadow-corpus outcome mix (empty/ops/ambiguous rates) + double-submit already_applied live.
4. **M3 exit:** valorant-class reroute probe (node≠None → device search); multi-turn "the first one" resolves; FILTER-guard + sold-name-veto DELETED with their census cases passing via session; all 17 V2 modules in both ratchets.
5. **M4 gates:** shadow soak (0 queue loss, p95 in budget, quality green) → canary:1 → live acceptance 3/3 re-run at every ramp step.
6. **Standing triage:** pre-existing failures test_hippograph_db(findings), test_supplier_catalog(idempotent) — verified pre-B1 via stash; test_recommend.py engine-aliasing (blocks the 95-test parity oracle); 89-SKU stock drift before `CATALOG_READ_MODEL=canonical`.

## 8. Refactor / rewire / extract / excise — the verdicts

- **EXCISE (only at M4 promotion, none now):** off_catalog regex + negative list → sells_within();
  `_classify_turn_intent`; the chat→HTTP→suggest hop; App.tsx cart regex (after soak passes);
  finally suggest() → recommend_legacy.py frozen. Premature excision = the risk, not the fix.
- **EXTRACT (to DATA, not to new modules):** C3 is the one real extraction left — _SPEC_MAP +
  _GPU_TIER_VRAM into attribute-registry data; hippograph thresholds → thresholds.json (same
  pattern, backlog). No new code-extractions needed from suggest(): the 37 stages stay as-is
  until archival.
- **REWIRE:** chat thin-edge (envelope built once at the edge; router = single authority);
  session dual-read at C2; market-intel as a core evidence leg at Phase-5 timing.
- **REFACTOR: deliberately NO.** suggest() internals stay untouched (ratchet-held, archived at
  M4); apply_cart_ops/handlers already share single decision surfaces; further churn there is
  risk without payoff. The discipline that got findings-never-reopen across 5 reviews is
  exactly this: build the replacement, measure, then excise — never remodel the condemned house.
