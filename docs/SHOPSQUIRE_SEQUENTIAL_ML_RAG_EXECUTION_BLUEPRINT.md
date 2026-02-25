# ShopSquire Sequential Upgrade Blueprint (ML + Agentic RAG + Orchestration)

Generated: 2026-02-24

## Status Snapshot
- Completed in this pass:
  1. Replace static playbook selection with learned playbook ranking (feature-flagged fallback).
- Code touched:
  - `src/app/services/playbook_engine.py`
  - `src/app/services/security_playbooks.py`
- Feature flags:
  - `PLAYBOOK_LEARNED_RANKING_ENABLED`
  - `PLAYBOOK_SIGNAL_LEARNED_RANKING_ENABLED`

---

## Execution Rules (applies to every step)
1. Keep deterministic fallback path enabled.
2. New ML paths must be feature-flagged and shadow-runnable.
3. Every step must emit decision-trace evidence fields.
4. Every rollout must ship with offline benchmark + online guardrails.

---

## Phase 1: Orchestration Intelligence (Immediate)

### 1. Replace static playbook selection with learned playbook ranking
- Status: Done (v1).
- Why: Better playbook choice quality over time.
- Next hardening:
  1. Add offline replay benchmark for ranking uplift.
  2. Add calibration by incident domain (email/cv/payment).

### 2. Add multi-agent debate only for high-risk/high-value cases
- Why: Improve decision quality where mistakes are expensive.
- Implement:
  1. Create `DebateCoordinator` (`proposer`, `challenger`, `judge`) in `src/app/services/`.
  2. Trigger only when `risk_band in {high, critical}` OR `transaction_value >= threshold`.
  3. Enforce token/time budgets and max rounds.
  4. Persist debate transcript summary to decision trace.
- KPI:
  - Reduced false approvals in high-risk lane.

### 3. Introduce uncertainty-aware orchestration
- Why: Budget tools based on confidence/uncertainty.
- Implement:
  1. Add `uncertainty` field to agent outputs.
  2. Dynamically increase tool budget and human escalation probability for high uncertainty.
  3. Emit `uncertainty_policy_applied` trace event.
- KPI:
  - Better precision at equal recall; fewer unnecessary expensive calls.

### 4. Add temporal campaign detection (time-series bursts)
- Why: Detect coordinated attacks and drift spikes.
- Implement:
  1. Build sliding-window burst features from security events.
  2. Add anomaly detectors per tenant/channel.
  3. Route campaign-level incidents to SOC path.
- KPI:
  - Mean time to campaign detection.

### 5. Add graph correlation across email/CV/payments/supply-chain
- Why: Link weak single signals into strong multi-hop evidence.
- Implement:
  1. Build entity graph: sender, domain, account, device, SKU, supplier, IOC.
  2. Add graph risk score and neighborhood features.
  3. Expose graph evidence in admin drilldown.
- KPI:
  - Improved detection on multi-stage attacks.

### 6. Add causal attribution fields in decision trace
- Why: Explainability + auditability.
- Implement:
  1. Add `top_features` and `counterfactual` fields to model outputs.
  2. Log per-decision attribution bundle.
- KPI:
  - Reviewer acceptance rate, reduced override confusion.

### 7. Add policy simulation sandbox before publish
- Why: Prevent bad policy/model rollouts.
- Implement:
  1. Add dry-run simulator against historical traces.
  2. Show impact deltas (allow/review/block rates).
  3. Block publish if guardrails violated.
- KPI:
  - Zero high-severity regressions from policy changes.

### 8. Add automatic threshold tuning
- Why: Keep precision/recall targets without manual retuning.
- Implement:
  1. Periodic optimizer over labeled outcomes.
  2. Per-tenant threshold sets with rollback.
- KPI:
  - Stable precision/recall over time.

### 9. Add per-capability SLAs
- Why: Operational control.
- Implement:
  1. Track latency, precision, escalation rate per capability.
  2. Alert on SLA breaches.
- KPI:
  - SLA compliance by lane.

### 10. Add safe failure modes when models unavailable
- Why: Resilience.
- Implement:
  1. Fail closed for dangerous actions.
  2. Degrade to deterministic policy with audit tag `model_unavailable_fallback`.
- KPI:
  - No unsafe auto-approvals during model outages.

---

## Phase 2: Move from Regex-First to ML-First Decisioning

### 11. Keep regex as candidate generation only
- Why: Maintain recall and speed.
- Implement:
  1. Regex emits candidates/signals only.
  2. Final action decided by ML scorer + policy gate.

