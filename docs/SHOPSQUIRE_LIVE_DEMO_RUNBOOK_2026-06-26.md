# ShopSquire — Live Demo Runbook v2 (EXACT wiring)
**2026-06-26** · buyer query → query decomposition (scatter-gather) → supplier identification → human-approved email → supplier → buyer. Every step mapped to the **exact backend file:function, frontend file, port, agent, endpoint, and bitemporal trace**. Includes the three views (buyer / human / supplier), the no-supplier fallbacks, and the **bounded supplier-inbox-reader agent** (a gap to build).

> Line numbers I personally verified are exact; ones from code-mapping are marked `~` (function names are reliable, lines may drift).

---

## 0. The three surfaces, ports, and exact frontend files

| Surface | Port | App / dir | The components that matter |
|---|---|---|---|
| **Buyer** | **5173** | `frontend/src/` (React/Vite) | `App.tsx` (recommendations + panels), `components/FulfilmentOptions.tsx` (procurement panel), `components/FulfilmentJourney.tsx` (buyer-safe journey), **`components/DecisionTrace.tsx`** (the agent bitemporal trace) |
| **Operator (human)** | **3001** | `src/frontend/admin-react/` | `components/ProcurementCases.tsx` (the human control room — drafts, gates, economics, journey), `components/MarketIntelligence.tsx`, `api.ts` |
| **API** | **8080** | `src/app/` (FastAPI) | routers below |

---

## 1. Bring-up (flags · seed · auth)

```
# flags (config/feature_flags.json or env) — all default-OFF, ON for the demo:
FULFILLMENT_CASES_ENABLED=1   FULFILLMENT_DEMO_ENABLED=1   FULFILLMENT_BULK_THRESHOLD=5
COMMERCE_CATALOG_ENABLED=1
# seed suppliers + trusted domains + canonical price/stock (so the draft resolves a supplier + economics has data):
PYTHONPATH=. python scripts/seed_suppliers.py
# operator auth on the :3001 tab:
localStorage.setItem('ss_owner_key', '<OWNER_API_KEY>')
```
⚠️ Never commit `config/feature_flags.json` from a demo run (`git checkout config/feature_flags.json` after).

---

## 2. The pipeline buyer-query → supplier-email (exact files, agents, the TWO scatter-gathers)

The orchestrator runs a 4-phase flow (`services/orchestrator.py` → `Orchestrator._run_internal()` ~L2658, phases traced via `_trace_phase()` ~L307). Two distinct scatter-gathers feed the email:

### Scatter-gather #1 — decompose the buyer QUERY (EXPLORE)
- **`services/query_decomposer.py` → `decompose(query)` (L808)** returns a **`QueryPlan`** (L347) with the fields that drive procurement:
  - `quantity` (`_extract_quantity` L475) → the bulk order qty ("10 laptops")
  - `availability_horizon_days` (`_extract_availability_horizon` L71) → becomes the email's `needed_by`
  - `intent` / `is_compound` / `sub_questions` (`_segment_query` L765, `_classify_clause` L706) → multi-intent split
  - `hard_constraints`, `exclusions`, `needs_market_evidence` + `market_evidence_kinds` (`_detect_market_evidence_need` L660)
- **`services/parallel_agent_executor.py` → `run_parallel_checks()` (~L415)** fans CV / Fraud / Inventory agents across a 3-worker pool (`_run_cv` ~L66, `_run_inventory` ~L207, `_run_fraud` ~L230) and votes a swarm consensus (`_build_swarm_consensus` ~L393). **This is the asyncio path fixed by `services/async_safe.py` (`fbde019`).**
- **Availability** (PLAN): `services/recommend_fulfillment_stage.py → run_fulfillment_stage()` (L27) computes `{requested_qty, in_stock, shortfall}`; `_maybe_open_case()` (L55) opens the case at **GATE 1** when `FULFILLMENT_CASES_ENABLED` and `order_qty ≥ FULFILLMENT_BULK_THRESHOLD` and `shortfall > 0` (L57–L88).

### Scatter-gather #2 — compile the supplier EMAIL from evidence (PLAN→ACTION)
- **`services/fulfillment/draft.py → gather_evidence()` (L84)** fans out **four independent, best-effort sources**, each emitting a discrete evidence id onto the trace:
  - **inventory shortfall** from case state (L100, `INV-…`) — authoritative
  - **hippograph** supplier reliability/context (L107, `HIP-…`, `_default_hippograph` L139 → `hippograph_feedback.build_hippograph_insights`)
  - **market-intel** urgency (L112, `MKT-…`, `_default_market` L144 → `market_analysis.load_recent_findings`) — your Track-B detectors land here
  - **external benchmark** (L117, `EXT-…`, provenance-tagged, internal-only — never sent)
