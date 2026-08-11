# ShopSquire — Complete Capability Deep Dive (2026-08-02)

*Everything the platform does, traced from source at HEAD `b3dca021`. Where a capability the reader
expects does **not** exist, it is marked ❌ rather than described.*

---

## 0. What it is, and the scale

**An evidence-governed commerce decision platform.** A model proposes into closed vocabularies;
deterministic authorities validate; connectors execute; a human authorizes anything consequential.
Every decision carries its evidence, and where facts are incomparable it abstains.

| | |
|---|---:|
| Total code | **418,042 lines** |
| `src/` | 265,958 (1,007 files) |
| `tests/` | 104,905 (1,082 files) · **5,524 collected tests** |
| Services · Routers · Security modules | **434 · 116 · 140** |
| Migrations | 98 |
| Registered API routes | 738 |
| Empty function bodies in `src/app` | **10 / 6,722 (0.15%)** — all typing Protocols |
| TODO/FIXME in `src/` | **4** |

---

## 1. Chat, personas & workload grounding

### 1.1 Persona / use-case model — 11 profiles, 54 aliases
`config/use_case_kb.json`:

```
gaming · game_development · university · engineering_student · creative
corporate · calls_productivity · ai_ml_workstation · general
primary_school · high_school
```

Each carries requirement floors (`gpu_tier`, `ram_min`, `vram_min`, storage, CPU) plus
`soft_requirement_weights`. **54 aliases** map natural phrasing → profile
("uni", "college", "3D rendering", "fine-tuning", "Zoom calls").

**Personas are NOT prompt personalities.** They are requirement floors that produce *fit verdicts*.
"I'm a uni student" changes which attributes are checked, not the tone.

### 1.2 Vertical profiles — the agnostic core proof
`config/store_profiles/` → **electronics · fashion · pharmacy** (+ JSON schema).
`data/attributes/` carries per-vertical attribute registries. The core never names a product
attribute — `test_no_flavour_in_core.py` fails the build if it does.

### 1.3 Workload grounding
```
utterance ──► workload stage ──► detect games (slug)      ──► steam_requirements connector
                              ──► detect software/AI reqs ──► regex: fine-tune|stable diffusion|
                              ──► merge floors                       7b|13b|70b|local LLM
                                     │
                                     ▼
                        fit verdicts: meets / fails / UNKNOWN
                        (enriches TRUTH, does NOT filter retrieval)
```
⚠️ **Known limit:** 9 Steam fixtures; the live lane exists behind
`STEAM_REQUIREMENTS_LIVE_ENABLED` but is **not wired at the call site**. Non-fixtured titles fall to
a flat `gaming` floor.

---

## 2. Routing & NLP — the decision spine

```
utterance + session
      │
      ▼
┌─────────────────────────────────────────────────────────────────┐
│ SHARED COMMERCE GUARD  injection · model-theft · rate · intake   │  deterministic, fail-closed
└──────────────────────────┬──────────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│ MODEL CALL #1 — route_turn()                                    │
│  out: {lane, node_handle, requirements[], quantity, budget,     │
│        brand, subject_action, procurement_context, confidence}  │
└──────────────────────────┬──────────────────────────────────────┘
                           ▼  the model PROPOSES; it decides nothing
┌─────────────────────────────────────────────────────────────────┐
│ CLAMP CHAIN                                                     │
│  lane ∈ LANES(10) · node ∈ offered candidates                   │
│  requirements ∈ attribute registry · brand ∈ catalog            │
│  quantity/budget ← canonical grammar (NOT model text)           │
│  refusal granted ONLY if sells_within()==False                  │
└──────────────────────────┬──────────────────────────────────────┘
                           │ any miss → _bounded_fallback_decision()
                           │            lane = PROCUREMENT if qty>=2 else SEARCH
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│ CLARIFY GATE (pre-retrieval, TEMPLATE-ONLY, no model, ~ms)       │
└──────────────────────────┬──────────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│ PLAN — TOOLS = 7 closed executors                                │
│  derive_plan() deterministic baseline                            │
│  propose_plan() MODEL may reorder/extend WITHIN TOOLS             │
│  validate_plan() → any miss falls back to derived                 │
│  ★ the model can add a STEP; never a CAPABILITY                   │
└──────────────────────────┬──────────────────────────────────────┘
                           ▼
    retrieve (Postgres BOW, MODEL-INDEPENDENT) → fit_check (tri-state)
                           ▼
  POST-RETRIEVAL, each _run_stage()-guarded/timed/traced:
   capability_budget → shelf(3 bands) → variant_clarify → complement_offer
   → bulk_economics → fulfillment_preview → secondary_explanation
                           ▼
   COMPOSE  set_message(MsgPriority ladder) — deterministic; blank never claims
                           ▼
   POSTFLIGHT  persist constraints_used (REFRESH, not wipe)
```

