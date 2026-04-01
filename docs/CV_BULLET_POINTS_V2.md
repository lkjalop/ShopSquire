# CV / Resume Bullet Points — v2 (March 2026)

> Two projects covered: **JanuSec** (threat detection / XDR platform) and **ShopSquire** (agentic AI / e-commerce security).
> 5 bullets per role. Mix and match across projects for the best fit.
> CyberCX Academy consulting/strategy version at the bottom.

---

---

# PART 1 — JANUSEC

> JanuSec is a production-grade AI-assisted threat detection platform: multi-tenant, cloud-deployed, real-time event pipeline with LLM triage, MITRE ATT&CK correlation, HopGraph attack visualisation, hunt lanes, and full chain-of-custody forensics across network, endpoint, email, IAM, supply chain, and cloud domains.

---

## JanuSec — Role 1: Detection Engineer / Threat Intelligence Engineer

1. **MITRE ATT&CK Correlation Engine** — Built a multi-domain correlation rules engine spanning network, endpoint, email, IAM, cloud, and supply chain, mapping detections to MITRE ATT&CK techniques and MITRE STRIDE threat categories — authoring enriched rules including BEC payment-change detection, DKIM-flip anomaly correlation, and lateral movement chaining that fire contextual threat scores rather than binary alerts.

2. **LLM-Assisted Triage (T1/T2 Automation)** — Engineered a two-tier AI triage pipeline where Tier 1 LLM summaries auto-classify incoming events by severity and technique, and Tier 2 deep-analysis sessions reconstruct multi-hop attack paths with confidence scoring and human-readable context — compressing analyst triage time from hours to seconds for high-signal alerts.

3. **HopGraph Attack Path Reconstruction** — Designed and implemented HopGraph Lite: a graph-based attack visualisation engine that stitches together related events across time and assets into a connected attack narrative — enabling analysts to trace lateral movement, persistence, and exfiltration paths that span disparate log sources and would be invisible in flat alert queues.

4. **Hunt Lane Automation** — Built a lane-based threat hunting framework (JA3 novelty detection, process lineage anomaly, auth burst analysis) with evidence envelopes that package correlated signals into structured hunt artefacts, fusing heuristics from network, endpoint, and identity layers for cross-domain attack pattern recognition.

5. **Feedback-Driven Detection Tuning** — Implemented a closed-loop analyst feedback system where triage decisions (TP/FP/benign) are captured, stored in a feedback repository, and used to recalibrate factor weights and TFIDF classifiers — creating a self-improving detection engine that reduces false-positive rates as it accumulates operational data.

---

## JanuSec — Role 2: Security Platform Engineer

1. **26-Stage Event Ingestion Pipeline** — Architected and implemented a multi-stage real-time event processing pipeline covering normalisation, enrichment, embedding generation, allowlist gating, circuit-breaking, risk scoring, correlation, hunt-lane dispatch, and LLM triage — processing events from Zeek, Suricata, Wazuh, XDR connectors, and cloud APIs through a unified schema.

2. **Connector Ecosystem & Adapter Framework** — Built a pluggable adapter layer ingesting telemetry from Zeek (network), Wazuh (endpoint/SIEM), Eclipse XDR, KAPE forensic artefacts, and cloud CSPM APIs — normalising heterogeneous log formats into a canonical event schema with source-specific enrichment and risk-factor attribution.

3. **Chain-of-Custody Forensic Artefact Store** — Designed an artefact management system with cryptographic chain-of-custody tracking, bitemporal decision logging (valid-time + system-time), and a custody transfer API — ensuring forensic evidence is tamper-evident, court-admissible in posture, and fully reproducible for regulatory audit requests.

4. **Resilient Event Delivery with DLQ** — Implemented a durable dead-letter queue architecture for event pipeline failures, with automated retry logic, batch replay capabilities, and outbox-pattern persistence — ensuring no alert is lost under partial infrastructure failure and that event ordering is preserved for time-sensitive correlation windows.

5. **Multi-Tenant Isolation & Tenant Config Management** — Built multi-tenancy into the platform core with per-tenant configuration overrides, isolated data paths, tenant-scoped metrics, and role-based API access — enabling the platform to serve multiple customer environments from a shared infrastructure without cross-tenant data leakage.