- The email is then assembled in **`build_draft()` (L207)**: `_urgency_note()` (L191) is driven by the market_intel evidence; `_confidence()` (L198) rises with hippograph/market evidence; the body is a **fixed template slot-fill** (`DEFAULT_TEMPLATE` L34) — `needed_by` from the query's availability horizon, `item_ref`/`quantity` from the plan. Optional LLM polish is accepted **only if `_claim_safe()` (L79)** holds (no price, mandatory "not a purchase order" footer).

### The agents (registered with MAESTRO boundaries in `security/maestro_boundaries.py`)
| Agent | Role | `max_autonomous_value_usd` | Can send externally? |
|---|---|---|---|
| `NLP_Search_Agent`, `Candidate_Retrieval_Agent`, `Product_Ranking_Agent`, `NQE_Engine` | EXPLORE/EVALUATE | — | no |
| `Fraud_Scoring_Agent`, `CV_Label_Agent`, `Security_Observer_Agent` | EVALUATE/guard | — | no |
| **`Procurement_Agent`** (~L162) | assess · rank · gather_evidence · **draft** · options · propose_po | **0.0** | **no — `can_call_external_api=False`, it DRAFTS** |
| **`Supplier_Communication_Agent`** (~L179) | transport (dispatch) | **0.0** | only on a **human-approved** send |
| `Orchestrator` (~L142) | 4-phase driver | 500.0 | no |

**The point: the only actor that fires the external send is HUMAN_OPERATOR** (`domain.py` GATE 2, `external_message_sent` L133) — no agent value cap can bypass it.

---

## 3. Supplier identification + targeting + fallbacks (no supplier details)

**Who do we email, and how is the address chosen (anti prompt-injection)?**
- `draft.py → select_supplier()` (L175) → `_default_rank()` (L153) → `InventoryAgent._get_best_supplier(item_ref)` ranks the SKU's suppliers (`suppliers ⋈ supplier_products`), then the **recipient domain is read from the ALLOWLIST** `trusted_supplier_domains` via `supplier_catalog.domain_for_supplier()` (L113) — **never from buyer text**. The allowlist is enforced again at send (`supplier_domain_guard.is_trusted_supplier_domain`, L80) and on every inbound reply.
- Targeting precedence: top-ranked supplier whose domain is on the allowlist (L181–L187). Reliability (`on_time_rate`) feeds draft confidence.

**Fallbacks when there are no supplier details:**
1. **No approved supplier / no allowlisted domain** → `build_draft()` returns `None` (L228) → `draft_and_record()` fires **`no_approved_supplier`** (L273) → state `NO_APPROVED_SUPPLIER`. *Operator action:* seed (`scripts/seed_suppliers.py`) or add a trusted domain (`supplier_domain_guard.add_trusted_domain`).
2. **No live quote (wholesale unknown)** → economics falls back to the **cheapest approved supplier cost** (`supplier_catalog.cheapest_wholesale_cents`, just shipped `5995db2`) so the operator still sees margin pre-quote.
3. **Richer supplier identity exists but is NOT yet wired into targeting** — `security/kyv_registry.py` (`kyv_vendors.contact_email`, ~L79) and `security/supplier_baseline.py` (`supplier_baseline_events`: historical send-times/invoice amounts, ~L73). These are the natural fallback/enrichment source for a contact email + "how we usually deal with them."

### NEW (to build): bounded **Supplier_Inbox_Reader** agent
**Gap:** nothing reads recent supplier emails to contextualize a draft. `tasks/email_poll_tasks.py` (~L121) calls a **stub** `jobs/ingest_gmail.fetch_recent_emails()` that doesn't exist; inbound replies are stored in case state (`external_comms.receive_reply` L67) but never read back to inform a new draft.
**Design (bounded, read-only):**
- New `services/supplier_inbox_reader.py` → `recent_supplier_context(db, *, supplier_id|domain, item_ref, window_days=90)` → returns `{last_quote_cents, typical_lead_days, last_contact_at, open_threads, contact_email}` from `supplier_baseline_events` + `kyv_vendors` + correlated `external_ref`/case inbound.
- **MAESTRO boundary:** `allowed_tools={read_supplier_history}`, `allowed_data_scopes={suppliers, emails}`, `can_call_external_api=False`, `can_write_db=False`, `max_autonomous_value_usd=0.0`. It only *reads* and returns a summary; it injects context into `gather_evidence()` as a 5th evidence source (`SUP-HIST-…`) — never into the recipient choice (allowlist stays authoritative).
- Implement `jobs/ingest_gmail.fetch_recent_emails()` so the poller actually populates an inbox archive (or read the already-correlated case inbound first — no new mailbox access needed for the demo).

