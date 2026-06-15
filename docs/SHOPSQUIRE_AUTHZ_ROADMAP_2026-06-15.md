# ShopSquire — Authorization Engine & Live-Test Roadmap (resume 2026-06-15)

**Purpose:** single source of truth to resume cleanly tomorrow. Read this first.

---

## 0. Where we are (end of 2026-06-14)

The **Authorization Engine** (Tier-1 "AI proposes, this disposes" control) is built,
consolidated, tested, and shadow-safe. Three sessions of work, all green:

| Area | State |
|---|---|
| `security/authorization_engine.py` | pure `authorize()` core + `authorize_action()` orchestrator; fail-closed, idempotency, shadow/active/off modes, compromise detection, `hard_block`/`never_auto`/`enforce_lane`, observable side-effects |
| `config/authorization_policy.json` | versioned; 9 actions (6 native + refund/bank_change/pii_export/supplier_pay aligned to the legacy matrix) |
| `policy/route_enforcement.py` | **consolidation seam** — runs engine in shadow beside the legacy matrix, records parity, cutover flag `AUTHZ_ENGINE_AUTHORITATIVE` |
| Control-plane | 4 tables (migration `20260614_authz_cp`, single clean head) + `exception_resolver.py` worker + `routers/authz_audit.py` read API |
| Exception model (1.4) | terminality proof — no path falls through; only `escalate_governance` is non-autonomous |
| Anti-pattern (1.5) | `claim_grounding.py` contradicted → `reject_under_policy` + customer evidence path (no employee runtime gate) |
| Action wiring (1.2) | `supplier_order`@`inventory_agent.execute_reorder` (autonomous) + `order_modification`@`orders.cancel_order` (human). reshipment/fraud_disposition have **no execution site** — not fabricated |
| Tests | 57+ green (engine, seam, exception-model, claim-grounding, inventory, billing, privacy, authz-audit) |
| Alembic | pre-existing broken chain FIXED → single head |

Everything runs in **shadow** — zero behaviour change in production until activated.

---

## 1. IMMEDIATE RESUME — the live clickthrough test (was in progress)

**Goal:** real end-to-end test of CV-security + recommendation with two images ×
three query intents, then assess the decision trace / agent swarm.

**Harness is ready:** `c:\tmp\authz_clickthrough.py` (path bug fixed). Run:
```bash
cd /c/AI/ShopSquire && python /c/tmp/authz_clickthrough.py 2>&1 | grep -vE "Tracer|Jaeger|opentelemetry" | tail -140
```
It drives the **real app in-process** (`create_app()`/`TestClient`) against the
seeded **128-product** catalog — no Docker needed.

**What it does (3 phases):**
1. `POST /api/v1/cv/analyze` on raw bytes of both images → real QR decode / OCR /
   SSN-PII / steg / off-topic verdict (all CV libs confirmed importable locally).
2. `GET /api/v1/recommend/suggest` for each (image, query) with the CV features
   forwarded → results, NQE clarifying questions, grounding, image_feature_gate, authz.
3. Pull decision-trace events → agent-swarm sources, scatter-gather, `authorization_decision`.

**Test matrix:**
| Image | Query | Budget | What it should prove |
|---|---|---|---|
| `apple-red.jpg` (fruit, UNRELATED) | gaming | $1200–1800 | off-topic gate strips image features, still answers with gaming laptops |
| `msi-SSN.png` (MSI laptop + QR/SSN, COMPROMISED-but-relevant) | gaming | $1200–1800 | QR decoded + PII/SSN flagged + `[SECURITY]` surfaced + image_feature_gate=text_only/sanitized, **but still recommends in-budget gaming laptops** |
| `msi-SSN.png` | university | none | NQE asks budget + use-case; security still flagged |
| `msi-SSN.png` | content creation | none | NQE clarifying Q (what kind — video render? stream? photo?) — ambiguous intent |