**10 lanes:** `SEARCH · FILTER · COMPARE · EXPLAIN · SUPPORT_CLAIM · CART_MUTATE · PROCUREMENT ·
OFF_CATALOG · POLICY_QUESTION · INVENTORY`

---

## 3. Scatter-gather evidence & external search

`evidence_orchestrator.py` — **the LLM never fetches anything. Legs are deterministic reads; the
intelligence is in the SELECTION.**

```
        plan (possibly LLM-filled) ──► select_legs()
                                            │
        ┌──────────┬──────────┬─────────────┼─────────────┬──────────┐
        ▼          ▼          ▼             ▼             ▼          ▼
     market     policy   availability  purchase_history  image      web
   competitor  approved   stock depth   buyer's recent   CV-identified  CONSENT-
   /price      policy     for category  orders (support/  product      GATED
   findings    answer     when qty      re-order turns    (computed
                          matters       ONLY)             upstream)
        └──────────┴──────────┴─────────────┴─────────────┴──────────┘
                   ALL RUN CONCURRENTLY · hard per-leg budget ~2.5s
                   ADDITIVE — a hung leg NEVER blocks the turn
                                     │
                                     ▼
                    labeled evidence + citations → Evidence tab + source chips
                                (message text untouched)
```

### External search — two independent mechanisms
| Mechanism | Trigger | Gate | Status |
|---|---|---|---|
| **Steam requirements** | game detected | fixture-first; live needs `allow_live` + allowlist | ⚠️ fixture-only wired |
| **General web research** | `plan.needs_market_evidence` + web consent | `EXTERNAL_RESEARCH_ENABLED` | off by default |
| **Registered public sources** | `market_source_registry` | `licence_id` · `licence_url` · pinned origin · trust tier | ✅ USGS, World Bank live |

**The consent rule:** the web leg is *never* selected from query content alone. A user typing
"search the web for X" cannot force a fetch — the imperative only surfaces a consent chip.

---

## 4. Retrieval-augmented generation — the honest inventory

| What you asked about | Reality |
|---|---|
| **Hippograph** | ✅ **Real.** `hippograph.py` — projects `decision_trace_events` (an edge table: source→target labelled by event_type) + `conversion_event` reward edges into a graph of canonical entities (deduped via `entity_resolution`), then recalls top-k via **spreading activation — a Personalized-PageRank approximation, reward-weighted** so high-converting entities surface first. **READ-ONLY, never writes or executes.** In-memory adapter; Neo4j swap is a later option. Recalled entities are *proposals* that re-enter policy/escalation before acting. A/B measured: NDCG 0.4737 both arms, delta 0. |
| **CacheRAG** | ⚠️ **EXISTED — and was deleted with `recommend.py` on 2026-07-29.** It was a **narration-text cache**: it cached LLM prose only, never the payload — procurement fields were recomputed fresh per request, so a cache hit never returned stale data. Known defect at the time (commit `859ef80a`, 2026-06-30): *"the cache fingerprint omits `order_quantity`, so a bulk query can reuse a non-bulk query's narration prose (prose↔card mismatch, not data loss)."* Companion CAG / dynamic-context flags were **orphaned — defined, never read.** Today: zero references to `narration_cache` / `CAG_` / `dynamic_context` in `src/app`; the archived `recommend_v1_2026-07-29.py.txt` still carries 51 `cache` mentions. **This is an undocumented regression — see §4.1.** |
| **TemporalRAG** | ❌ **No module by that name.** The *substrate* exists — `market_facts` carries `valid_from`/`valid_to`/`freshness_policy`/`observed_at`/`ingested_at` (bitemporal), and `market_evidence_policy` resolves by `trust_tier_then_freshness_then_confidence`. That's temporal evidence governance, not TemporalRAG. |
| **Multi-agent RAG** | ✅ The evidence orchestrator scatter-gather (§3) is genuinely multi-agent retrieval; `agentic_rag_pipeline.py` carries `policy_version` + `model_version` on results. |