### 12. Add ML scorer as final decision layer
- Why: Improve precision and robustness.

### 13. Introduce calibrated confidence thresholds (allow/review/block)
- Why: Stable decision boundaries.

### 14. Train on decision traces + incident outcomes
- Why: Domain-specific model quality.

### 15. Add hard-negative mining
- Why: Reduce false positives from regex hits.

### 16. Build per-tenant calibration
- Why: Different tenants have different normal behavior.

### 17. Use feature store for offline/online parity
- Why: Reproducible training and serving.

### 18. Add drift detection on features + outputs
- Why: Catch model decay and data shifts.

### 19. Route low-confidence outputs to human review
- Why: Safe uncertainty handling.

### 20. Add active learning loop from reviewer corrections
- Why: Continuous quality improvement.

### 21. Version policies/models/prompts with rollback
- Why: Controlled change management.

### 22. Gate rollout with offline benchmark + shadow mode
- Why: Lower production risk.

### 23. Run continuous red-team mutation campaigns
- Why: Adversarial robustness.

### 24. Add cost-aware routing
- Why: Use cheap model first, escalate when uncertain.

### 25. Add post-incident learning jobs
- Why: Encode new attack patterns rapidly.

---

## Phase 3: Detection Model Portfolio

### 26. Prompt-injection classifier (text + OCR)
- Inputs: prompt text, OCR text, context metadata.
- Output: injection probability + rationale.

### 27. Tool-abuse intent classifier
- Inputs: requested tool, args, user intent text.
- Output: abuse risk + blocked intent class.

### 28. BEC/phishing model (sender/header/body/thread)
- Inputs: auth results, thread continuity, linguistic cues, trust graph.
- Output: BEC probability + action recommendation.

### 29. URL/domain risk model
- Inputs: lexical, redirect chain, TLS, WHOIS/age, reputation.
- Output: URL/domain maliciousness score.

### 30. Attachment malware risk model
- Inputs: metadata, MIME/ext, OCR, static triage, sandbox summary.
- Output: malware risk score.

### 31. Supplier anomaly model
- Inputs: vendor behavior baseline over channel/time.
- Output: anomaly score and deviation factors.

### 32. OAuth scope anomaly model
- Inputs: baseline scopes, newly granted scopes, scope semantics.
- Output: privilege anomaly probability.

### 33. SBOM/package risk scoring model
- Inputs: CVE severity, exploitability, KEV, reachability.
- Output: actionable supply-chain risk.

### 34. Risk fusion model (stacking/GBM)
- Inputs: all model scores + deterministic signals.
- Output: unified risk and route.

### 35. Graph ML for trust relationships
- Inputs: entity graph + interaction histories.
- Output: coordinated fraud/campaign likelihood.

---

## Phase 4: Agentic RAG Maturity

### 36. Hybrid retrieval (BM25 + dense + graph)
### 37. Cross-encoder reranking
### 38. Query decomposition + planner
### 39. Evidence-grounded context builder with budgets
### 40. Source trust scoring + tenant-aware filtering
### 41. Citation enforcement with confidence bands
### 42. Retrieval guardrails vs indirect injection
### 43. Memory lifecycle policies (freshness/TTL/revocation)
### 44. Self-check/reflection before action
### 45. Tool-augmented RAG with policy-gated execution

For items 36-45, enforce two hard constraints:
1. Never execute tools from retrieved content without policy gate.
2. Always attach citations and confidence to generated recommendations.

---

## Suggested Build Order (90-Day)
1. Week 1-2: Steps 2, 3, 10.
2. Week 3-4: Steps 11-13, 19.
3. Week 5-6: Steps 26, 27, 34.
4. Week 7-8: Steps 28, 29, 30.
5. Week 9-10: Steps 36, 37, 39, 41.
6. Week 11-12: Steps 4, 5, 35, 42.

---

## Success Metrics (Global)
1. Precision increase on high-risk lane.
2. False positive reduction in email/CV/security queues.
3. Escalation quality uplift (fewer noisy escalations).
4. Mean-time-to-detect for campaign attacks.
5. SLA compliance by capability.
6. Rollback incidents from model/policy changes.

---

## Immediate Next Sequential Build (Step 2)
Implement multi-agent debate for high-risk/high-value decisions with:
1. Feature flag.
2. One debate round (proposer/challenger/judge).
3. Trace fields: `debate_enabled`, `debate_outcome`, `debate_confidence_delta`.
4. Fallback to current deterministic path when disabled or model unavailable.