**Known caveats to call out in the writeup (don't fabricate around them):**
- **LLM summary NOT exercised** — Ollama isn't confirmed up; harness sets
  `include_summary=false`. The *deterministic* intelligence (security, grounding,
  NQE, results, trace, authz) is real; the natural-language answer quality (BUG-6/7)
  is NOT tested here. To test it, point at a live LLM and set `include_summary=true`.
- **tesseract binary** may be absent (python `pytesseract` is present) → OCR/SSN text
  extraction may be weak even though QR decode (pyzbar) works. Harness sets
  `CV_STRICT_RUNTIME_DEPS=0` so analyze still runs. Note OCR fidelity in results.
- If trace events come back empty, read from the in-process cache
  (`decision_log.get_cached_trace_events(tid)`) — DB trace writes can be flaky on sqlite.

**Optional richer runs (after the baseline works):**
- `RECOMMEND_PIPELINE_V2=1` to exercise the **scatter-gather** pipeline and compare.
- `AUTHZ_CONTROL_PLANE_LOG=1` + apply the migration to a real DB to see exception_queue fill.

---

## 2. Docker decision (BLOCKER if you want the *full* live stack)

`docker ps` showed **GridVerdict's** containers (not ShopSquire) holding ports
**5432 + 6379**. ShopSquire's compose wants those same ports → conflict.
Options for tomorrow (pick one):
- **(a)** Stop GridVerdict (`docker compose -p gridverdict down`) then
  `docker compose up -d` ShopSquire (self-seeds + has Ollama/workers/real Postgres).
- **(b)** Add a compose override mapping ShopSquire db/redis to 5433/6380 (no host
  conflict; api talks to them over the compose network anyway).
- **(c)** Stay in-process (Section 1) — enough for everything except real LLM summary
  + real Celery/Neo4j.
> This is a user decision (don't stop another project's stack unprompted).

---

## 3. Assessment deliverables the user asked for (produce after the run)

Using the real trace output, write up:
1. **Delta vs previous tests** (compare to `dump/` screenshots: smart-1/2, lenovo-multimodal,
   sec-LLM-summ, where-payload, agents-decision-trace).
2. **Per-agent bitemporal decision trace**, parallel agent swarm, scatter-gather behaviour.
3. **Improvements now live** (authz engine, consolidation, exception model, anti-pattern fix,
   off-topic gate, QR/SSN surfacing, control-plane audit API).
4. **Stakeholder reactions:** shopper (does it answer + feel safe?), AI engineer
   (grounding/NQE/trace quality), security (QR/SSN/compromise handling, audit trail).
5. **Investor case** vs Shopify/Magento/Agentforce/CrowdStrike/Darktrace — the
   bitemporal audit + in-pipeline security + bounded autonomy is the unoccupied quadrant.
6. **What to do next** (Section 4).

---

## 4. Remaining build roadmap (after the test)

**Finish Tier 1 (activation):**
- Run shadow, watch `shopsquire_authz_parity_total{agree="false"}`; when clean, flip
  `AUTHZ_ENGINE_AUTHORITATIVE=1` (seam) and per-action `AUTHZ_ENGINE_MODE=active`.
- Wire `claim_grounding.ground_claim()` into the returns flow (it has NO caller yet).
- Schedule `exception_resolver` Celery task on beat.
- Apply migration `20260614_authz_cp` to the real DB so control-plane tables exist.

**Tier 2 (depth / close the loops):** shipping de-stub (label/track + reshipment loop →
then gate `reshipment`); order/payment state machine (guard illegal transitions e.g.
refund-after-chargeback); inventory auto-reorder loop close (detect→authorize→PO→receive→restock);
supplier procurement automation; verify autonomous repricing within bounds.

**Tier 3 (certification):** produce the 6 artifacts (Use-Case Set, RTM, Module List,
Interaction Diagram, Exception Model [done via test], Validation Checklist [from eval harness])
and pass the 8 review gates.

---

## 5. Quick reference — env flags
`AUTHZ_ENGINE_MODE` (shadow|active|off) · `AUTHZ_ENGINE_AUTHORITATIVE` (cutover) ·
`AUTHZ_CONTROL_PLANE_LOG` · `AUTHZ_POLICY_PATH` · `AUTHZ_IDEMPOTENCY_TTL` ·
`CV_STRICT_RUNTIME_DEPS` · `RECOMMEND_PIPELINE_V2`

Metrics: `shopsquire_authz_decisions_total`, `_authz_parity_total`,
`_authz_write_failures_total`. Audit API: `GET/POST /api/v1/authz/*`.