### 4.1 ⚠️ The CacheRAG regression — flagged, not yet fixed

Retiring `recommend.py` removed the narration cache with it. Nothing replaced it, and no commit
records the loss. Consequences to check:

- **Cost/latency:** repeated or similar turns now re-generate narration prose every time. The router
  call was already ~99% of turn latency; this adds narration generation on top of turns that
  previously served cached prose.
- **The silver lining:** the known `order_quantity` fingerprint bug went away with it. Any
  replacement **must** include `order_quantity` (and currency, and tenant) in the fingerprint.
- **What survives:** `semantic_cache.py` (319 ln, Redis-backed with in-process fallback — used by
  `TierRouter`, `agentic_rag_pipeline`, `orchestrator`, `recruiting_pipeline`), `vision_cache.py`,
  and the 4-layer Redis session memory.

**Recommendation:** if narration caching is wanted back, rebuild it against `semantic_cache` with a
fingerprint of `(tenant, uid_scope, node, requirements, budget, order_quantity, currency, lane)` —
and it must participate in the DSR erasure sweep (§4.2), which the old one did via the Redis key
scan.

### 4.2 Right-to-erasure — GDPR **and** Australian Privacy Principles

This is real and more complete than the RAG naming suggests:

| Surface | Where |
|---|---|
| `POST /privacy/delete_user_data` (OWNER-gated) | `routers/privacy.py:242` |
| Deletion orchestration | `services/privacy_deletion_orchestrator.py` |
| **DSR erasure across ALL user-linked Redis keys** — 8 memory + typed slices | `privacy.py:326` |
| **Fails loud on partial erasure** → `action_required: "redis_or_cache_erasure_incomplete"` | `privacy.py:335` |
| `DELETE /retention/purge?days=` | `privacy.py:518` |
| Storage-limitation sweep (GDPR Art. 5(1)(e)) — soft-expire then hard-purge | `privacy.py:576`, `retention_sweeper.py` |
| Per-tenant erasure/export scoping | `tenant_context.current_tenant_id` |

Note the code says **"GDPR/APP"** — Australian Privacy Principles are handled alongside GDPR, which
matters for the ANZ positioning. And the `redis_or_cache_erasure_incomplete` flag is the right
posture: an incomplete erasure is surfaced as an action item, never silently reported as done.

**Any cache added back must be enumerable by that sweep**, or right-to-delete becomes unprovable.

### The actual retrieval stack
```
candidate_retriever · recommend_retriever_stage · graph_retrieval
vector_store · embeddings · embedding_pipeline · product_embedding_text
taxonomy_embedding_index · ocr_embedded · storage_s3
hippograph · hippograph_db · hippograph_feedback
ragas_eval · recommend_retrieval_metrics
```
**Retrieval is taxonomy-first and model-independent** (Postgres BOW) — which is why product cards
can paint in under a second while the router is still thinking.

---

## 5. Multi-turn memory & context rot