---

## JanuSec — Role 3: AI Security Engineer (LLM / AI Operations)

1. **LLM Triage Orchestration with Deterministic Fallback** — Built a production LLM orchestration layer supporting multiple provider backends (OpenAI, Anthropic, Ollama local inference) with deterministic fallback chains, pre-warm probes, cost tracking per inference, and structured JSON output schemas — ensuring triage quality degrades gracefully rather than failing silently when upstream AI services are unavailable.

2. **Semantic Embedding & Vector Search** — Integrated pgvector-backed semantic similarity search into the detection pipeline, enabling factor embeddings for near-duplicate alert clustering, cross-event correlation by semantic proximity, and threat-intel enrichment lookup by embedding distance — reducing alert volume through intelligent deduplication before LLM triage is invoked.

3. **AI FinOps & Cost Governance** — Implemented a FinOps cost ledger tracking per-tenant, per-operation LLM token consumption and API costs, with real-time cost dashboards and budget guardrails — providing the operational visibility needed to run AI triage at scale without uncontrolled spend creep.

4. **TFIDF Classifier with CI Shadow Testing** — Built and operationalised a TFIDF-based signal classifier with a CI-gated shadow-run pipeline that validates classifier drift against ground-truth baselines before promoting updates — preventing silent regression in the AI triage layer when training data or model configurations change.

5. **Graph-Augmented LLM Context (HopGraph + LLM Fusion)** — Designed the integration between HopGraph's attack path snapshots and the LLM triage layer, injecting graph-derived attack context (lateral movement paths, node relationships, prior-hop evidence) directly into LLM prompts — producing analyst-grade narrative summaries that explain *how* an attack unfolded, not just *that* it happened.

---

## JanuSec — Role 4: Security Architect

1. **Defence-in-Depth Platform Architecture** — Designed JanuSec's layered security architecture: real-time ingestion with circuit-breaking, correlation with MITRE ATT&CK/STRIDE mapping, hunt-lane dispatch, LLM triage with confidence scoring, graph-based attack reconstruction, and chain-of-custody forensic storage — each layer providing an independent detection opportunity and a fail-safe for the layers below.

2. **Webhook Guard Middleware** — Designed and implemented a webhook verification middleware layer that validates HMAC signatures, enforces rate limits, and provides per-source authentication — hardening the platform's event ingestion surface against spoofed telemetry injection, replay attacks, and upstream connector compromise.

3. **Email Threat Detection Architecture (BEC/DKIM)** — Architected multi-signal email threat correlation rules detecting Business Email Compromise, DKIM alignment flips (domain impersonation), and supplier portal free-reply anomalies — treating email telemetry as a first-class detection domain rather than a secondary signal, integrated directly into the cross-domain correlation engine.

4. **Cloud Security Posture Management (CSPM) Integration** — Built CSPM ingestion and posture analysis into the platform, correlating cloud misconfiguration signals with endpoint and network telemetry — providing a unified risk view that connects cloud exposure (open buckets, excessive IAM permissions) with active threat activity.

5. **Threat Model as Operational Architecture** — Embedded STRIDE, MITRE ATT&CK, and CVSS risk scoring as runtime data — every event carries technique tags, severity weights, and MITRE tactic attribution — so that the platform's detection logic *is* the threat model, not a separate document that drifts out of sync with implementation.

---

## JanuSec — Role 5: Platform / Cloud Infrastructure Engineer

1. **Containerised Multi-Environment Deployment** — Designed Docker Compose-based deployment with environment-specific profiles (dev, staging, Azure, GCP) and Dockerfile variants (API, worker, collector, fast-inference) — with Azure and GCP override files enabling cloud-native deployment without application code changes, ready for Kubernetes/Helm promotion.

2. **Observability Stack (Prometheus / Grafana / Structured Logging)** — Built full-stack observability with Prometheus metric collection, custom Grafana dashboards (hunt lane throughput, LLM cost ledger, alert pipeline latency, per-tenant SLOs), structured JSON event logging, and SSE streaming for real-time UI telemetry — following production SRE practices from day one.

