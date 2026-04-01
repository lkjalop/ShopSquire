# ShopSQUIRE Eval Slide Rewrite

Date: 2026-03-29

Purpose:

- make `dump/ShopSQUIRE- Eval.pdf` more defensible
- reduce word count
- sharpen positioning
- give speaker notes that survive technical criticism

---

## Overall Positioning Change

Current deck strength:

- strong architecture story
- strong moat story
- strong guardrails + trace story

Current deck risk:

- a few claims are too absolute
- some phrases imply production/compliance certainty the platform does not yet support
- some lines are longer than they need to be

Recommended framing:

- not "fully autonomous production platform"
- instead: "bounded agentic commerce intelligence layer with auditability, security, and human-governed action paths"

Use these default replacements throughout:

- Replace `full autonomy` with `bounded autonomy`
- Replace `PII never leaves your environment / COLO` with `PII can stay local with local model routing`
- Replace `SOC evidence ready` with `evidence-oriented control trail`
- Replace `legally defensible` with `defensibility-oriented`
- Replace `production-ready` with `pilot-ready` unless you are discussing a specific subsystem

---

## Slide 1

### Current issue

Too absolute:

- `Full autonomy by design`
- `TARGET Near-zero-staffing autonomous operation — not a chatbot`

### What to change

Keep the comparison, but soften the certainty.

### Suggested rewrite

Title:

`The Evaluation Question`

Subtitle:

`Which path best supports auditable, low-headcount commerce operations?`

Body:

- `Path A  Turnkey SaaS`
- `Fastest to deploy`
- `Limited decision trace`
- `Shared vendor boundaries`

- `Path B  Configurable Platforms`
- `More workflow control`
- `Still bounded by vendor architecture`
- `Limited audit depth`

- `Path C  Custom AI Layer`
- `Bounded autonomy`
- `Security inside the pipeline`
- `Replayable decision trace`

Footer:

- `Scope: support, returns, refunds, general inquiries`
- `Goal: high automation with strict guardrails`

### Word-count cut

Approx. 30-40% reduction if you remove repeated negatives and compress the footer.

### Talking points

- The decision is not "buy AI vs build AI." It is "what level of control, traceability, and safety do we need?"
- Turnkey tools are strong for workflow speed but weak for system-level auditability.
- Configurable tools improve control, but still inherit a platform ceiling.
- ShopSquire is justified only if the requirement includes traceability, policy enforcement, and security-native orchestration.
- The real differentiator is not LLM output quality alone. It is governed action.

### Terms to understand

- `Architecture ceiling`: limits imposed by a vendor platform that you cannot redesign.
- `Bounded autonomy`: agents can act inside explicit constraints, not open-ended freedom.
- `Replayable decision trace`: ability to reconstruct what the system saw, decided, and why.

---

## Slide 2

### Current issue

Mostly good, but a few numbers look more precise than the proof currently supports:

- `< 2s P95 response latency`
- `> 0.8 Retrieval quality (RAGAS)`
- cost claim if challenged may need exact measurement context

### What to change

Keep the architecture shape, reduce numeric specificity unless you can show measurement provenance live.

### Suggested rewrite

Title:

`Rules First. Models Last.`

Subtitle:

`The model handles exceptions. Deterministic systems handle the rest.`

Body:

- `50+ pre-LLM rules`
- `Many requests resolved before model use`

- `Complexity router`
- `Small model for simple cases`
- `Stronger model for harder cases`
- `Vision lane for image-heavy cases`

- `Context graph + session memory`
- `History, constraints, and retrieved evidence`

- `CV / OCR enrichment`
- `OCR, QR, fraud, and product signals`

Footer:

- `Outcome: higher automation, lower model spend, stronger control`

### Optional numeric version

If you want numbers, use:

- `High LLM bypass rate on routine traffic`
- `Sub-second to low-second response targets`
- `Lower model spend than cloud-heavy stacks`

### Talking points

- This is not a chatbot architecture. It is a routing architecture.
- You do not want the LLM reasoning over trivial or policy-fixed work.
- The more deterministic the first layer, the more reliable and cheaper the whole system becomes.
- Session memory and graph context matter because follow-up questions and buyer intent collapse without state.

### Terms to understand

- `Complexity router`: a gate that assigns work to the cheapest sufficient reasoning path.
- `LLM bypass rate`: percentage of requests resolved without calling an external or heavy model.
- `Context graph`: structured memory and relationships used to improve retrieval and continuity.
- `RAGAS`: a framework for evaluating retrieval-augmented generation quality. Useful, but do not oversell any single score.

---

## Slide 3

### Current issue

Strongest slide in the deck, but it overclaims in places:

- `Sale never stopped`
- `SOC evidence ready`
- `WORM logs 5yr`

### What to change

Keep this as the hero slide, but make the claims demonstrable instead of absolute.

### Suggested rewrite

Title:

`Built To Operate Under Attack`

Subtitle:

`Parallel agents, narrow permissions, and replayable decisions.`

Buyer side block:

- `NLP + computer vision`
- `CV labels + OCR`
- `QR inspection`
- `steg / fake-image checks`
- `26-signal fraud scoring`
- `policy gating before action`

Email block:

- `Email threat pipeline`
- `SPF / DKIM / DMARC`
- `YARA + attachment analysis`
- `semantic BEC scoring`
- `verdict + playbook`

Trace block:

- `Bitemporal decision trace`
- `agent steps`
- `time-aware audit history`
- `tamper-evident chain`
- `replay support`

Framework footer:

- `PASTA · STRIDE · DREAD · MITRE ATT&CK · MITRE ATLAS · OWASP LLM`

### Remove

- `Sale never stopped`
- `SOC evidence ready`
- `WORM logs 5yr`

### Replace with

- `customer path can degrade gracefully under threat`
- `evidence-oriented audit trail`
- `supports append-only archive patterns`

### Talking points

- The key idea is separation of powers: one component recommends, another scores risk, another gates action.
- Parallel agents are useful only if they are narrow in scope and auditable.
- The trace is not decorative telemetry. It is the control surface for debugging, incident response, and governance.
- Bitemporal matters because it answers two different questions:
  - what the system believed at decision time
  - what the database later came to contain

### Terms to understand

- `Bitemporal`: storing both business-valid time and system-recorded time.
- `Tamper-evident`: changes can be detected, even if not physically impossible.
- `Graceful degradation`: continue operation in a safer reduced mode instead of failing open.
- `MITRE ATT&CK`: attacker behavior framework for enterprise techniques.
- `MITRE ATLAS`: adversarial ML / AI attack framework.
- `PASTA`: attack simulation and threat analysis framework.
- `STRIDE`: threat categories: spoofing, tampering, repudiation, information disclosure, denial of service, elevation of privilege.
- `DREAD`: risk scoring dimensions for damage, reproducibility, exploitability, affected users, discoverability.

---

## Slide 4

### Current issue

This slide is outdated because the named known gap is no longer the most honest one.

Current problem:

- `KNOWN GAP: NQE context loss`

That is not the strongest current caveat.

### What to change

Keep the scorecard but update the caveat.

### Suggested rewrite

Title:

`Scorecard`

Subtitle:

`Strong architecture, with a few hardening gaps stated plainly.`

Table simplification:

- reduce labels to short nouns:
  - `Support`
  - `Integrations`
  - `Automation`
  - `Workflows`
  - `Data controls`
  - `Exceptions`
  - `Auditability`
  - `Tuning effort`
  - `Rollout`

Footer:

- `Current caveat: governance and payment hardening still in progress`
- `Most material blocker today: payment idempotency reliability`

### Talking points

- The purpose of the scorecard is not to prove perfection. It is to show tradeoffs.
- The platform's strength is control and auditability, not lowest tuning effort.
- The honest weakness is operational hardening and governance completeness, not architecture absence.

### Terms to understand

- `Idempotency`: repeated identical requests should not create repeated side effects.
- `Hardening`: taking a working system and making it reliable, safe, and resistant to misuse.

---

## Slide 5

### Current issue

Good slide, but `26+ Parallel Agents` is likely to trigger skepticism if you cannot show them clearly as bounded and meaningful.

### What to change

Reduce the “agent count” emphasis and increase the “control plane” emphasis.

### Suggested rewrite

Title:

`Build The Control Layer. Buy The Commodity.`

Body:

- `Commerce stack stays interchangeable`
- `ShopSquire sits as the intelligence + control layer`

Core blocks:

- `Orchestrator`
- `Policy gates`
- `Security observer`
- `Decision trace`
- `Fraud + CV + memory`

Bottom row:

- `Keep Stripe, shipping, ERP, SIEM, and CX tools replaceable`

### Replace

- `26+ Parallel Agents`

With one of:

- `Parallel specialist agents`
- `Multi-agent execution with bounded roles`
- `Specialized agents under one control plane`

### Talking points

- The moat is not owning payments, shipping, or ticketing.
- The moat is owning the governed intelligence layer that can sit above any stack.
- Vendor-agnostic means switching tools without rebuilding the reasoning and audit model.

### Terms to understand

- `Control plane`: the layer that governs policy, routing, identity, safety, and observability.
- `Commodity layer`: replaceable third-party tools that do not define your advantage.

---

## Slide 6

### Current issue

This is the slide most exposed to challenge.

Too strong:

- `Legally defensible bitemporal audit trail`
- `Data sovereignty — PII never leaves COLO`
- `12-week rollout delivered, not planned`

### What to change

Keep the ambition, but anchor it in what you can prove.

### Suggested rewrite

Title:

`Recommendation`

Subtitle:

`Custom is justified only when auditability, security, and controlled autonomy are first-class requirements.`

Why this path:

- `High automation with guardrails`
- `Security inside the workflow`
- `Replayable decision trace`
- `Local-first deployment options`
- `Vendor-agnostic integration model`