```
┌──────────────────────── REDIS, per uid, scoped by tenant ─────────────────────┐
│  session:{uid}:summary              utterances[-50:]      TTL 86,400s         │
│  session:{uid}:kv_state             budget · brand · subject · node   86,400s │
│  session:{uid}:recent_retrieval     facts                 TTL    600s         │
│  session:{uid}:agent_steps                                                     │
│  session:{uid}:observation_summary  observation_log[-500:]                     │
│                                                                                │
│  index TTL guard: max(ttl, kv_ttl, 90*86400) — the index can never expire      │
│                   before a value it indexes                                    │
│  ✗ reads do NOT refresh TTL  ("deliberately do not refresh on read/touch")     │
└────────────────────────────────────────────────────────────────────────────────┘
                                     │
   TURN N+1 re-enters with kv_state as PRIOR NODE + carried budget/constraints
                                     │
   postflight persists constraints_used as REFRESH-NOT-WIPE
   (the exact bug class that killed the 12k engine)
```

**Anti-rot controls:** bounded (`[-50:]`, `[-500:]`) · tiered TTL (24h state / 10min retrieval) ·
no TTL refresh on read · index-outlives-values guard.
**Tested:** `tests/test_context_rot.py::test_summary_truncates_over_50_utterances`,
`::test_recent_retrieval_expires`.

---

## 6. Shopping cart

```
 buyer intent ──► CART_MUTATE lane ──► propose_plan()  persists a CartMutationPlan
                                            │           against the cart VERSION it saw
                                            ▼
                                     apply_plan()   ← the ONLY way a plan touches a cart
                                       • idempotent: status CAS claims the plan;
                                         re-applies return the STORED result
                                       • stale-guarded: cart changed → refuse
                                       • expiry: plans expire
                                       • trace-linked
```
Table `cart_mutation_plans` (tenant, uid, status, plan, cart_version, expires_at, trace_id) with
indexes on owner+status, expires_at, trace_id.

**Identity:** cart is scoped by **(tenant, customer)** via `tenant_context` ContextVar — threaded
through cart/facade/service/orders/account/privacy/recommend/upsell with a 4-proof isolation suite.

**Capabilities:** add · remove · **swap** · quantity change · deficit-reorder · undo chip (restore a
cleared cart) · stock gates · combined-availability two-option (fill-now vs ship-from-stock).

---

## 7. Procurement, bulk orders & RFQ drafting

```
 T:  "what about 15 of them"
      │  quantity >= 2  → PROCUREMENT lane  (DETERMINISTIC, one line, no model)
      ▼
 bulk_economics       qty × price_breaks × MOQ  → unit/total, break nudges
 fulfillment_preview  network availability · transfer plan · shortfall
      │
      ▼
 CART  ──► "Confirm delivery plan"  ═══ GATE 1 (domain) ═══
      │
      ▼
┌──────────────────── build_draft() ────────────────────────────────┐
│ select_supplier(rank_fn, allowlist_fn, tenant)                    │
│ gather_evidence(item_ref, case_state, recipient_domain)           │
│ supplier_terms(supplier, sku) → MOQ pre-check                     │
│    qty < MOQ → explicit warning IN the draft                      │
│ price_break_advisory() → volume nudge                             │
│ fields: recipient · domain · subject · body · quantity ·          │
│         needed_by · case_ref · terms · reliability · reason       │
│                                                                    │
│ draft_send_gate(min_confidence=0.6)  ADVISORY, PRIOR to human      │
│   → allow | needs_info | block                                     │
│                                                                    │
│ send_gate: "human"        auto_sent: FALSE                         │
│ channel by supplier record: email→agent drafts/human sends ·       │
│   phone/portal→human-only · edi/cxml/api→integration               │
└───────────────────────────┬───────────────────────────────────────┘
                            ▼   ═══ GATE 2 — HUMAN ONLY ═══
        outbound_queue: pending→sending→sent | dead_letter
          idempotency_key dedup · claim/reclaim on stale · backoff
          max_attempts · ack_status (EDI 855)
          outbound_integrity: the platform can QUARANTINE ITS OWN DRAFT
                            ▼
        supplier reply ──► QUARANTINE ──► projected as OBSERVATION
                                          (never an instruction)
```