3. **Database Architecture with pgvector and Bitemporal Tables** — Designed a PostgreSQL schema with pgvector for embedding-based similarity search, Alembic-managed migrations with pre/post hooks, bitemporal decision tables (valid-time + system-time), and factor weight repositories — portable across managed cloud databases (RDS, Azure Database for PostgreSQL, Cloud SQL) without application changes.

4. **CI/CD Pipeline Ecosystem** — Built and maintained a comprehensive GitHub Actions CI ecosystem: unit tests, integration tests, LLM mock tests, Playwright E2E, coverage matrix, Bandit security scanning, Trivy container scanning, TFIDF seed/validation, Prometheus rule validation, and migration tests — providing multi-layer quality gating for a security product where a regression is a security gap.

5. **Infrastructure-as-Code & Terraform** — Designed Terraform modules for cloud infrastructure (DLQ, variable management, cloud-specific overrides) and Helm charts for Kubernetes deployment — treating infrastructure as version-controlled, reviewable code with the same rigour applied to application logic.

---

## JanuSec — Role 6: SOC Analyst / Threat Hunting (Consulting Positioning)

1. **Multi-Domain Threat Coverage Design** — Designed detection coverage across 8 domains — network, endpoint, email, identity/IAM, supply chain, cloud, SBOM/vulnerability, and lateral movement — mapping each to MITRE ATT&CK techniques and defining detection gaps as structured backlog items, applying the same coverage-gap methodology used in enterprise SOC gap assessments.

2. **Structured Threat Hunting with Hunt Lanes** — Built a structured hunt framework with lanes for JA3 TLS fingerprint novelty, process lineage anomaly, authentication burst detection, and domain baseline deviation — each lane producing evidence envelopes that package correlated signals for analyst review with clear escalation criteria.

3. **SBOM-Driven Vulnerability Correlation** — Integrated SBOM ingestion and CVE/CVSS enrichment into the detection pipeline, correlating known-vulnerable software components with active network and endpoint telemetry — enabling proactive threat hunting that starts from software exposure rather than waiting for observable exploitation.

4. **Analyst-Facing Triage Interface Design** — Designed the analyst workflow from alert queue through LLM-assisted triage summary, HopGraph attack visualisation, and feedback capture — with a focus on reducing cognitive load, surfacing the highest-confidence signals first, and enabling one-click contextual pivoting between evidence layers.

5. **Decision Audit Trail for Regulatory Compliance** — Implemented a bitemporal chain-of-custody model where every triage decision, analyst override, and automated suppression is timestamped against both the event's occurrence time and the system's processing time — enabling full forensic reconstruction of "what was known, when, and why the decision was made" for compliance and incident reporting.

---

---

# PART 2 — SHOPSQUIRE (Updated March 2026)

> ShopSquire is a production-grade agentic AI platform for e-commerce security: parallel agent swarms, multimodal CV+NLP forensics, OWASP LLM/Agentic/API Top 10 compliance, MITRE ATLAS threat mapping, and bitemporal audit trails. All bullets updated for clarity and competitive differentiation.

---

## ShopSquire — Role 1: Agentic AI Engineer

1. **Multimodal Forensics Pipeline** — Engineered a production CV + NLP forensics pipeline combining YOLOv8 object detection, LLaVA visual reasoning, dual-OCR cross-validation, and EXIF metadata integrity analysis — automating return-fraud detection, QR prompt-injection scanning, and image-manipulation forensics across untrusted e-commerce complaint media.

2. **Email Security & Anti-BEC Controls** — Built an email threat subsystem enforcing DMARC/SPF/DKIM alignment, Unicode homoglyph detection (Cyrillic/Latin impersonation), and outbound C2-pattern monitoring using entropy, rate, and periodicity scoring — preventing Business Email Compromise and AI-generated phishing in automated supplier communications.

3. **OWASP + MITRE Real-Time Security Observer** — Implemented a continuous Security Observer mapping every agent action to OWASP LLM Top 10, OWASP Agentic Top 10, OWASP API Top 10, MITRE ATT&CK, and MITRE ATLAS — computing composite DREAD/CVSS risk scores in real time to drive Transaction Firewall enforcement and human-in-the-loop escalation.