Today:

- `Working prototype / pilot-ready platform`
- `Strong audit + security architecture`
- `Substantial test coverage`

Tradeoffs:

- `Higher engineering ownership`
- `More hardening still required`
- `Best fit for teams that value control over speed`

Demo footer:

- `Live demo: recommendations, trace, security pipeline, email triage`

### Replace

- `PII never leaves COLO`

With:

- `PII can remain local with local model routing`
- or `supports local-first data handling`

### Talking points

- The recommendation is not "always build custom."
- It is: if you need governed AI actions, traceability, and security-native workflows, the custom layer becomes rational.
- The differentiator is not just intelligence. It is controllable intelligence.

### Terms to understand

- `Local-first`: prefer local processing paths when possible, especially for sensitive data.
- `Pilot-ready`: mature enough for controlled customer use, not the same as regulated-production-ready.

---

## Punchier Deck Version

Use these compressed slide subtitles:

- Slide 1: `Choose the path that can be governed, not just deployed.`
- Slide 2: `Deterministic first. Models only where they add value.`
- Slide 3: `Operate under attack. Keep every decision replayable.`
- Slide 4: `Strong architecture. A few hardening gaps.`
- Slide 5: `Own the control layer. Swap the commodity layer.`
- Slide 6: `Build custom only when control is the requirement.`

---

## Presentation Rules

### Say

- `bounded autonomy`
- `pilot-ready`
- `audit-oriented`
- `replayable decisions`
- `local-first option`
- `governed agent execution`

### Avoid

- `fully autonomous`
- `fully compliant`
- `production-ready across the board`
- `legally defensible` unless discussing design intent, not final legal status
- `PII never leaves` unless you are showing local-only routing

---

## Comprehensive Talking Points By Theme

### Why bitemporal trace matters

- Normal logs tell you what happened.
- Bitemporal trace tells you what the system believed when it acted.
- That distinction matters for refunds, fraud, escalations, and disputes.
- Without it, post-incident review becomes guesswork.

### Why multi-agent architecture matters

- Different jobs should not be collapsed into one opaque model call.
- Retrieval, fraud, CV, security review, and policy gating have different trust requirements.
- Specialized agents let you narrow permissions and make failures observable.

### Why guardrails matter

- Capability without control is the wrong product shape for commerce.
- A good system is not one that can do everything.
- It is one that can do the right set of things safely and explainably.

### Why custom can be justified

- You buy commodity infrastructure where it is truly commodity.
- You build where your risk model, traceability, and integration depth create advantage.

---

## What Is Left For Production-Grade Credibility

### P0 technical blockers

- Fix payment idempotency behavior in `src/app/routers/payments.py`
- Add a single global autonomy kill-switch authority
- Run and pass the full showcase UI path with Playwright enabled
- Reconcile the compliance/status docs with actual implementation

### P1 technical hardening

- Increase test coverage for provider-boundary redaction and residency on every outbound model/tool path
- Tighten structured configuration and reduce env-only governance toggles
- Prove WORM/archive behavior in deployment, not only in code support
- Remove or clearly isolate remaining stub/degrade paths in ERP, graph, analytics, and ranking

### P1 governance/evidence

- Complete DPIA
- Complete RoPA / processing register
- Complete AI governance inventory and review process
- Complete DPA/legal evidence for any external AI provider path
- Produce a current evidence pack that matches code reality

### P2 product credibility

- Re-run E2E showcase tests with the exact recording path
- Build a formal “recording-safe” demo mode checklist
- Ensure every slide claim has a code path, a test, or a live proof attached

---

## Hard Questions You Should Be Ready For

### "Is this production-ready?"

Answer:

`It is pilot-ready and architecture-mature, but I would not market it today as fully production-grade across all regulated workflows. The main remaining work is payment hardening, centralized autonomy controls, and evidence-pack completeness.`

### "Is the AI really autonomous?"

Answer:

`It is bounded autonomy, not open-ended autonomy. The point is controlled execution inside policy limits, with escalation and traceability when confidence or risk changes.`

### "Why not just use Zendesk / Ada / Salesforce?"

Answer:

`Those are good tools for workflow acceleration. They are weaker if you need deep traceability, security-native orchestration, and governed multi-agent action paths across commerce, fraud, CV, and email risk.`

### "Are you claiming compliance?"

Answer:

`No blanket claim. I am claiming a strong compliance-oriented architecture with meaningful controls already implemented, and a clear path to stronger production evidence.`

### "Why is bitemporal trace better than normal logs?"

Answer:

`Because normal logs do not preserve the difference between what the system knew at decision time and what the database later showed. In AI-driven workflows, that distinction is critical.`

---

## Best Single-Line Positioning

Use this if you need one sentence:

`ShopSquire is a bounded-agent commerce intelligence layer built for auditability, security, and replayable decision-making, not just faster chatbot answers.`