**Full procurement stack (35 modules):** approval_policy · autonomous_send · budget_gate ·
buyer_qualification · buyer_reply · cart_commitment · change_order · draft · draft_retry · economics
· external_comms · fulfillment_split · margin_advisor · notifications · okf_export · order_split ·
outbound_delivery · outbound_integrity · outbound_queue · po_transport · procurement_fraud_signals ·
procurement_request · purchase_order · repository · rfq_fanout · sandbox_supplier · supplier_channel
· supplier_contacts · supplier_events · supplier_polish · three_way_match · transport · workflow

**Identity ladder:** `PR-{tenant}-{date}-{short}` → CASE → PO → GR/INV. Gate 3 = change-order, not
supersede, human-only.

---

## 8. Market intelligence — every detector

`market_analysis.py` — **13 deterministic detectors**, all vertical-blind (counts only, no product
vocabulary):

| Detector | Computes |
|---|---|
| `detect_demand_shift` | anomaly over daily demand series |
| `detect_conversion_anomaly` | conversion-rate anomaly |
| `detect_inventory_demand_mismatch` | unmet demand vs stock (min_unmet=3) |
| `detect_demand_forecast` | EWMA α=0.28 forward projection |
| `detect_seasonal_demand` | weekday/seasonal pattern (min_days=7) |
| `detect_competitor_undercut` | price gap ≥5% |
| `detect_objection_cluster` | repeated buyer objections (min_count=3) |
| `detect_funnel_dropoff` | stage drop ≥50% at volume ≥10 |
| `detect_segment_shift` | segment share vs baseline |
| `detect_channel_performance` | channel rate gap ≥30% |
| `detect_bundle_opportunity` | co-occurrence ≥3, top-k=5 |
| `detect_velocity_dsi` | `units_sold/avg_stock`; `DSI = stock/(units/day)`; dead-stock flag |
| `detect_bulk_order_frequency` | RFQ count per sku/category per window |

**Evidence discipline:** every finding is a `MarketFinding` with confidence, provenance,
`observed_at`/`ingested_at`, `valid_from`/`valid_to`, `freshness_policy`, status.
Contradictions resolve **trust_tier → freshness → confidence**, never by averaging.

**Supporting modules (20):** bi_intelligence · demand_forecast · market_action_policy ·
market_analysis · market_digest · market_evidence_policy · market_facts · market_intelligence_agent ·
market_metrics · market_outcome · market_pipeline · market_projection · market_replay ·
market_signal · market_signal_adapters · market_source_registry · market_store · market_warehouse ·
public_market_source_fetch · seasonal_market_scenario

---

## 9. Sales & executive metrics

`executive_metrics.py` + `bi_intelligence.py`:

| Metric | Status |
|---|---|
| `forecast_quality` — WAPE/bias vs actuals | ✅ |
| `compare_forecast_candidates` (+ `_from_sealed`) | ✅ versioned sealed evidence |
| `persist_forecast_actual_pair` | ✅ the accuracy loop |
| `inventory_productivity` — GMROI / turns / WOS | ✅ |
| `ppv_evidence` — purchase price variance | ✅ |
| `gmroi_unavailable(...)` | ✅ **returns typed unavailability rather than a guess** |
| `clv_prediction` — RFM, tenant-scoped, currency-partitioned | ✅ honest `_unavailable` on missing data |
| `churn_prediction` | ✅ |
| `margin_intelligence` — revenue/wholesale/margin by SKU×currency | ✅ |
| Supplier scorecard — OTIF, lead mean **and σ** | ✅ |
| Executive pulse | ✅ in UI |
| Dead-stock capital · discount leakage · sell-through | ⚠️ derivable, partly surfaced |
| CAC/ROAS · freight cost-to-serve · shrink | ❌ **honest external gaps — labelled absent** |