4. **Parallel Agent Swarm + CacheRAG Orchestration** — Designed a propose-only parallel agent swarm (NLP, CV, Security, Inventory lanes) with a 5-stage pipeline (Validate → Retrieve → Reason → Policy → Execute), shadow Security Observer sidecars, and a 3-tier CacheRAG (Session/KV/Recent) that prevents context-poisoning attacks while eliminating unbounded prompt growth.

5. **Bitemporal Decision Trace for AI Accountability** — Architected a dual-timeline (valid-time + system-time) decision log providing regulatory-grade reproducibility — enabling exact reconstruction of what the AI knew and what evidence it held at each decision point — the foundational audit primitive for ISO 42001, EU AI Act, and SOC 2 Type II compliance.

---

## ShopSquire — Role 2: AI Security Engineer

1. **Adversarial Multimodal Defence** — Built multi-layer CV forensics (YOLOv8 + OCR + EXIF) detecting image-based prompt injection, QR-code payload attacks, and adversarial perturbations targeting agent decision loops — hardening the highest-risk attack surface: untrusted media entering an autonomous system.

2. **Email Threat Intelligence Layer** — Engineered anti-BEC controls including DMARC/SPF/DKIM enforcement, Unicode homoglyph scanning, and outbound agent-communication monitoring that detects C2-like patterns by analysing entropy, rate anomalies, and periodicity — treating the AI's own generated emails as a potential attack vector.

3. **OWASP Agentic + MITRE ATLAS Compliance Framework** — Implemented the OWASP Agentic Top 10 (the framework barely existed at build time) as executable policy gates via a Transaction Firewall and Security Observer — mapping every tool call, retrieval action, and agent proposal to attack techniques and risk scores before execution, not after.

4. **Zero-Trust Agent Isolation** — Designed a propose-only swarm where no agent executes directly — all proposals pass a Transaction Firewall, a shadow Security Observer runs as a sidecar, and CacheRAG isolates retrieval tiers to prevent cross-conversation context poisoning and data exfiltration via prompt manipulation.

5. **Non-Repudiation Audit for Agentic AI** — Implemented dual-timeline decision traces capturing exact evidence, model version, confidence score, and risk assessment at each autonomous decision — enabling forensic incident reconstruction and providing the non-repudiation guarantees that agentic platforms require when AI decisions carry financial consequences.

---

## ShopSquire — Role 3: AI Architect

1. **Multimodal Intelligence Architecture** — Architected a tiered CV + NLP pipeline (YOLOv8, LLaVA, XGBoost intent classification, corrective RAG with query expansion) processing untrusted images, text, and emails through a unified forensics layer — solving the core architectural tension: multimodal agents need CV and NLP context simultaneously without accumulating unbounded context.

2. **Security-as-Architecture** — Embedded OWASP LLM/Agentic/API Top 10, MITRE ATLAS, and STRIDE as first-class architectural concerns — every agent decision is tagged with risk vectors and CVSS scores at creation time, so the Transaction Firewall enforces policy before execution rather than detecting violations after the fact.

3. **Email as High-Risk Agent Surface** — Designed the email security layer as a first-class architectural component, not a bolt-on — treating inbound supplier communications and outbound agent-generated emails symmetrically as attack vectors with layered defences integrated directly into the orchestration loop.

4. **Swarm Orchestration with Selective Evidence Refresh** — Designed a parallel propose-only agent architecture with interleaved chain-of-thought planning and a 3-tier CacheRAG that provides selective evidence refresh rather than accumulating full context — the architecture decision that makes the difference between an agent that hallucinates at scale and one that reasons reliably.

5. **Bitemporal Platform Foundation** — Architected dual-timeline decision tracing as the platform's core data primitive — not just for compliance, but because any autonomous AI system making financial decisions *must* answer "what did the system believe, and when" — a requirement that event sourcing alone cannot satisfy.

---

## ShopSquire — Role 4: Security Architect

1. **Defence-in-Depth for Untrusted Media Ingestion** — Layered YOLOv8 detection, dual-OCR cross-validation, EXIF integrity checks, and QR payload scanning to neutralise image-based prompt injection, adversarial perturbations, and steganographic attack vectors before they reach agent reasoning loops.