---

## 4. The bitemporal decision trace — exact endpoints, WS, tab

There are **two** complementary bitemporal records:

### (a) Agent decision trace (the EXPLORE→EVALUATE→PLAN→ACTION reasoning + security signals)
- **Backend:** `routers/decisions.py` — query `GET /api/v1/decisions/query` (~L448, filters on `valid_from/valid_to/system_from/system_to/agent_name`), live **WebSocket `GET /api/v1/decisions/{trace_id}/events/ws`** (~L745), SSE fallback `…/events/stream` (~L864). Events are written by **`services/decision_log.py → log_trace_event()` (L746)** (normalized, sanitized, bitemporal); approve/reject/reopen/extend close or reopen the bitemporal intervals (~L1122–L1366). Contracts in `services/trace_contracts.py` (`apply_trace_contract` ~L289, `BitemporalWindow` ~L101).
- **Frontend tab:** **`frontend/src/components/DecisionTrace.tsx`** on the **buyer app :5173**, rendered inline in `App.tsx` (`{traceOpen && <DecisionTrace traceId={traceId} … />}` ~L2238). It connects to `wsUrl('/api/v1/decisions/{traceId}/events/ws')` (L516), SSE at L559, polling at L570. Shows intent analysis, the agent chain, policy gates, model selection, and the `bitemporal` block.

### (b) Procurement case journey (the buyer→supplier state machine, bitemporal SCD-2)
- **Backend:** `routers/fulfillment_cases.py` — **`GET /cases/{id}/journey`** (L77) every transition `event→state by actor (reason) @valid_from`; **`GET /cases/{id}/as-of?t=<ISO>`** (L83) reconstructs the case as it was at a past instant (the time-travel proof). Persistence is `fulfillment_case_version` (SCD-2 valid/system from/to) via `fulfillment/repository.py`; the chokepoint that writes each version + trace event is `fulfillment/workflow.py → transition()` (L84).
- **Frontend tabs:** operator **Journey** panel in `ProcurementCases.tsx`; buyer **View journey** toggle → `FulfilmentJourney.tsx` (redacted).

The two are **linked by `trace_id`**: the case is opened with `source_trace_id` = the recommendation's trace (`recommend_fulfillment_stage.py` L75), so the agent trace and the procurement journey are the same thread.

---

## 5. The THREE views — what each party sees (exact redaction)

| | Buyer (:5173) | Human / operator (:3001) | Supplier (external) |
|---|---|---|---|
| Recommended products | ✅ `App.tsx` ProductGrid + right panel (`displayProducts`, L1644) | — | — |
| Procurement panel | ✅ `FulfilmentOptions.tsx` (GATE-1 commit, options, "Order confirmed · PO-…") | ✅ full case | — |
| **The drafted supplier email (To/Subject/Body/hash/rationale)** | ❌ redacted | ✅ **Outbound draft** panel in `ProcurementCases.tsx` | only the **sent** body (no price, "not a PO" footer) |
| Wholesale cost / margin / discount headroom | ❌ | ✅ **Deal economics** button | ❌ |
| Supplier identity / domain | ❌ | ✅ | (is itself) |
| Bitemporal journey | ✅ redacted (`FulfilmentJourney.tsx`) | ✅ full (`/journey`, `/as-of`) | — |
| Agent decision trace | ✅ `DecisionTrace.tsx` | (same API) | — |

**Where the redaction is enforced (one place):** `routers/fulfillment_cases.py → _case_view(for_operator=False)` strips `draft/inbound/quarantine`, wholesale `unit_amount_cents` on `validated_quote`, and the PO's `unit_amount_cents/total_amount_cents/supplier_ref` (the buyer keeps the PO ref + qty). The supplier only ever receives what the human approved at GATE 2 (`external_comms.send_approved` L44, hash-checked).

---

## 6. GPT-5.5 browser clickthrough (exact testids + assertions)