Every metric emits a `MetricEvidence` with `status ∈ {observed, estimated, insufficient,
unavailable}` + provenance + `as_of`.

---

## 10. Machine learning & forecasting models

| Model | Where | Use |
|---|---|---|
| **EWMA** (α=0.28) | `demand_forecast`, `market_analysis` | baseline demand forecast |
| **ARIMA** | `demand_forecast` chain | primary in `FORECAST_MODEL_CHAIN=arima,prophet,ewma` |
| **Prophet** | `demand_forecast` | daily+weekly seasonality |
| **Croston / SBA** | `demand_forecast` | **intermittent demand** — the wholesale-critical one |
| **Seasonal naive** | `rolling_origin_evaluation` | the baseline everything must beat |
| **Rolling-origin evaluation** | `demand_forecast` | walk-forward, not in-sample |
| **WAPE / bias** | `executive_metrics` | headline accuracy (MAPE is wrong for zero-sale days) |
| **Interval calibration** | `forecast_interval_calibration` | conditional coverage |
| **IsolationForest** | `agent_behavior_anomaly`, `anomaly_detector` | agent + market anomaly scoring |
| **Contextual bandit** (70 refs) | `recommendation_bandit`, `bandit_context` | ranking exploration |
| **ALS** (67 refs) | `recommendation_als` | collaborative filtering |
| **KMeans / NN / PCA** | `sklearn` — clustering, `image_clustering`, decomposition | fraud + image grouping |
| **Confidence calibration** | `confidence_calibration` | model confidence → decision bands |
| **ML decision gate** (+ training) | `ml_decision_gate` | learned gating with a deterministic floor |
| **Fusion / fraud scorers** | `fusion_scorer`, `fraud_scorer` | CV + signal fusion |
| **DREAD calibration** | `dread_calibration`, `dread_scorer` | threat scoring |

**Earned autonomy:** measured WAPE feeds `authorize_replenishment(min_confidence)` — the gate widens
only as demonstrated accuracy improves.

---

## 11. Vision, OCR & upload safety

### 11.1 The pipeline
```
 upload
   │
   ▼
┌───────────────────────────────────────────────────────────────────┐
│ strict_binary_ingest_gate()   743-line intake gate                │
│  • magic-byte sniff (content over extension)                      │
│  • polyglot signature detection (trailing data after IEND/EOF)    │
│  • archive depth + expansion inspection                           │
│  • size + decoded-pixel ceilings                                  │
│  • AV scan hook                                                   │
│  • NFKC normalise → strip zero-width + BIDI overrides → THEN match │
│  • generated storage name, outside webroot, no execute bit        │
└──────────────────────────────┬────────────────────────────────────┘
                               ▼
┌───────────────────────────────────────────────────────────────────┐
│ SPLIT-RESOLUTION POLICY                                            │
│   downscale ≤1280px COPY ──► VLM  (avoids 600s+ hangs on 24MP)     │
│   FULL-RES original      ──► steg detector · QR decode · adversarial│
└──────────────────────────────┬────────────────────────────────────┘
                               ▼
   ┌────────────┬──────────────┬───────────────┬──────────────────┐
   ▼            ▼              ▼               ▼                  ▼
 VLM ident   OCR (cv_ocr)   steg_detector   QR decode        forensics
 cv_vision_  ocr_embedded   LSB/χ² floor    ALL codes        exif_analyzer
 ollama      passive_       score           (not just #1)    cv_document_
 cv_tiered   payload                                          forensics
 cv_object_  analysis                                         gan_image_detector
 detector                                                     diffusion_detection
   │            │              │               │                  │
   └────────────┴──────────────┴───────────────┴──────────────────┘
                               ▼
    ALL extracted text classified  untrusted:document_text
    → reaches pattern scanner ✓   → reaches model context ONLY as DATA
    QR external → TEXT-ONLY WIPE (strict pin)
    PCI/SSN → redacted at boundary (***-**-1234)
    damage detected → routed to SUPPORT, not recommendation
```

