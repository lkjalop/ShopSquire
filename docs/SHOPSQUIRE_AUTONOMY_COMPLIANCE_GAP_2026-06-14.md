# ShopSquire vs. the Autonomous-Enterprise Rubric — Compliance & Gap Analysis
**Date:** 2026-06-14 · **Inputs:** the 3 reference decks (Technology Evaluation; AI Architect Playbook; Fully Autonomous Enterprise) · **Question:** what's the delta to *full, compliant, bounded agentic AI with minimal human oversight?*

> The three decks are, in effect, the **formal rubric** for "a real bounded-autonomous enterprise." ShopSquire is the **Path C — Custom-Built AI** answer they describe. This maps ShopSquire against that rubric honestly: ✅ done · ⚠️ partial · ❌ missing.

---

## 0. The frame (and the good news)
The decks' own **Build-vs-Buy doctrine** says: *buy commodity/regulated (storefront, payments, shipping labels), manage infrastructure, and **build only the differentiating intelligence + autonomy control**.* ShopSquire's effort allocation **already matches this**: it integrates payments (×5), shipping providers, etc., and has **built the hard, differentiating core** — the AI-control, anti-hallucination, trust, and audit layers. The decks call that core *"the most important security control in the architecture."* So ShopSquire isn't far from the target on the part that's hard to build; the gaps are mostly **control-plane plumbing, a few domain loops, and the formal artifacts that *prove* it.**

---

## 1. The 5 Operating Doctrines

| Doctrine | Status | Evidence / Gap |
|---|---|---|
| **1. Zero-Employee Runtime** | ⚠️ | Strong autonomous flow, BUT runtime paths still route to a human *employee* (e.g. claim-contradiction → `route_human_review`). The decks list "manual review queue / escalate to human agent" as an **anti-pattern**. Asking the *customer* to clarify is fine; waiting on an *employee* is not. → must become a bounded autonomous outcome. |
| **2. AI Is the Operator** | ✅ | Orchestrator (EXPLORE→EVALUATE→PLAN→ACTION) + named agents run operations; not a bolt-on chatbot. |
| **3. Policy-Bounded Autonomy** | ✅ (strong) ⚠️ (scattered) | This *is* the thesis — grounding ladder, confidence gates, `autonomy_tier` (denied/escalated). But authorization is **scattered** across `image_feature_gate`, `tool_intent_gate`, `maestro_boundaries`, `object_authz` — not one engine. |
| **4. Exception Handling Is Core** | ⚠️ | Per-domain handling exists, but no **unified exception model** guaranteeing a terminal autonomous outcome for every category, and no `exception_queue` / `retry_tracking`. |
| **5. Auditability Is Mandatory** | ✅ (mostly) | `decision_log` + WORM chain + the Decision Trace cover attribution/replay. Missing `policy_evaluation_log` + `AI_interaction_log` for *full* replay. |

## 2. The Critical Control — AI Authorization Boundary (deck's #1 control)
*"AI-generated outputs must NEVER directly become privileged system actions. Every customer-impacting action passes deterministic policy validation."* Six actions require it: **refund, return approval, order modification, reshipment, supplier order, fraud disposition.**