2. **Zero-Trust Email Architecture** — Architected an email security layer enforcing DMARC/SPF/DKIM alignment, Unicode homoglyph impersonation detection, and C2 behavioural monitoring on agent-generated outbound communications — the only architecture that treats the AI's output as an attack surface, not just its inputs.

3. **Continuous Multi-Framework Threat Correlation** — Built a Security Observer correlating all agent actions against OWASP LLM Top 10, OWASP Agentic Top 10, OWASP API Top 10, MITRE ATT&CK, MITRE ATLAS, and STRIDE in real time — computing composite DREAD + CVSS scores feeding a Transaction Firewall with automated escalation above risk thresholds.

4. **Secure-by-Design Agent Isolation** — Designed propose-only agent architecture with policy gates, shadow Security Observer sidecars, and CacheRAG memory isolation — preventing cross-conversation context poisoning, tool-call injection, and data exfiltration via prompt manipulation.

5. **Regulatory Non-Repudiation for AI Decisions** — Implemented dual-timeline audit (valid-time + system-time) providing cryptographic-grade non-repudiation for every autonomous decision — enabling forensic reconstruction and evidence for ISO 42001, EU AI Act, and SOC 2 Type II audits.

---

---

# PART 3 — CYBERCX ACADEMY: CONSULTING & STRATEGY TRACK

> Tailored for the CyberCX Academy — Consulting pathway (Strategy & Consulting, GRC, Cyber Intelligence).
> These bullets reframe both JanuSec and ShopSquire through a consulting, risk-advisory, and client-communication lens.
> Application closes **15 April 2026 at 5:00pm AEST**.

---

## CyberCX Academy — Consulting / Strategy Track (5 Core Bullets)

1. **Threat Detection Strategy Across 8 Security Domains** — Designed and implemented end-to-end detection coverage strategy for JanuSec spanning network, endpoint, email, identity, supply chain, cloud, SBOM/vulnerability, and lateral movement — applying structured gap analysis to prioritise detection investment by risk impact, a methodology directly transferable to client security posture assessments and roadmap engagements.

2. **AI Governance & Compliance Advisory Practice** — Implemented ISO 42001 (AI Management Systems), EU AI Act, and OWASP Agentic Top 10 compliance controls as operational requirements across two production AI platforms — developing the hands-on understanding of AI governance frameworks that organisations now urgently need as advisors, not just technicians.

3. **Communicating Risk to Non-Technical Stakeholders** — Built analyst-facing triage interfaces and executive-grade reporting (LLM-generated narrative summaries, HopGraph attack visualisations, SOC dashboards) for a platform whose outputs are consumed by both technical analysts and business decision-makers — developing the skill of translating complex threat data into actionable business language.

4. **Structured Security Risk Assessment & Scoring** — Designed multi-factor risk scoring frameworks (DREAD + CVSS, MITRE ATT&CK technique weighting, factor confidence scoring with feedback loops) and applied them across real threat data — providing hands-on experience with the quantitative risk assessment methodology that underpins GRC, threat modelling, and security strategy engagements.

5. **Security Architecture Advisory from First Principles** — Architected two production security systems (a threat detection platform and an AI agent security layer) from threat model through implementation, making real design tradeoffs between detection coverage, operational cost, analyst workflow, and regulatory compliance — the same reasoning process a strategy consultant applies when advising clients on security investments.

---

## CyberCX Academy — Supporting Bullets (Mix and Match)

**GRC / Compliance Focus:**
- Implemented OWASP Top 10 (LLM, Agentic, API), MITRE ATT&CK, STRIDE, and ISO 42001 as executable compliance controls — not documentation — across two production platforms, developing a practical understanding of how major security and AI governance frameworks translate into real operational requirements and control gaps.
- Designed chain-of-custody forensic artefact stores with bitemporal audit trails (valid-time + system-time) satisfying regulatory requirements for evidence preservation, non-repudiation, and audit reproducibility — practical experience with the compliance evidence layer that GRC engagements ultimately produce.