### 11.2 Vision module inventory (27)
`cv_damage_classifier · cv_evidence · cv_explain · cv_model_pack · cv_object_detector · cv_ocr ·
cv_provider · cv_quality · cv_tier2_pipeline · cv_tiered · cv_triage_basic · cv_vision_ollama ·
cv_warmup · image_downscale · image_fallback_advice · image_forensics · image_intake ·
image_intent_router · image_query_relationship · image_security_event · ocr_embedded ·
recommend_image_hints · recommend_image_similarity_stage · recommend_vision_stage ·
reverse_image_search · vision_cache · vision_reasoning`

### 11.3 Upload attack coverage — 46-artifact corpus, wired to a passing test
`tests/security/test_generated_security_corpus.py` (6 tests) hash-verifies every artifact and
exercises production code. Categories: MIME mismatch · PNG+ZIP / PDF+ZIP polyglots · malicious SVG
(script + xlink + foreignObject) · XML entity expansion · EXIF/XMP injection · GPS/serial privacy ·
pixel bomb (197KB → 192MB, 64MP) · 240-frame GIF · nested archives · WebP RIFF overflow · truncated
stream · AVIF ftyp-only · PNG bad CRC · 9 QR payloads (SSRF, punycode, shortener, `javascript:`,
`data:`, PCI, **multi-code**) · 5 visible-injection variants · adversarial patch · LSB/recompress
near-dupes · poisoned batch isolation · replay · cross-tenant probe · supplier PDF white-on-white ·
CSV formula injection · Unicode bidi/ZWSP/homoglyph.

**Documented known gaps:** `injection_mirrored`, `injection_edge_cropped` may pass undetected.

---

## 12. Security capabilities — 140 modules

**Identity & access:** auth · iam · rbac · authorization_engine · object_authz · scope_enforcement ·
buyer_principal · admin_mfa · mfa_store · totp · dual_control · oob_verification ·
runtime_confirmation

**AI/LLM-specific:** injection_patterns · prompt_injection_eval · prompt_registry ·
jailbreak_embedding_guard · model_theft · agent_guardrails · agent_events · tool_intent_gate ·
maestro_boundaries · nlp_deception · guardrails

**Content & file:** file_validator · archive_sandbox · csv_safety · exif_analyzer · steg_detector ·
adversarial_image_detector · gan_image_detector · diffusion_detection · image_feature_gate ·
image_threat_signals · image_behavior_abuse · image_clustering · cv_document_forensics ·
pdf_producer_cve · linked_artifact_analysis · qr_legitimacy · yara_email_scan · passive_payload_analysis

**Email / BEC:** email_security (2,833 ln) · email_attachment_parser · email_attachment_intel ·
email_header_forensics · email_dmarc · email_dns_verify · email_sender_trust · email_url_click_protect ·
bimi_verifier · bec_kill_chain · semantic_bec_scorer · mailbox_compromise ·
adversarial_email_pipeline · email_ai_authorship · phishing_page_detector · email_security_eval_harness

**Network & egress:** egress_allowlist · url_guard · safe_requests · internal_mtls ·
tls_fingerprint_middleware · firewall · transaction_firewall · client_ip · headers · csrf_middleware ·
rate_limit · webhook_security

**Data protection:** pci · pci_boundary · pii_ner · dlp_export · kms · secrets_store ·
backup_encrypt · idempotency · audit_chain (hash-chained: `payload_hash` + `prev_hash`)

**Supply chain:** supply_chain · supply_chain_controls · supply_chain_automation ·
supply_chain_harness · supply_chain_scenarios · supplier_baseline · supplier_governance_store ·
vendor_baselines · vendor_connectors · artifact_authority · config_integrity · flag_integrity

