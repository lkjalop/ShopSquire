# ShopSquire — Agnostic-Core Roadmap & Review Pack (for GPT-5.5)

Date: 2026-06-18 · Branch: `wip/docker-real-env-20260213` · For peer review before continuing.

This pack is **falsifiable**: every claim carries a file:line anchor. Re-check with `rg -n`
before patching — the tree moves. Reviewer goal: find the holes in the plan, the ordering,
the risk register, the external-data design, and the David-autonomy tie-in.

---

## 0. Where we are (shipped this session, all committed + parity-verified)

| Commit | What | Verify |
|---|---|---|
| `15ef7c7` | Fail-close authority matrix + egress allowlist + model-ladder doc | `tests/security/test_failopen_defaults.py` |
| `e23cab8` | Determinism **harness** | `scripts/determinism_check.py` |
| `de2fb92` | Determinism doc + P0 exit bar + known-flaky list | `docs/DETERMINISM.md` |
| `ce63438`…`af10f32` | **P1**: 8 answer-shapers → `recommend_response_finalizer.py`; single `finalize_response_payload()` pipeline | `tests/services/test_finalizer_characterization.py` |
| `fceeca7` | **P2**: `products` +`product_type/brand/category/attributes` + 6 autonomy-support tables | `tests/test_schema_contract.py` |
| `935bbc3` | **P3+P4-seed**: `execution_gate.decide()` (evaluate + always-log) | `tests/security/test_execution_gate.py` |
| `ed2126c` | **P5 scaffold**: consolidated electronics StoreProfile (the excision map) | `config/store_profiles/electronics.json` |

`recommend.py`: **14,918 → 14,689** and shrinking. Moat-first reorder confirmed:
control/evidence/security up, recommendation polish down.

---

## 1. The agnostic line (verified, not assumed)

Grep counts proving the boundary:
- `src/app/routers/recommend.py` — **~115 lines of electronics flavour** (rtx/gtx/vivobook/macbook/gpu/240hz/refresh_hz). **← excise.**
- `src/app/flows/nqe.py` — **0 flavour** (pure mechanism).
- `src/app/services/recommend_pipeline.py` — **0 flavour** (scatter-gather is agnostic).

The ~18 agents are **role-based mechanisms** (`Candidate_Retrieval_Agent`, `Product_Ranking_Agent`,
`Spec_Filter_Agent`, `Device_Match_Agent`, `Budget_Guard_Agent`, `Price_Filter_Agent`,
`Catalog_Guard_Agent`, `Intent_Guard_Agent`, `Product_Identity_Agent`, `Policy_Gate_Agent`,
`Security_Gate_Agent`, `Security_Observer_Agent`, `Steg_Detector_Agent`, `Adversarial_Image_Agent`,
`Text_Fusion_Agent`, `Checkout_Upsell_Agent`, `Support_Playbook_Agent`, `Support_Routing_Agent`).
**They consume flavour; they do not contain it.** Only the flavour moves into StoreProfile.

---

## 2. Excision map — electronics flavour → `config/store_profiles/electronics.json`

| Flavour | Today (file:line) | → StoreProfile slot | How to excise |
|---|---|---|---|
| Brand label patterns | `recommend.py:~8572` `_BRAND_LABEL_PATTERNS` | `brand_label_patterns` | read via `StoreProfile.get()` |
| Brand price floors | `recommend.py:~8645` `_BRAND_PRICE_FLOORS` | `brand_price_floors_usd` | read via profile |
| Use-case patterns + dGPU set | `query_decomposer.py:68-83` `_USE_CASE_PATTERNS`, `_DGPU_USE_CASES` | `use_cases` | inject patterns from profile |
| Spec regexes (refresh/ram/storage/gpu) | `query_decomposer.py:134-165` `_extract_hard_constraints` | `spec_constraints` | compile from profile |
| Use-case→spec floors | `use_case_advisor.py` + `recommend.py:9053-9065` | `use_cases[*].spec_floors` | read via profile |
| NQE domain questions | `flows/nqe.py:907-953` (hs/uni/corp gate + `_template_field_map`) | `use_cases[*].nqe_question` | data-drive the gate |
| product_type rules / primary types | `config/store_vocab.json` (already config) | `product_type_rules`, `primary_types` | merge into profile |
| CV views/damage/OCR | `config/verticals/electronics.json` (already config) | `cv_returns_pack` | reference |

**Excise ONE slot per commit, each behind a characterization test.** First proof slot:
`brand_price_floors_usd` (smallest blast radius). Then `pharmacy.json` (same shape) = agnostic proof.