**Tab A — buyer (:5173):**
1. Submit *"I need 10 gaming laptops for an esports lab, $1800 each"*.
2. Assert recommended products render; the **Procurement** panel (`data-testid="fulfilment-options"`) shows status *awaiting buyer commitment* (`fc-status`).
3. Click **Confirm sourcing** (`fc-commit-btn`) → assert status *committed*.
4. (after operator step B6) assert options (`fc-options`); pick **substitute** (`fc-option-substitute_shortfall`) → **Confirm selection** (`fc-select-btn`) → assert `fc-selected`.
5. Open the **agent trace** (DecisionTrace) — assert intent + agent chain + bitemporal block. Later assert `fc-confirmed` ("Order confirmed · PO-…").

**Tab B — operator (:3001 → Procurement):**
6. Select newest case. **Draft quote** (`op-draft`) → assert the **Outbound draft** panel shows To/Subject/**Body**/content-hash/rationale *(screenshot — headline artifact)*.
7. **Request approval** (`op-request-approval`) → assert **HUMAN APPROVAL REQUIRED** badge (`op-human-gate`).
8. **Approve & send (GATE 2)** (`op-dispatch`) → assert *quote sent*.
9. Scenario select (`op-scenario`) = `full_quote` → **Trigger supplier reply** (`op-demo-reply`, labelled SANDBOX SUPPLIER) → assert parsed quote + **DEMO QUOTE RESPONSE** (`op-demo-quote`). Repeat once with `untrusted_sender` → assert quarantine.
10. **Validate quote** (`op-validate`) → **Generate options** (`op-options`) → (buyer selects in Tab A) → **Propose PO** (`op-propose-po`) → **Approve & create PO** (`op-execute-po`) → **Mark completed** (`op-complete`).
11. **Deal economics** (`op-economics`) → assert margin + discount headroom + profit (`op-economics-panel`). **Journey** → assert it ends at COMPLETED.

**Surface (screenshot these):** the drafted email body + hash; the GATE/DEMO/SANDBOX labels; parsed-quote evidence; deal-economics panel; the bitemporal journey + an as-of read; the substitute alternative.
**Fix-if-fails:** 401 → set `ss_owner_key`; no procurement panel → `FULFILLMENT_CASES_ENABLED` + qty ≥ threshold + real shortfall; `NO_APPROVED_SUPPLIER` → run seed; no reply option → `FULFILLMENT_DEMO_ENABLED`; empty economics → no validated quote / seed + `COMMERCE_CATALOG_ENABLED`.

---

## 7. What to test to confirm progress (all green today)
```
pytest tests/services/fulfillment/ tests/services/test_commerce_catalog.py \
  tests/services/test_catalog_entities.py tests/services/test_shopify_catalog_adapter.py \
  tests/services/test_magento_catalog_adapter.py tests/services/test_supplier_catalog.py \
  tests/services/test_market_analysis.py tests/services/test_market_replay.py \
  tests/integration/test_fulfillment_api.py tests/test_*_migration.py \
  tests/test_no_flavour_in_core.py tests/test_no_silent_except_in_core.py
```
Covers: state machine + 2 gates, PO → COMPLETED, economics (catalog JOIN + wholesale fallback), canonical catalog + both adapters + the seam, Track-B detectors, single alembic head + drift, agnostic/observability ratchets. **The only thing tests can't prove is the live browser + WS + auth clickthrough (§6).**

---

## 8. What's left for a polished live demo (prioritized)
1. **Wire `inventory_level` → availability** (`recommend_fulfillment_stage`/availability) so seeded/synced canonical stock drives the case `shortfall` (today it comes from the recommend stage's own count). *Highest buyer-visible value.*
2. **Single-item out-of-stock trigger** (or lower `FULFILLMENT_BULK_THRESHOLD`) so "do you have X? → no, here are alternatives" opens a case, not just bulk orders.
3. **Build the bounded `Supplier_Inbox_Reader`** (§3) + implement the `fetch_recent_emails` stub → contextual drafts ("last quoted $X, lead 7d").
4. **Live Playwright recording** of §6 (`GATE_PROCUREMENT=1` harness in `tests/e2e/` — needs a running stack).
5. **Operator UX:** editable draft pre-approval, inline quote-evidence spans, an as-of viewer in the Journey panel.
6. **DecisionTrace ↔ case tab:** a "Fulfilment journey" tab inside `DecisionTrace.tsx` (data linked by `trace_id`; the missing UI edit).
7. **Real market sources** + `market_signal → warehouse` sink; **Phase-8 production transports** (real send/inbound/PO) — today SANDBOX by construction.

> 1–3 change what the demo *shows*; 4–6 are confidence/polish; 7 is productionization.