**Detection & response:** anomaly_detector · insider_threat_detector · ransomware_detector ·
lolbin_behavioral_catalog · runtime_detection_policy · runtime_evidence_lab · pcap_analyzer ·
security_event_ingest · siem_adapter · misp_feed · escalation · observer · telemetry_emit

**Governance:** compliance · control_registry · owasp_map · atlas_map · framework_correlation ·
kyv_registry · policy_pack_release · provider_boundary · pentest_bounds · vuln_scan · threshold_tuning

**Build-blocking ratchets:** `test_no_fail_open_in_security` · `test_no_silent_except_in_core` ·
`test_no_flavour_in_core` · `test_no_untimed_outbound_http` · `test_no_bundled_demo_key`

---

## 13. Threat modelling

```
 signal ──► threat_intel (feed_client · store · url · automation · enrichment)
              │  MISP feed · vendor baselines
              ▼
         framework_correlation ──► owasp_map  (OWASP LLM Top-10 / File Upload CS)
                               ──► atlas_map  (MITRE ATLAS — e.g. AML.T0048, AML.T0051)
              │
              ▼
         dread_scorer + dread_calibration   → calibrated severity
              │
              ▼
         bec_kill_chain        → BEC stage attribution
         insider_threat_detector
         payment_threats
         threat_hunter_leads   → evidence-backed hunting leads (surfaced in the trace)
              │
              ▼
         escalation_policy → escalation_room → incident → playbook_engine
```
The steg corpus manifest already carries per-artifact `mitre_atlas` and `owasp` mappings.

---

## 14. How it compares

| Category | Player | Structural limit |
|---|---|---|
| **Horizontal AI governance** | Fiddler ("AI Control Plane"), Arthur, FutureAGI, Trustible | Domain-blind. Scores *behaviour* (11 safety dims). **Cannot know AUD≠USD, each≠case-of-24, on-hand≠available.** |
| **CX agents** | Sierra ($15.8B), Decagon, Fin, Zendesk | Ticket-scoped. 3–7 month deploys, six figures. No procurement, no catalog truth. |
| **CRM** | Agentforce, HubSpot Breeze | Owns the customer record; conversion-centric; no supplier side. |
| **Supply-chain planning** | Blue Yonder, o9, Kinaxis, SAP IBP | *"Strongest inside the planning estate, still building out action beyond it."* Provenance not a feature. |
| **Source-to-pay** | Coupa, Ariba, Zip | No buyer-side catalog truth, no conversational grounding. |
| **Buyer agents** | ChatGPT Instant Checkout, Rufus, Gemini | Conversion-optimised — a refusal is a loss to them. |

**The differentiation, in one line:**
> Horizontal governance platforms detect that an agent *behaved* badly. ShopSquire prevents the bad
> claim from being *constructible* — because it knows what the numbers mean.

**Enterprise procurement checklist (2026):** kill switch ✅ · tamper-evident audit trail ✅ (hash
chain) · human-in-the-loop boundaries ✅ · model change control ✅ · **ISO 42001 / SOC 2 ❌**.
Four of five, built before the checklist was published.

---

## 15. Honest gaps — state these first, always

| Gap | Status |
|---|---|
| **Zero customers, zero production traffic, synthetic data only** | the one that matters |
| Relevance labels | `human_reviewed_by: null` |
| ISO 42001 / SOC 2 | not certified |
| `external_stock` (supplier ATP) | **does not exist** — supplier availability is RFQ-based |
| Steam live lane | flag exists, not wired at call site |
| `chat.py` (3,689 ln) | still holds a **duplicate regex router**; budget parsing duplicated in 6+ places |
| CacheRAG / TemporalRAG | **do not exist** as named components |
| Load testing | never done (~40 concurrent turns/replica; Ollama doesn't batch) |
| CAC/ROAS · freight · shrink · FEFO | honest external data gaps |
| Bus factor | 1 |

---

*Traced from source. No code changed. HEAD `b3dca021`.*