**New module to create:** `src/app/platform/store_profile.py` — `load_profile(tenant_id|vertical) → StoreProfile`
(`@lru_cache`, **must be added to the determinism fixture's cache-clear list** — see §6).

---

## 3. Roadmap (moat-first), per phase, with anchors

### P1 — One-writer finalizer ✅ DONE
- `src/app/services/recommend_response_finalizer.py` owns 8 pure transforms + `finalize_response_payload()`.
- Single call site `recommend.py:~14014`. **Follow-up:** route `_with_trace` (`recommend.py:~348`) early-return transforms through the same pipeline (deferred — ordering trap).

### P2 — Schema + autonomy tables ✅ DONE
- `db.py:838-856` (cols) + `db.py:~288` (autonomy tables). **Create:** `alembic/versions/20260618_products_type_attributes.py` (Postgres parity — **MISSING, add**). **Wire:** `scripts/seed_demo_data.py:~314` to populate `product_type/brand` at seed; `src/app/erp/sync.py:~305` to populate from feeds.

### P3 — Execution gate ✅ facade DONE; migration PENDING
- `src/app/policy/execution_gate.py` `decide()`. **Migrate the 9 callers** to it (strangler):
  `billing.py:52/178/197/212`, `orders.py`, `returns.py`, `auth.py:794`, `privacy.py`, `events.py`,
  `inventory_agent.py:974-1130`. Each migration behind a test that asserts a `policy_evaluation_log` row.

### P4 — Control-layer eval + provenance (EXPAND)
- Seeded by `tests/security/test_execution_gate.py`. **Create** `eval/datasets/policy_decisions.jsonl`
  (action → expected verdict) + a scorer in `eval/`. **Provenance:** tag retrieved chunks in
  `rag/retrieve.py:43-66` + `agentic_rag_pipeline.py:158-178` with `{source, trust, ingestion_hash}`
  (CaMeL data≠instruction). **Create** `src/app/security/text_feature_gate.py`.

### P5 — StoreProfile + pharmacy proof (IN PROGRESS)
- Scaffold done. **Next:** `store_profile.py` loader → wire first reader → iterate → `config/store_profiles/pharmacy.json`.

### P6+ — demoted: NQE refinement (`recommend.py:9031-9052` real bug, P3-era), V2 parity (`recommend.py:~6604`), text/RAG depth.

---

## 4. Parse-before-LLM (the input contract — what must happen before a prompt)

Today this is partial and scattered. The target pipeline (every text/image/RAG/memory input):

```
raw input
  → 1. NORMALIZE        unicode/homoglyph/zero-width/encoding   (deps.py:121-123 partial)
  → 2. PII/PCI SCRUB    scrub_pii                                (deps.py:193-216)
  → 3. INJECTION GATE   commerce_request_guard (text)            (security/commerce_request_guard.py:44-152)
                        image_feature_gate (image)               (security/image_feature_gate.py:66-130)
                        text_feature_gate (RAG/memory) — CREATE
  → 4. TRUST-LABEL      {source, trust_tier, allowed_use:evidence|instruction}
  → 5. STRUCTURED ENV   typed object, never raw string, into the LLM context
```

**Rule (CaMeL / David L-K):** retrieved/OCR/QR/email/memory text is **data, never instruction**.
**Gap:** steps 4-5 don't exist; `rag/guardrails.py` is a 2-pattern list. **Create** the envelope +
`text_feature_gate.py`. **Anchor for the LLM-summary prompt build:** `recommend.py:4442` `_build_knowledge_answer`,
`recommend.py:~4710` `_summarize_results` — these must consume the *labelled envelope*, not raw fields.

---

## 5. Question decomposition: core logic + ecommerce adapter

- **Core (agnostic):** `query_decomposer.py:289` `decompose()` → `QueryPlan{intent, sub_questions, hard_constraints, is_compound}`. Keep.
- **Adapter (flavour):** the *patterns* it matches (use-cases, spec regexes, brands) move to StoreProfile (§2).
- **Design:** `decompose(query, *, profile)` — the engine stays; the profile supplies vocab. A pharmacy
  profile supplies `{antihistamine, drowsy/non-drowsy, age_restriction}`; electronics supplies `{gaming, rtx, refresh_hz}`.
- **Consumed by:** `answer_composer.py:98` `needs_composition`, `recommend.py:~9031` use-case resolution
  (the real NQE bug lives here — `detected_use_case=None` reaches `NQEInput` at `recommend.py:10107/12812`).

---

## 6. Testing strategy (to surface debt / hangs / wiring / agent behaviour)

| Test | Purpose | File |
|---|---|---|
| Determinism harness | order-dependence + anti-masking gate | `scripts/determinism_check.py` ✅ |
| Characterization | parity before every refactor | `tests/services/test_finalizer_characterization.py` ✅ |
| Schema-contract | phantom-column bug class | `tests/test_schema_contract.py` ✅ |
| Control-layer eval | gate decides correctly + always logs | `tests/security/test_execution_gate.py` ✅ |
| **Flag-matrix** | run COMMERCE_* on AND off (gated paths rot) | CREATE |
| **Agnostic test** | run core against `pharmacy.json` — proves core/adapter line | CREATE |
| **Silent-hang test** | scatter-gather + LLM calls have timeouts; assert bounded wall-time | CREATE (see §7) |
| **"Guard fired" asserts** | not "didn't crash" — assert `data_integrity`/`compound_answer`/gate-verdict set | CREATE |
| **Tool-isolation / SoD** | each agent has least-privilege; no agent can call a privileged tool without `decide()` | CREATE |
| **Agent-behaviour / red-team** | injection in product desc / review / RAG / memory / supplier email | extend `security/redteam/suite.py` |

---

## 7. Risk register / tech-debt (file:line, severity)

1. 🔴 **`orchestrator.py` is a SECOND monolith** — **4,009 lines, 241 `except` blocks.** Biggest silent-fail surface; the roadmap barely touches it. Strangle after recommend.py.
2. 🔴 **Scatter-gather has no timeout** — `recommend_pipeline.py:250` `asyncio.gather(*scatter_tasks, return_exceptions=True)` with **no `wait_for`/`timeout`**. A hung leg (slow vector DB / LLM) → **silent hang**. *Fix:* wrap each leg in `asyncio.wait_for(...)` with a per-leg budget.
3. 🟠 **375 `except: pass` in recommend.py** — guards fail open & invisible. Instrument the *critical-path* ones (log on except).
4. 🟠 **Frontend monoliths** — `DecisionTrace.tsx` (3,055 lines), `App.tsx` (2,225). Refactor candidates; not breaking, but fragile. WS path `DecisionTrace.tsx:516` now correct (`/events/ws`) ✅ (was a known bug).
5. 🟠 **Determinism not fully solved** — ASUS still order-dependent (engine-alignment); tracked in `docs/DETERMINISM.md`. New `store_profile` `lru_cache` must join the clear-list or it re-introduces leakage.
6. 🟠 **Gate not yet enforced everywhere** — `decide()` exists but 9 callers still hit the old mechanisms; "policy-bounded" is partial until migrated.
7. 🟡 **Dual schema drift** — `db.py` (SQLite/tests) vs alembic (Postgres). Postgres migration for P2 cols is **missing**.

---

## 8. External data: loyalty / CDP / warehouse integration (the new ask)

**Design principle (David build-vs-buy + ports): ShopSquire does NOT become a CDP or warehouse — it adapts to them via `CustomerContextPort`, behind consent + the execution gate.**

```
Loyalty / CDP / Warehouse  →  [ CustomerContextPort adapter ]  →  consent-scoped, redacted
  (Everyday Rewards, Flybuys,        (NEW: src/app/ports/             PersonalizationContext
   Kroger/Nectar/Payback,             customer_context.py +            {source, consent_basis,
   Segment/mParticle,                 adapters/*)                       ttl, redaction_state,
   Snowflake/Databricks/Athena)                                         allowed_use}
                                                                              ↓
                                            evidence bundle  →  ranking + "why" (reason codes)
```

- **Loyalty (AU: Woolworths Everyday Rewards, Coles Flybuys; US: Kroger 84.51°/Nectar360; EU: Payback):**
  ingest *consented* segment + purchase-history *summaries* (never raw PII into prompts). Adapter maps
  their API → `PersonalizationContext`. Reason codes: `prior_purchase_compatible`, `loyalty_tier`, `viewed_brand_preference`.
- **CDP ([mParticle](https://www.mparticle.com/integrations/)/[Segment](https://genesysgrowth.com/blog/best-alternatives-for-twilio-segment)):** real-time profile/consent; consent framework ([Didomi](https://insiderone.com/best-customer-data-platform/)-style) gates `allow_personalization`.
- **Warehouse ([Snowflake](https://celerdata.com/glossary/databricks-and-snowflake-a-comprehensive-comparison)/[Databricks](https://peliqan.io/blog/databricks-alternatives-competitors/)/Athena):** batch features via **reverse-ETL** ([Hightouch/Census](https://www.digitalapplied.com/blog/marketing-data-pipeline-etl-2026-modern-data-stack-reference)) into a read model; **caveat — reverse-ETL is not real-time**, so session signals stay local, warehouse features are pre-computed. AWS zero-ETL / SageMaker Lakehouse is the emerging real-time path.
- **3rd-party research data:** same port, marked low-trust + consent-scoped; **never** lets external data drive a *policy* decision (data≠instruction).

**APIs/things to consider:** OAuth2/OIDC per loyalty provider; consent receipts (ISO/IEC 29184); data-residency (`policy/data_residency.py:3-38` already models cross-border); reverse-ETL latency; PII minimization (only summaries/segments cross the boundary, enforced by `security/provider_boundary.py:22-42`).

---

## 9. Agentic AI behaviour · tool isolation · segregation of duties (David tie-in)

David's invariant (decks pg 5/7/13): **AI infers → policy decides → execution acts → audit records.** Map:
- **Tool isolation:** each agent gets least-privilege; **no agent calls a privileged tool directly** — it must go through `execution_gate.decide()` (`policy/execution_gate.py`). *Gap:* not enforced; agents can still call services directly. **Create** an agent→tool allowlist + a test that fails if a non-gated path mutates money/inventory/supplier.
- **Segregation of duties:** the agent that *recommends* an action must not be the one that *executes* it. `Product_Ranking_Agent` recommends; `decide()` authorizes; a separate execution service acts. Enforce via the gate.
- **Bounded autonomy (David pg 8):** valid autonomous outcomes = retry / switch / fallback / substitute / clarify / quarantine / refund-within-policy. **Tension with our fail-close→HUMAN_REVIEW default** (`action_authority_matrix.py:251`): correct *now*; the autonomous outcomes are the end-state, gated on the gate + exception-recovery being proven. Use the new `exception_queue`/`retry_tracking` tables (P2) for this.
- **"No human closure" (David pg 2)** is a north-star, **not** today's rule — do not ship full autonomy before the gate is enforced everywhere + the control eval passes.

---

## 10. Frontend assessment

- Defensive enough for demo (`App.tsx:256/1464` graceful backend-unavailable handling; `.catch` present). WS trace path correct.
- **Risks:** `DecisionTrace.tsx` (3,055) + `App.tsx` (2,225) are large/fragile; the new payload fields (`data_integrity`, `compound_answer`, security-challenge text, `product_type`) need render paths + null-guards. **Verify** the right-panel "Why" + security sections render the new fields. **CSP/DOMPurify** on any LLM-text sink (the email lab is inline HTML — XSS surface).
- **Test:** the Playwright suite (`tests/browser/`) is **environment-blocked here** (server didn't boot in the 30s fixture window). Needs CI with chromium + longer startup. In-process TestClient covers route logic.

---

## 11. Open questions for GPT-5.5

1. Is the **moat-first reorder** correct, or should agnostic (StoreProfile) precede the gate migration?
2. **Excision granularity** — one slot/commit (safe, slow) vs batched (fast, risky)?
3. **`orchestrator.py` (4,009/241-excepts)** — strangle now or after recommend.py? It's a bigger silent-fail surface.
4. **Reverse-ETL latency** — is batch warehouse personalization acceptable, or is a real-time CDP (mParticle/zero-ETL) required for the buyer path?
5. **Bounded-autonomy timing** — when is it safe to replace HUMAN_REVIEW defaults with autonomous outcomes? What eval gate proves it?
6. **Scatter-gather timeout budget** — per-leg value, and fallback when a leg times out?

---

## 12. Recommended next commit (lowest-risk proof)

`store_profile.py` loader + wire **one** reader (`brand_price_floors_usd`) from `electronics.json`,
behind a characterization test, + add its `lru_cache` to the determinism clear-list. Then iterate
slot-by-slot, then `pharmacy.json`. This excises recommend.py safely *and* proves the agnostic+moat story.

Sources: [mParticle CDP](https://www.mparticle.com/integrations/), [CDP landscape 2025](https://insiderone.com/best-customer-data-platform/), [Segment alternatives](https://genesysgrowth.com/blog/best-alternatives-for-twilio-segment), [marketing data pipeline / reverse-ETL 2026](https://www.digitalapplied.com/blog/marketing-data-pipeline-etl-2026-modern-data-stack-reference), [Databricks vs Snowflake 2025](https://celerdata.com/glossary/databricks-and-snowflake-a-comprehensive-comparison).
