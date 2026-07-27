# ShopSquire — Whole-Platform Assessment (2026-07-27)

*Every number below was measured from the working tree today, not carried forward from a prior doc.
Where a doc and the tree disagree, the tree wins and the disagreement is noted.*

---

## 0. What this thing actually is, in one paragraph

ShopSquire is a **governed commerce-decision layer**: a conversational buyer surface and a merchant
operator surface sitting on top of a catalog, a procurement FSM, and a payments spine — where every
recommendation, refusal, discount, and supplier action is produced by a *model that proposes into a
bounded vocabulary*, *clamped by deterministic gates*, and *written to a per-decision audit trail*.
It is **not** a storefront, not an ERP, and not a recommender. The recommender is the demo surface.
The product — if there is one — is the **refusal-with-evidence trace**.

---

## 1. Measured scale

| Area | Files | Lines |
|---|---:|---:|
| `src/` | 925 | 253,686 |
| `tests/` | 995 | 95,527 |
| `scripts/` | 177 | 17,122 |
| `frontend/` | 100 | 18,405 |
| `alembic/` | 65 | 5,077 |
| **Total** | **2,265** | **390,238** |

- 115 routers · 384 services · 136 security modules · **704 registered routes**
- App boots cold in **4.0s**
- 1,219 commits since 2026-01-20. **89% of them (1,083) landed in June + July.** The first five
  months were exploration; the platform as it exists now is ~8 weeks old.
- Test-to-source ratio ≈ **0.38** — high for a solo project, and it is the single most important
  number in this document.

---

## 2. Does it work? — today's live evidence

`tmp/quality/replay_20260727.json` — 27-turn stateful replay, live `qwen3:14b` router, 147s wall.

| Gate | Value | Threshold | Verdict |
|---|---:|---:|:--|
| p95 latency | **6,906 ms** | ≤ 8,000 | ✅ |
| empty_rate | **6.25%** | ≤ 15% | ✅ |
| unauthorized_rate | **0.0** | = 0 | ✅ |
| constraint_satisfaction | **80.3%** | ≥ 70% | ✅ |
| precision@10 | **68.3%** | ≥ 60% | ✅ |
| NDCG@10 | **68.7%** | ≥ 60% | ✅ |
| classified_shown_rate | **100%** | ≥ 98% | ✅ |
| fallback_rate / timeout_rate | **0% / 0%** | ≤ 1% | ✅ |
| labeled_coverage | **31.25%** | ≥ 30% | ✅ (barely) |
| **`gates_pass`** | **False** | — | ❌ |

`gates_pass: False` because the V1-vs-V2 parity ledger still records **6 BLOCKER / 13 MAJOR**
divergences. Those are adjudicated (§6) — most are *V1 being wrong* — but the harness refuses to
call itself green while they sit unresolved. **That refusal is the healthiest thing in the repo.**

Diagnosis block from the same run: 61 `meets` / 15 `fails` / **0 `unknown`** across 76 verdicts;
top failed key `gpu_vram_gb` (14). Read: *retrieval/ranking gap, not a truthfulness gap* — products
are being retrieved that genuinely fail a requirement, and the system says so rather than hiding it.

Just re-run for this assessment: **218 passed, 0 failed** across V2 core + facade + facade-cart +
gates + ranking + envelope + stages + all `tests/architecture` + V2 compatibility.

### 2.1 Security suite — 11 failures, triaged

`tests/security` + the three hygiene ratchets, run for this assessment (deterministic order).
Every failure was re-run in isolation to classify it. **None is a security regression**, but two are
real and one is embarrassing:

| Count | Class | Detail |
|---:|---|---|
| **1** | ⚠️ **Real — the ratchet doing its job** | `test_no_silent_except_in_core` caught a **new** silent `except (TypeError, ValueError): continue` at [recommendation_facade.py:572](../src/app/services/recommendation_facade.py#L572), added **in the uncommitted batch** (confirmed via `git diff`). It silently drops a malformed budget slot — the exact failure mode that produced the negated-budget bug class. **Fix: log `stage_partial_failure`; do NOT raise the baseline.** |
| **1** | ⚠️ **Real — the differentiator is off by default** | `test_decision_trace_retention` → `/api/v1/decisions/{id}` returns **404**. Cause: `DECISION_LOG_WRITES_ENABLED: false` in `config/feature_flags.json`. `config.py` re-defaults it ON in production, so this is a *local/demo posture* issue — but the audit trail, the thing this whole platform is arguably *for*, does not write in the default dev config. |
| **3** | 🟡 **Stale tests — code is more secure than the test** | `test_linked_artifact_analysis` asserts `'123-45-6789' in ['***-**-6789']`. The SSN masking landed and these tests still assert the **raw** SSN. The tests are wrong; the code is right. Update them. |
| **6** | 🟡 **Test-order pollution** | `admin_playbooks_governance` ×2, `admin_playbooks_ops`, `flag_dual_approval`, `email_security_siem`, `trace_contracts_matrix_gate` — **all pass in isolation**, fail in-suite. Shared-state leakage between tests. Not a defect, but a suite that only passes in isolation is a suite CI cannot trust. |

*(Total pass count unavailable — the captured output was truncated to its tail.)*

---

## 3. What the platform can actually do

**Buyer lane (V2 core, live):** SEARCH · FILTER · COMPARE · EXPLAIN · SUPPORT_CLAIM · CART_MUTATE ·
PROCUREMENT · OFF_CATALOG · POLICY_QUESTION · INVENTORY — 10 lanes, model-classified into a closed
vocabulary, clamped against a 47-node sold taxonomy, with a *sellability refusal gate* that makes
"we don't sell that" a platform decision rather than a prompt instruction.

**Merchant/operator:** procurement RFQ → case → PO → GR/INV with irreversibility gates and a
human-only external-send invariant; multi-location availability + transfer plans; supplier
scorecards (859 audit rows); margin advisor with bulk price-breaks; velocity/DSI, demand trend,
governed replenishment proposals; executive pulse + margin intelligence panels.

**Security/governance:** shift-left guard on every recommendation surface; prompt-injection and
model-theft ingress blocks; steganography detection; QR-external → text-only wipe; PCI/SSN
redaction; CV return-fraud triage; email XDR with quarantine and disposition; SSRF allowlist;
fail-closed money ledger with idempotency; bitemporal decision log (**229,307 rows** in the demo DB).

**Surfaces:** shopper SPA + embeddable widget + admin React console (27 components incl. Decision
Trace, Market Intelligence, Procurement Cases, GRC, Email XDR) + 13 CI workflows.

---

## 4. The "it's all bullcrap and you wasted 7 months" case — steelmanned

I am going to make this argument as well as a hostile reviewer would, because the weak version is
useless to you.

1. **The catalog is 134 products in one vertical, 131 of them with a NULL category.** Every quality
   number in §2 is measured on a **27-turn corpus you wrote yourself**, graded against **8 hand-drafted
   relevance cases**. n is tiny and the oracle is in-house.
2. **The labels were drafted by an AI and never human-sealed** — `human_reviewed_by: null`. The
   quality gate is grading its own homework. That is stated honestly in the file, which is to your
   credit, and it is still true.
3. **Zero real users, zero real traffic, zero pilots, zero revenue.** Nothing in the repo has ever
   met an adversary who wasn't imagined by its author.
4. **390k lines / 704 routes / 384 services to recommend laptops.** A reviewer will call that sprawl,
   not scope, and they will not be entirely wrong.
5. **The security posture is untested against real attackers.** They are tests you wrote against
   attacks you thought of. That is necessary and it is not evidence of resistance.
6. **Large parts are built-but-dark:** `EXTERNAL_RESEARCH_ENABLED=false`, the Steam live lane exists
   but is never called with `allow_live=True`, CLV/churn endpoints have no UI, `external_stock` does
   not exist so there is no supplier ATP feed at all.
7. **The latency numbers don't survive contact with load.** 6.9s p95 is one turn on one local Ollama
   on a 12GB consumer GPU. Concurrency was never tested and cannot be on this hardware.
8. **The overfit is visible to a sharp viewer in one question.** Nine Steam fixtures. Ask about a
   tenth game and the system falls back to a flat `gaming` floor that cannot distinguish path-traced
   Cyberpunk from Minecraft.

That is a serious case. Anyone who dismisses it is not helping you.

---

## 5. The honest rebuttal — and what 7 months actually bought

**The rebuttal is not "but look at all the features."** Features are the weakest evidence here.
The rebuttal is four specific things:

1. **A measurement rig that can prove the system wrong.** `gates_pass: False` on a run where every
   individual metric passed. A machine-readable V1/V2 adjudication ledger where all 19 divergences
   carry an owner, a disposition (`known_wrong_v1` / `v2_regression` / `accepted_v2_contract` /
   `data_gap`), and a status. Two hygiene ratchets (`test_no_flavour_in_core`,
   `test_no_silent_except_in_core`) wired into a **mandatory** CI job with no `|| true` on the path.
   Most projects at this stage cannot tell you whether they got better last week. This one can, with
   numbers, and has caught its own author repeatedly.

2. **The refusals are real, measured, and correct — including when they're inconvenient.** The
   sharpest example in the tree: V2 **refuses to numerically compare a USD Dell against an AUD
   Lenovo without approved FX**. V1 happily compared them and was wrong. That refusal is recorded
   as a `BLOCKER` in the parity ledger and adjudicated `known_wrong_v1`. A system that gets *worse*
   on a parity metric because it stopped lying is a system with a spine.

3. **The second implementation is smaller than the first and keeps the safety properties.**
   `recommendation_core/` = **6,365 lines across 18 modules** replacing a **12,536-line** router with
   an **8,111-line function**. That is the rewrite going the right direction, which is rare.

4. **It runs.** Boots in 4s, 704 routes, live 27-turn replay completed today in 147s against a real
   local model, 218 targeted tests green.

**What the 7 months bought:** an architectural doctrine that survived 11 adversarial review cycles,
a second implementation that is half the size of the first, and an evidence trail that lets you
answer "does it work?" with numbers.

**What it did not buy:** a customer, a second vertical, a load-tested deployment, or human-sealed
ground truth. Those are the four things that convert this from a project into a product, and none of
them are engineering problems you can solve by writing more code.

**Verdict:** it is not bullcrap, and it is also not a product. It is a *working system with an
unusually good conscience and no customer.* The risk is not that the work was wasted — it's that the
next 7 months get spent the same way.

---

## 6. Where V1 → V2 actually stands (the delta you asked for)

### Transport: DONE
- `main.py:44` now imports `recommend_compat` (84 lines), **not** `recommend`. The 12,536-line legacy
  router is **not registered**.
- `/api/v1/recommend/suggest` is a deprecated compat route → `serve_v2_compatibility` (315 lines) →
  typed V2 facade. Emits `Deprecation`, `Sunset: 2026-09-30`, successor `Link`, engine header.
- `legacy_recommendation_delegate.py` is now 22 lines and calls V2.
- All 10 sibling endpoints extracted: `recommendation_checkout` (233) / `_explain` (246) / `_nqe`
  (216) / `_feedback` (306) / `recommend_aux` (42). **`recommend.py` now holds exactly one route.**
- The widget posts to `/api/v1/chat/query`.

### Capability parity: NOT done — this is the real delta
From `RECOMMEND_PY_ARCHIVE_READINESS_2026-07-27.md`:

| Area | Result | The actual gap |
|---|---:|---|
| Legacy multimodal + bulk pack | 8 pass / **17 fail** | image-brand constraints, QR status/security matrix, NQE generation + persistence, persona, image relationship, bulk availability |
| Reference acceptance matrix | 17 pass / **4 fail** | V2 taxonomy fixtures, durable incident evidence, timing envelope, multi-use-case tags |
| Follow-up suite | 3 pass / **3 fail** | V2 session budget carry-forward |
| Golden workload | 16 pass / **1 fail** | Stable Diffusion response lacks explicit GPU/VRAM/cloud honesty |

### Evidence pin: NOT done
**~25 test modules still import `src.app.routers.recommend` private helpers** (the readiness doc says
13 — the tree says 25; the doc undercounts). Until that hits zero, `git rm` destroys characterization
evidence and breaks collection. Each must move to: a V2 service contract, a compat-route contract, or
frozen characterization data.

### IMAGE: no V2 implementation at all
The one lane with zero V2 coverage. Legacy image is threaded through ~20 conditionals in
`recommend.py`. Live benign-image request returns **25.17s bounded degradation** with
`vision_provider_timeout` — honest, but not interactive. Root cause is hardware: 9.3GB text model +
6.1GB vision model cannot co-reside on 12GB VRAM. Smaller candidates were rejected on quality
(Moondream returned empty identity; LLaVA **fabricated** brand/model evidence).

### ⚠️ And the whole cutover is UNCOMMITTED
37 modified + 20 untracked files, ~2,600 lines, including `main.py`'s router swap and the entire
`recommend_compat` + `recommendation_compatibility` path. **The single most important architectural
change in the project is sitting in the working tree with no commit.** Fix this first — it is 10
minutes of work protecting 2 weeks of it.

---

## 7. What "pilot-ready" means (a definition you can hold someone to)

Pilot-ready ≠ feature-complete. **Pilot-ready = a named design partner can run real traffic through
it, on their data, for a bounded window, without you in the room — and afterwards you can both tell
whether it helped.** Five conditions:

| # | Condition | State |
|---|---|:--|
| 1 | **Safety floor** — cannot do irreversible harm unattended | ✅ **close.** human-only send, `unauthorized_rate` 0.0, fail-closed money ledger, SSRF allowlist, injection/model-theft blocks |
| 2 | **Identity & isolation** — tenant identity not client-asserted | ❌ **open.** tenant = raw `X-Tenant-Id` header in 49 places; ABAC allowlist exists and fails closed, but an *empty* allowlist allows all — the default posture |
| 3 | **Truthfulness on THEIR data** — right, or labeled absent | ❌ **open.** currency authority missing (AUD+USD mixed, no store currency on `TurnEnvelope`); `external_stock` absent (no supplier ATP); 42 modules use SQLite-only SQL (`datetime('now')`, `strftime`) |
| 4 | **Operability** — deploy, migrate, roll back, observe, on-call | ⚠️ **partial.** 8 docker-composes, alembic at head, 13 CI workflows, Prometheus metrics ✅ — but no rollback rehearsal and **no load test** (Ollama single-turn ≠ concurrency; needs vLLM/TGI + replicas) |
| 5 | **A measurable "did it help?"** | ❌ **open.** labels unsealed (`human_reviewed_by: null`), corpus is 27 self-authored turns, no partner-agreed baseline metric |

**By this definition: not pilot-ready. 1 is close, 4 is partial, 2/3/5 are open.**
Distance ≈ **3–6 focused weeks** on items 2/3/4/5 — *provided you stop adding surface.*

---

## 8. Blocker list, ranked by what actually gates a pilot

| # | Blocker | Why it gates | Owner | Effort |
|---|---|---|---|---|
| **B0** | **Cutover is uncommitted** | 2,600 lines of the critical path exist only in your working tree | ME | 10 min |
| **B0.5** | **New silent-swallow in the uncommitted facade** (§2.1) + **decision-log writes off by default** | a dropped budget slot goes untraced; the audit differentiator doesn't write in dev config | ME | 30 min |
| **B1** | **Currency authority** | budget filtering compares AUD to USD; blocks every budget-sensitive turn on any real mixed-currency catalog. This is a *correctness bug*, not a parity artifact | ME | S–M |
| **B2** | **Tenant identity from header** | one client can assert another's tenant unless an allowlist is configured; disqualifying for multi-tenant pilot | ME | M |
| **B3** | **Labels unsealed** | every quality claim is measured against an unverified spec; you cannot prove V2 ≥ V1 or compare router models | **YOU** | 2–4 hrs |
| **B4** | **IMAGE lane has no V2** | pins `recommend.py`; and 25s vision degradation is not interactive | ME | 1–2 wks |
| **B5** | **~25 test imports of legacy helpers** | `git rm` breaks collection until zero | ME | 2–3 days |
| **B6** | **No load test** | 6.9s p95 is a single-turn number on consumer hardware | ME + infra | M |
| **B7** | **Workload overfit** (9 fixtures, live lane never called) | first sharp question in any demo: "does it only know Cyberpunk?" Today: effectively yes | ME | S (one arg + data) |
| **B8** | **`compare_two_models` named binding** | blocks COMPARE canary; currently data-blocked on FX (folds into B1) | ME | S after B1 |
| **B9** | **`chat.py` duplicate regex router** | 5 regex intent functions duplicating the core router — the exact doctrine violation ("never a second copy of a decision surface") that produced the negated-budget bug class | ME | M |
| **B10** | **42 SQLite-only SQL modules** | `bi_intelligence` and friends will not run on the Postgres a pilot needs | ME | M |

---

## 9. Files that need refactoring / re-architecting

| File | Lines | Verdict |
|---|---:|---|
| `src/app/routers/recommend.py` | 12,536 | **DELETE target.** One route left; unregistered; held alive only by test imports |
| `src/app/routers/admin.py` | 4,169 | Split by domain; unrelated to the V2 arc but the second-worst file |
| `src/app/routers/support_complaints.py` | 3,990 | Router doing service work; extract |
| `src/app/services/orchestrator.py` | 3,960 | 4-phase orchestrator; overlaps `recommendation_core` — **decide which one is the brain** |
| `src/app/routers/chat.py` | 3,251 | **Highest-value refactor after the delete.** `_chat_query_impl` is a 1,533-line god-function containing a ~470-line image-CV subsystem and a duplicate regex router. Target: ~400-line transport edge + `image_edge.py` + `chat_presentation.py` |
| `src/app/routers/admin_email_security.py` | 3,244 | Extract service layer |
| `src/app/routers/merchant_dashboard.py` | 3,203 | Extract service layer |
| `src/app/security/email_security.py` | 2,833 | Cohesive but oversized; split by concern |
| `src/app/main.py` | 2,642 | 704 routes + middleware stack in one file; extract middleware + startup |
| `src/app/routers/decisions.py` | 2,628 | SSE + query + replay in one router |
| `src/app/services/recommendations.py` | 2,297 | Legacy sibling of `recommendation_core` — **duplicate decision surface**; audit and fold or delete |
| `src/app/routers/admin_bi.py` | 2,033 | Split; also holds the dark CLV/churn endpoints |

**Architectural (not file-level) items:** the connector interface should be generalized from the
Steam pattern into a registry (`KnowledgeConnector` protocol with trust tiers) before a second
vertical lands; the claim guard should ground against the *evidence set*, not just the catalog; and
`orchestrator.py` vs `recommendation_core` needs an explicit ownership decision before either grows.

---

## 10. How it compares — honestly

| Player | What they own | What they structurally will not build |
|---|---|---|
| ChatGPT Instant Checkout · Gemini AI Mode · Rufus · Perplexity | buyer-side discovery → checkout, enormous distribution, far better models | per-decision governance trace, procurement/RFQ, merchant margin. **Conversion is their metric; a refusal is a loss.** |
| Salesforce Agentforce Commerce | conversational + merchant agents, real enterprise distribution | open decision trace, procurement governance, margin-gated action authorization |
| SAP IBP · NetSuite · Blue Yonder | ROP/EOQ/MAPE/ATP planning, the actual system of record | conversational surface, per-decision bitemporal audit, human-gated agentic action |
| Shopify Sidekick · Magento | merchant copilot inside the platform they own | depth; cross-stack; governance artifact |

**The claimed intersection** — ERP-grade metrics feeding bounded-autonomy gates, surfaced
conversationally, with per-decision audit — **is genuinely unoccupied.** But be careful with that
argument: intersections are usually empty because each column's incumbent has distribution you don't,
not because nobody thought of it.

**The sharper version of the pitch:** the recommender is commodity and you will never win it. What is
rare is a system that can show, per decision, *why it refused, what evidence it held, who authorized,
and what it would have needed to act.* That is a **compliance artifact** — and under EU AI Act /
NIST AI RMF, decision-level auditability stops being a nice-to-have. That is the thing the
conversion-optimized incumbents will not build, because for them a refusal is a lost sale, and for
your buyer a refusal is a prevented loss.

**Why anyone would care, in their language:** a mid-market merchant does not want a smarter chatbot.
They want to not stock out, not sit on dead capital, not get defrauded on returns, not have an agent
email a supplier something stupid, and to be able to *explain the decision afterwards*. This platform
is aimed at exactly that list. It has not yet proven it on anyone's data but its own.

---

## 11. What I would do next, in order

1. **Commit the cutover** (B0). 10 minutes.
2. **Seal the 8 labels** (B3) — the only item on the list nobody but you can do, and it unlocks every
   quality claim downstream.
3. **Currency authority** (B1) — store/tenant currency on `TurnEnvelope`, same-currency-or-refuse.
   It fixes a real bug, unblocks B8, and removes the largest class of MAJOR divergences.
4. **Tenant identity from the authenticated principal** (B2) — the one thing that makes a
   multi-tenant pilot legally discussable.
5. **Live Steam lane + fixture expansion** (B7) — one argument and a data file; removes the single
   most obvious "this is rigged" criticism, and it is the *proof* of the BYO-model thesis: a small
   model plus a live connector beats a big model with stale memorized specs.
6. Then, and only then: IMAGE V2, the `chat.py` strangle, and the second vertical.

**Everything in the roadmap docs from the last ten days** — pharmacy vertical, connector registry,
exec-metrics Phases 5–7, forecast-accuracy loop, cadence replenishment, policy packs, streaming UX,
voice, MCP, temporal hippograph — **is good work and none of it should start before items 1–5.**
Those documents describe roughly six months of new surface. Items 1–5 are the ones that turn this
from a project into something a stranger can run.

---

*Assessment only. No code was changed.*