**Status: ⚠️ — the seed exists, not the engine.** The **grounding ladder is the perfect template** ("AI proposes, catalog disposes" = the deck's "separation of conversational output from privileged execution"). But it's only applied to *product identity*. The six privileged actions don't yet pass through **one** deterministic authorization gate. **This is the highest-value compliance build.**

## 3. The 9–13 Business Domains (coverage)

| Domain | Status | Note |
|---|---|---|
| Storefront & commerce (recs/NLP) | ✅ | strongest area |
| Orders & payments | ⚠️ | `orders.py`, `payments×5` exist; full deterministic **state machine** unproven |
| Inventory & replenishment | ⚠️ | `inventory_agent` + 5 modules; closed-loop **auto-reorder** loop to verify |
| Supplier coordination | ⚠️ | `supplier_domain_guard` is security-side; **machine-to-machine procurement** thin |
| Shipping & fulfillment | ⚠️ | providers + webhooks exist, but `shipping_stub.py` = not fully live |
| Support, returns & refunds | ✅ | claim grounding, CV triage, `returns.py` |
| Fraud & trust | ✅ | observer, `fraud_scorer`, GNN/transformer fraud, security membrane |
| Governance & audit | ✅ | decision trace, WORM, `decision_log` |
| Pricing & promotion | ⚠️ | `pricing.py` + `bundle_pricing` exist; autonomous repricing unproven |
| Analytics & optimization | ⚠️ | RAGAS/drift/eval present; optimization loop partial |

## 4. The Control-Plane Data Entities (deck: "not optional")

| Entity | Status |
|---|---|
| `decision_log` | ✅ present |
| `anomaly_detection` | ✅ present |
| `exception_queue` | ❌ **missing** |
| `retry_tracking` | ❌ **missing** |
| `policy_evaluation_log` | ❌ **missing** |
| `AI_interaction_log` | ❌ **missing** |

**4 of 6 mandated tables are missing.** Without these you cannot *prove* replay, bounded retries, or policy-decision audit — i.e. you can't pass the deck's review gates.

## 5. The 6 Formal Architecture Artifacts — ❌ largely not produced
Use-Case Set · Requirements Traceability Matrix (with **Human-Dependency = No** per row) · Module List (formal responsibilities) · Interaction/Data-Flow Diagram · **Exception Model** · **Validation Checklist (8 gates)**. The **eval harness is a partial Validation Checklist** (good start). The rest exist as scattered docs/code, not as the formal coverage-control deliverables the decks require to *certify* zero-employee viability.

---

## 6. What we're ALREADY doing well (don't rebuild it)
- **The differentiating core** the decks say is where the value is: the **grounding ladder** (anti-hallucination = the "separate generation from action" control), the **security membrane**, **claim grounding**, the **decision trace** (auditability), **policy-bounded autonomy** + `autonomy_tier`.
- **Build-vs-buy posture is correct** — integrating commodity (payments/shipping/storefront), building the intelligence.
- **A real eval** (precision/recall/grounding/escalation-precision) = the seed of the Validation Checklist.
- **Most domains have code** — breadth exists; depth/closed-loop is the question.

---

## 7. THE DELTA — to full, compliant, minimal-oversight autonomy

### Tier 1 — Control-plane (makes it *provably* bounded; highest leverage)
1. **Unified deterministic Authorization Engine** — generalize the grounding ladder's "propose vs. dispose" to gate all 6 privileged actions (refund, return, order-mod, reshipment, supplier-order, fraud-disposition). *The deck's #1 control.*
2. **Add the 4 missing control-plane tables** (`exception_queue`, `retry_tracking`, `policy_evaluation_log`, `AI_interaction_log`).
3. **Formal Exception Model** — every exception category → a guaranteed terminal autonomous outcome (retry / fallback-to-rules / request-customer-clarification / substitute / refund / quarantine / safe-pause). No unresolved runtime state.
4. **Remove the runtime human-employee dependency** — convert `route_human_review` (contradicted claim, etc.) into bounded outcomes (reject-under-policy + offer customer an evidence path). Human review → governance-only, never a runtime gate.

### Tier 2 — Domain depth (close the loops to true autonomy)
5. De-stub **shipping**; prove the **order/payment state machine**; close the **inventory auto-replenishment** loop; add **supplier procurement automation**; verify **autonomous repricing**.

### Tier 3 — Formal artifacts (pass the 8 review gates on paper)
6. Produce **Use-Case Set, RTM (Human-Dependency=No), Module List, Interaction Diagram, Exception Model, Validation Checklist**; run **Gates 1–8** with evidence. (The eval harness + decision trace already supply much of Gates 6–8's evidence.)

---

## 8. The one doctrinal correction worth internalizing
Our "**bounded autonomy with a human-in-the-loop**" needs a precise edit to be *compliant*: the loop's human may be the **customer** (clarification) or a **bounded autonomous fallback** — but **never a runtime employee**. Employees belong only in **governance** (review audits, adjust policy, authorize strategy), never in the daily runtime path. Today, exactly one place crosses that line (`route_human_review`); fixing it is small and makes the autonomy story doctrinally clean.

## 9. Honest verdict
ShopSquire is a **strong Path-C build of the hardest, most differentiated layer** (AI control + trust + audit) — the layer the decks say to build and that proves hardest. To reach **"full, compliant, minimal-oversight"** it needs, in order: **(1) the deterministic authorization engine + 4 control-plane tables + formal exception model** (provability), **(2) closing a few domain loops** (breadth→depth), **(3) the 6 formal artifacts + 8 gates** (certification). None of these are research problems — they are disciplined plumbing, loop-closing, and documentation. The differentiating intelligence is already here.
