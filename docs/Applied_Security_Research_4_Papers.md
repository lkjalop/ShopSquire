# 4 Publishable Applied Security Research Papers
### From Building an Agentic AI Security Platform with Coding Agents

> **Framing principle:** You didn't just *use* AI to write code — you discovered novel security patterns
> that only emerge when agents operate at swarm scale. That's applied research.
> The coding agents were the lab. The findings are yours.

---

## Paper 1: Self-Red-Teaming Agent Swarms

**Title:** *"Agents That Attack Themselves: Continuous Self-Red-Teaming as a Pre-Escalation Gate for XDR Pipelines"*

### The Novel Claim
Before an alert reaches a human analyst or XDR platform, the agent swarm that *detected* the threat
should adversarially challenge its own finding. If the swarm can't break its own conviction,
the alert is worth escalating. If it can, it was a false positive — killed silently, no analyst fatigue.

### Why This Is Original
| Current state of the art | What you're proposing |
|---|---|
| Red teaming is external, periodic, human-led | Red teaming is internal, continuous, agent-led |
| Alerts escalate on threshold alone | Alerts survive adversarial self-challenge before escalation |
| False positive reduction happens post-SIEM | False positive reduction happens pre-escalation |

### Research Structure
```
1. Problem:  SOC analysts drown in false positives (70-90% industry average)
2. Method:   Parallel agent swarm where Agent-A detects, Agent-B attacks
             the detection with counter-evidence, Agent-C adjudicates
3. Metric:   False positive rate before/after self-red-team gate
4. Finding:  [Your measured reduction — even on synthetic data]
5. Artefact: Open-source the self-red-team prompt chain + policy gate config
```

### Where to Publish
- **USENIX Security / IEEE S&P workshop** — novel defensive AI architecture
- **arXiv cs.CR** — preprint for visibility, no peer-review gate
- **OWASP community paper** — directly extends Agentic AI Top 10 (AG01: Prompt Injection)

### How Coding Agents Made This Possible
You couldn't have discovered this pattern writing code sequentially. The parallel agent swarm
architecture — where multiple agents independently triage the same event — naturally revealed
that agents *disagree*. That disagreement is signal. Formalising it into adversarial
self-challenge is the research contribution.

---

## Paper 2: Bi-Temporal Decision Trace as an AI Forensics Standard

**Title:** *"What the AI Knew When It Decided: Bi-Temporal Logging for Post-Incident AI Forensics and Regulatory Compliance"*

### The Novel Claim
AI systems make decisions based on data that changes after the fact. A bi-temporal decision trace
records two timelines: (1) **decision-time** — what the model saw, what features it weighted,
what policy it applied; (2) **correction-time** — what we later learned was true. The delta
between these two timelines is the forensic gold: it tells you whether the AI was *wrong*
or simply *operating on incomplete information*.

### Why This Is Original
| Current state of the art | What you're proposing |
|---|---|
| AI audit logs record inputs + outputs | Bi-temporal trace records knowledge state at decision time |
| Post-incident review asks "was the AI wrong?" | Bi-temporal review asks "was it wrong, or was the world incomplete?" |
| ISO 42001 requires explainability but doesn't define the schema | You propose a concrete schema that satisfies ISO 42001 A.6.2.6 |

### Research Structure
```
1. Problem:  Regulators (EU AI Act, ISO 42001) demand explainability
             but no standard defines what an AI decision record must contain
2. Method:   Bi-temporal schema — (entity_id, decision_time_facts,
             correction_time_facts, delta, policy_version, confidence)
3. Case:     Apply to 3 ShopSquire threat lanes (injection, BEC, supply chain)
4. Finding:  X% of "false positives" were actually correct decisions on
             incomplete data — the AI wasn't wrong, the ground truth arrived late
5. Artefact: Open-source schema + reference implementation
```

### Where to Publish
- **ACM FAccT (Fairness, Accountability, Transparency)** — directly on-topic
- **IEEE Intelligent Systems** — AI governance special issues
- **NIST AI RMF community profile** — contribute as a MANAGE function implementation guide

### How Coding Agents Made This Possible
Interleaved thinking (GLM 4.7 pattern) means the agent reasons *while* acting — its internal
reasoning chain is a natural decision trace. You didn't bolt on logging after the fact.
The trace is a first-class artefact of the architecture. That's the insight:
**interleaved thinking produces forensic evidence as a side effect.**

---

## Paper 3: Recursive Confidence Calibration Across Agent Swarms

**Title:** *"Recursive Learning in Security Agent Swarms: How Triage Consensus Calibrates Confidence and Reduces Alert Fatigue"*

### The Novel Claim
When N agents independently triage the same event, their agreement/disagreement distribution
is a calibration signal. Over time, the swarm learns which threat patterns produce high consensus
(high confidence — auto-act) vs low consensus (low confidence — escalate to human).
This is a recursive learning model: each triage round feeds back into the next round's
confidence thresholds. The result is a system that gets quieter over time
without getting less secure.

