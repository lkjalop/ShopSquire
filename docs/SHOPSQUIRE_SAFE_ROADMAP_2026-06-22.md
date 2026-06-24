# ShopSquire — Safe Roadmap (2026-06-22)

Sequenced by **risk × dependency**, with safety guardrails baked into every phase. The rule:
*nothing risky ships un-gated; nothing promotes without data; no fallback is removed before parity proves coverage.*

---

## 0. Safety posture of the CURRENT (uncommitted) tree

All changes are either **behavior-preserving** or **gated default-off**, so the working tree is safe to commit and trivial to roll back (nothing committed yet).

| Change | Risk | Why it's safe |
|---|---|---|
| Webhook fail-closed (`payments.py`) | LOW | Only activates when `_is_non_dev_env` AND no secret — dev/test path unchanged; tested both branches |
| Scatter-gather leg-error trace (`recommend_pipeline.py`) | LOW | SHADOW path only (not customer-affecting); behavior identical, errors now visible; 6 tests green |
| `checkout_upsell` → profile accessors | LOW | Electronics tables kept as fallback (additive); 30 upsell tests green; no schema/parity change |
| `from_db` tokenization (`candidate_retriever.py`) | LOW | SHADOW retrieval path; strictly improves recall (0 → candidates); 2 new tests + caption tests green |
| Test-hygiene (cv DB leak, 50-min test, stale test) | LOW | Test-infra only; full suite green |
| Script fixes (gate endpoint, build fail-soft) | NONE | Tooling only, not product code |

**Verification:** full non-browser suite **GREEN (exit 0)** with all of the above; targeted suites green. → Safe to commit on your word.

---

## Phase 0 — Lock in what's done (NOW · zero-risk · offline)

1. **Commit** the test-hygiene + LANE A + demo-readiness fixes (suggested 2–3 commits; `Co-Authored-By` trailer). Clean rollback point before anything riskier.
2. **Bounded-observer prod fix** *(flag-gated)* — wrap `emit_security_event`/anomaly in `asyncio.wait_for(asyncio.to_thread(...), timeout≈2s)` so the observer can never hang a request (the returns/tickets cold-start timeout + the general hang). **Guardrail:** behind `OBSERVER_HARD_TIMEOUT_SEC` (default on, generous); run full suite before/after; revert if any timing test flakes.

## Phase 1 — Demo readiness (SAFE · env + re-run, no risky code)

3. Set demo flags: `RECOMMEND_NARRATION_MODE=skip · RECOMMEND_RETRIEVAL_MODE=shadow · IMAGE_SIMILARITY_ENABLED=0 · EXTERNAL_RESEARCH_ENABLED=0 · PARALLEL_VISION_IDENTITY=false · CV_VISION_ENABLED=0`.
4. `SKIP_OBSERVER_ENDPOINTS=/api/v1/returns,/api/v1/tickets` (demo-only mitigation; **Phase 0 #2 is the permanent fix**).
5. **Prewarm twice**, then re-run `live_demo_gate.py` (now fixed) + Playwright with the flags above. Expect returns/tickets/budget + BSOD<15s to clear (CV_VISION=0 removes the heavy VLM leg).
6. **Re-measure V2 parity** (shadow, measurement-only) now that `from_db` tokenizes — expect non-zero candidates. **Do NOT promote** off `shadow` yet.
7. Record demo **scoped to green**: fast text recs, image quarantine + safe hints, trace/security matrix, supplier draft→human-approval.

## Phase 2 — Capability promotion (GATED · promote only on data)

8. **Visual similarity:** install CLIP/faiss → `build_demo_visual_index.py` → bench → flip `IMAGE_SIMILARITY_ENABLED=1`. **Guardrail:** readiness gate already blocks if index absent; never claim live without a built index.
9. **Retrieval fusion:** with V2 returning candidates, prove parity (top-k overlap, in-budget %, in-stock %, p95) → promote `shadow → fusion` (V2 still re-applies all downstream guards). **Guardrail:** fusion fuses *before* ranking, so guards always run; revert to shadow on any parity regression.
10. **VLM:** warm/swap to a fast model (moondream) + measure → consider `CV_VISION_ENABLED=1` and only then `PARALLEL_VISION_IDENTITY` (with bench data). **Guardrail:** never flip parallel-vision without latency proof.

## Phase 3 — Architecture & agnostic completion (OFFLINE · medium)

11. **Complete A4 agnosticism:** populate `cart_crossover_cents / persona_accessory_slugs / intent_family_keywords / family_complement_matrix` for fashion + pharmacy profiles (electronics fallback removed only after parity test covers them). **Guardrail:** profile parity test must stay green.
12. **Constraint-engine extraction** `recommend.py:4109` → `suggest()` < 7k lines. **Guardrail:** golden-contract + no-flavour + silent-except ratchet tests gate every extraction; extract pure slices behind injected callables (same pattern as the narration/finalizer/retriever extractions).
13. **Trend-pack query bound:** index-/range-bound the `security_event_ingest` dashboard aggregation so it can't degrade with table size (root cause of the old 50-min test).

## Phase 4 — Toward the machine-operated north star (LARGER · phased)

14. **Close the doctrine gap — autonomous exception recovery:** replace remaining "manual review later" paths with bounded autonomous outcomes (retry / switch provider / fallback to rules / defer / substitute / quarantine / refund-within-policy). This is the single line on the deck we flag as "not yet."
15. **Wire the open domains:** shipping (Shippo/label workflow), checkout completion, supplier **M2M PO** (today draft-first only), forecasting/replenishment. Each routes through the **policy/execution gate + audit** — never AI → direct action.
16. **Event-driven backbone:** evolve Redis/Celery toward first-class domain events (OrderCreated / PaymentAuthorized / InventoryLow) so modules decouple — maps to David's EventBridge/Step Functions layer.

---

## Standing safety guardrails (apply to EVERY phase)

- **Flag-gate behavioral/concurrency changes default-off**; flip only with bench data.
- **Never remove an electronics fallback** before schema + parity prove the vertical is covered.
- **Promote retrieval/vision modes only on measured parity/latency**, never speculatively.
- **No consequential action bypasses the policy/execution gate + audit.**
- **Safe-search guardrails** stay: allowlist-only, no PII outbound, SKU-gated, never auto-cart/supplier, web text is data not instructions.
- **PCI honesty:** claim "tokenized, no CHD stored" — never "PCI compliant" without a QSA.
- **Every change ships only when the full non-browser suite is green**; risky hot-path changes get a before/after full-suite run.
- **Commit at each phase boundary** for clean rollback.
```