**Cyber Intelligence Focus:**
- Built a threat intelligence layer integrating MITRE ATT&CK technique attribution, CVSS vulnerability scoring, and feedback-driven confidence calibration into a production detection platform — developing hands-on experience with how threat intelligence is operationalised, not just consumed from feeds.
- Engineered detection rules for Business Email Compromise, DKIM domain impersonation, supply chain anomalies, and lateral movement chains — translating threat intelligence (who does what, how) into detection logic (what signals to look for, at what confidence threshold).

**Strategy & Advisory Positioning:**
- Designed JanuSec's detection roadmap by applying structured gap analysis across 8 security domains, prioritising coverage by attack frequency, business impact, and implementation cost — the same structured prioritisation methodology used in enterprise security strategy and advisory engagements.
- Built multi-tenant architecture enabling a single security platform to serve multiple client environments with isolated data paths, per-tenant configuration, and customised detection profiles — directly relevant to understanding how managed security service providers structure client delivery.

---

## CyberCX Academy — Cover Letter Talking Points

**Why Consulting Track:**
> "I've spent two years building security systems from the inside — detection engines, threat models, compliance frameworks — but what I want to do next is bring that technical depth to client advisory work. The most valuable thing a consultant can offer isn't frameworks from a textbook; it's having actually built and broken the systems those frameworks are meant to govern. I want to bring that to CyberCX clients."

**Why CyberCX Specifically:**
> "CyberCX works across the full spectrum of cyber risk — strategy through incident response — and across industries where the stakes are real. The Academy's consulting track puts me in front of that range of problems early, with the support structure to develop client skills alongside technical depth. That combination is exactly what I'm looking for."

**On No Prior Consulting Experience:**
> "I don't have consulting experience in a traditional sense, but I've done what consultants do: I've assessed security posture from scratch, identified gaps against frameworks, made architectural recommendations, and built the controls to close them. The difference is I've done it on my own platform. I'm bringing that same rigour to client engagements."

---

## Quick Reference: Which Version for Which Role

| Target Role | Primary Version | Supplement With |
|---|---|---|
| Agentic AI Engineer | ShopSquire Role 1 | JanuSec Role 3 (AI Ops) |
| AI Security Engineer | ShopSquire Role 2 | JanuSec Role 4 (Sec Arch) |
| Detection Engineer | JanuSec Role 1 | JanuSec Role 2 (Platform) |
| Threat Intelligence Engineer | JanuSec Role 1 | JanuSec Role 6 (SOC/Hunt) |
| Security Platform Engineer | JanuSec Role 2 | JanuSec Role 5 (Cloud Infra) |
| Security Architect | JanuSec Role 4 | ShopSquire Role 4 |
| AI Architect | ShopSquire Role 3 | JanuSec Role 3 |
| SOC Analyst / Threat Hunting | JanuSec Role 6 | JanuSec Role 1 |
| Cloud Security Engineer | JanuSec Role 5 | JanuSec Role 4 |
| GRC / AI Governance | ShopSquire Role 4 | CyberCX GRC bullets |
| CyberCX Academy — Consulting | CyberCX 5 Core Bullets | CyberCX Supporting bullets |
| CyberCX Academy — Technical | JanuSec Role 2 + Role 4 | CyberCX Technical bullets |

---

## Why These Bullets Win

### JanuSec-Specific Advantages
- **Detection engineering at depth** — you didn't configure a SIEM; you built the correlation engine, the rules, the scoring, and the feedback loop. That's a layer most candidates have never touched.
- **LLM + security intersection** — running AI-assisted triage in production, with cost governance, fallback chains, and CI validation. The market has almost nobody with this combination.
- **HopGraph = rare capability** — attack path reconstruction via graph analysis is a senior-level skill set that most security engineers describe in theory; you implemented it.

### Why CyberCX Consulting Track Fits
- The Academy explicitly welcomes career changers and non-traditional backgrounds.
- The consulting pathway covers strategy, GRC, and cyber intelligence — all areas where your framework knowledge (MITRE, OWASP, ISO 42001, CVSS) translates directly.
- Your ability to explain complex technical decisions in plain language — demonstrated by the LLM-generated analyst summaries and executive dashboards you built — is exactly the skill they develop in the consulting track.
- Applications close **15 April 2026**. Apply early.