### Why This Is Original
| Current state of the art | What you're proposing |
|---|---|
| Confidence thresholds are set manually | Confidence thresholds emerge from swarm consensus history |
| Alert fatigue is addressed by tuning rules | Alert fatigue is addressed by recursive calibration |
| Single-model confidence is unreliable | Multi-agent consensus is a more robust confidence signal |

### Research Structure
```
1. Problem:  Single-agent confidence scores are poorly calibrated
             (high confidence ≠ high accuracy)
2. Method:   N parallel agents triage same event; consensus distribution
             feeds Bayesian update on per-threat-type confidence thresholds
3. Metric:   Calibration error (ECE) before/after recursive update
             + analyst escalation volume over time
4. Finding:  After K rounds, escalation volume drops by Y% while
             detection recall holds steady
5. Artefact: Calibration algorithm + threshold update policy (open-source)
```

### Where to Publish
- **AAAI / NeurIPS workshop on reliable ML** — calibration is a hot topic
- **Journal of Cybersecurity (Oxford)** — applied security + ML intersection
- **Blog post + GitHub repo** — fastest path to visibility if formal peer review feels heavy

### How Coding Agents Made This Possible
The recursive learning model mirrors how you used coding agents: each iteration of the codebase
was informed by the previous run's failures. You applied the same pattern to security triage.
**The agents don't just detect threats — they learn what they're bad at detecting
and adjust.** That feedback loop is the research contribution.

---

## Paper 4: Brand Trust as a Measurable Security Outcome

**Title:** *"From SOC Metrics to Brand Metrics: Measuring How Transparent AI Security Increases Customer Trust"*

### The Novel Claim
Security teams measure MTTD, MTTR, false positive rate. Business teams measure NPS, churn,
brand sentiment. Nobody connects the two. This paper proposes a **trust attribution model**:
when your AI security platform visibly explains *why* it flagged a transaction, quarantined
an email, or blocked a vendor — and that explanation is auditable — customers trust the
platform more. Transparent security is a revenue driver, not a cost centre.

### Why This Is Original
| Current state of the art | What you're proposing |
|---|---|
| Security ROI = "incidents prevented" (negative metric) | Security ROI = "trust earned" (positive metric) |
| Security is invisible to end users | Security explanations are surfaced to end users |
| Compliance is a checkbox for auditors | Compliance artefacts (decision trace) become a trust signal |

### Research Structure
```
1. Problem:  Security teams can't justify budget because their value
             is measured in things that didn't happen
2. Method:   Expose bi-temporal decision trace to end users as
             "here's why we protected you" notifications
             Measure: trust survey, support ticket volume, churn delta
3. Case:     ShopSquire — retail platform where merchants see
             security decisions in real-time
4. Finding:  Merchants who see security explanations report X% higher
             trust scores and Y% lower churn
5. Artefact: Trust attribution framework + survey instrument (open-source)
```

### Where to Publish
- **Harvard Business Review / MIT Sloan Management Review** — business audience, high visibility
- **RSA Conference / Black Hat business track** — security + business intersection
- **LinkedIn long-form series** — 4-part series, one per week, builds narrative arc

### How Coding Agents Made This Possible
Building with autonomous agents forced you to make every decision explainable — because *you*
needed to understand what the agents did. That explainability infrastructure, built for
developer debugging, turns out to be exactly what customers want to see.
**Debugging transparency became brand transparency.** That's the insight.

---

## Publication Roadmap

```
MONTH 1          MONTH 2          MONTH 3          MONTH 4
─────────────────────────────────────────────────────────────
Paper 1:         Paper 2:         Paper 3:         Paper 4:
Self-Red-Team    Bi-Temporal      Recursive        Brand Trust
                 Forensics        Calibration

  Write +          Write +          Write +          Write +
  arXiv preprint   submit to        GitHub repo +    LinkedIn series
  + blog post      ACM FAccT        blog post        + HBR pitch

  ──── Each paper gets: GitHub repo + demo video + LinkedIn post ────
```

### "But I Used Coding Agents to Build It"

**That's the point.** Applied research doesn't require inventing the tools — it requires
discovering novel patterns *while using* the tools. Newton didn't invent the apple.

Your contributions are:
1. **Self-red-teaming as a pre-escalation gate** (architectural pattern)
2. **Bi-temporal trace as an AI forensics schema** (data model)
3. **Swarm consensus as a calibration signal** (algorithm)
4. **Security transparency as a trust metric** (measurement framework)

None of these existed before you built ShopSquire. The coding agents were the means.
The research is yours.

---

*Ship one per month. Four papers in four months. That's a portfolio, not a project.*
