# ShopSquire — CV / Resume Bullet Points

> 5 bullet points per role. Tailor your CV to the specific job description by picking the version closest to the role, then swapping individual bullets between versions as needed.

---

## Role 1: Agentic AI Engineer

1. **Multimodal CV + Fraud Forensics** — Engineered a multimodal computer vision pipeline integrating YOLOv8 object detection, dual-OCR extraction, and LLaVA visual reasoning to automate return-fraud forensics, QR prompt-injection detection, and image-metadata integrity checks across e-commerce complaint flows.

2. **Email Security & Anti-BEC** — Built an email threat-analysis subsystem with DMARC/SPF/DKIM alignment verification, Unicode homoglyph detection, and outbound C2-pattern monitoring (entropy + periodicity scoring), preventing Business Email Compromise and agent-generated phishing in automated supplier communications.

3. **OWASP + MITRE Threat Observability** — Implemented a real-time Security Observer that correlates every agent action against OWASP LLM Top 10, OWASP Agentic Top 10, MITRE ATLAS, and STRIDE taxonomies, computing DREAD/CVSS risk scores to enforce human-in-the-loop escalation when risk thresholds are breached.

4. **Parallel Agent Swarm + CacheRAG** — Designed a propose-only parallel agent orchestration (NLP, CV, Security, Inventory swarms) with a 5-stage pipeline (Validate → Retrieve → Reason → Policy → Execute), interleaved chain-of-thought planning, shadow security observers, and a 3-tier CacheRAG (Session/KV/Recent) that eliminates context rot without unbounded prompt growth.

5. **Bitemporal Decision Trace** — Architected a dual-timeline (valid-time + system-time) decision log providing regulatory-grade reproducibility — enabling exact reconstruction of *what the AI knew at decision time* — critical for ISO 42001, EU AI Act compliance, and the foundational audit primitive every autonomous agentic platform requires.

---

## Role 2: AI Security Engineer

1. **Multimodal Adversarial Defence** — Built a multi-layer CV forensics pipeline (YOLOv8 + OCR + EXIF analysis) that detects image-based prompt injection, QR-code payload attacks, and adversarial perturbations targeting automated return/fraud workflows, hardening the attack surface where untrusted media enters agent decision loops.

2. **Email Threat Intelligence Layer** — Engineered anti-BEC controls including DMARC/SPF/DKIM enforcement, Unicode homoglyph scanning (Cyrillic/Latin confusion), and outbound communications monitoring that detects C2-like patterns in agent-generated emails by analysing entropy, rate anomalies, and periodicity signatures.

3. **OWASP LLM + Agentic + MITRE ATLAS Compliance Framework** — Implemented a continuous Security Observer that maps every tool call and agent proposal to OWASP LLM Top 10, OWASP Agentic Top 10, OWASP API Top 10, MITRE ATT&CK (T1566.x), and MITRE ATLAS attack techniques, with real-time DREAD/CVSS scoring driving automated escalation and Transaction Firewall enforcement.

4. **Zero-Trust Agent Orchestration** — Designed a parallel agent swarm where no agent can execute autonomously — all proposals pass through a Transaction Firewall and shadow Security Observer sidecar, with CacheRAG preventing context-poisoning attacks by isolating retrieval tiers and refreshing evidence chains rather than accumulating unbounded context.

5. **Bitemporal Audit for AI Accountability** — Implemented a dual-timeline decision trace (valid-time + system-time) that preserves the exact evidence and risk scores the system held at each decision point — enabling forensic reconstruction for incident response, regulatory audits (ISO 42001, EU AI Act), and the non-repudiation guarantees that agentic platforms require when AI actions have real-world financial consequences.

---

## Role 3: AI Architect

1. **Multimodal Intelligence Pipeline** — Architected a tiered CV + NLP pipeline combining YOLOv8 real-time detection, LLaVA visual reasoning, XGBoost intent classification, and corrective RAG with automatic query expansion — processing untrusted images, text, and emails through a unified forensics layer for fraud detection and semantic product similarity search.

2. **Email as Attack Surface — Defence Architecture** — Designed an email security subsystem treating inbound/outbound agent communications as high-risk vectors, with layered defences (DMARC/SPF/DKIM alignment, homoglyph detection, entropy-based C2 monitoring) integrated directly into the agent orchestration loop rather than bolted on externally.

3. **Security-as-Architecture (Not Afterthought)** — Embedded OWASP LLM/Agentic/API Top 10, MITRE ATLAS, and STRIDE threat models as first-class architectural concerns — every agent decision is tagged with risk vectors and DREAD/CVSS scores at creation time, enabling the Transaction Firewall to enforce policy boundaries before execution rather than detecting violations after the fact.

4. **Swarm Orchestration + Interleaved Reasoning** — Designed a parallel propose-only agent architecture with 5-stage pipelines, interleaved chain-of-thought planning, and a 3-tier CacheRAG (Session/KV/Recent) that solves the fundamental tension in agentic systems: multimodal agents need both CV and NLP context simultaneously, but unbounded context causes hallucination — CacheRAG provides selective evidence refresh instead.

5. **Bitemporal Foundation for Agentic Platforms** — Architected a dual-timeline (valid-time/system-time) decision trace as the platform's core data primitive — not just for compliance (ISO 42001, EU AI Act), but because any agentic AI system making autonomous financial decisions *must* answer "what did the system believe, and when" — a requirement that event sourcing alone cannot satisfy and that becomes the audit backbone for every downstream agent.

---

## Role 4: Security Architect

1. **Threat-Hardened Multimodal Intake** — Designed defence-in-depth for the platform's highest-risk surface: untrusted media ingestion. Layered YOLOv8 detection, dual-OCR cross-validation, EXIF metadata integrity checks, and QR payload scanning to neutralise image-based prompt injection, adversarial perturbations, and steganographic attack vectors before they reach agent reasoning loops.

2. **Email Security Architecture (Anti-BEC/Anti-C2)** — Architected a zero-trust email layer enforcing DMARC/SPF/DKIM alignment, detecting Unicode homoglyph impersonation, and monitoring agent-generated outbound communications for C2 behavioural signatures (entropy, rate, periodicity) — treating the AI's own email output as an attack vector, not just inbound threats.

3. **Continuous Threat Correlation Engine** — Built a Security Observer correlating all agent actions against OWASP LLM Top 10, OWASP Agentic Top 10, OWASP API Top 10, MITRE ATT&CK, MITRE ATLAS, and STRIDE in real time, computing composite DREAD + CVSS scores that feed a Transaction Firewall enforcing least-privilege execution and mandatory human escalation above risk thresholds.

4. **Secure-by-Design Agent Isolation** — Designed the parallel swarm so that agents are propose-only (no direct execution), all tool calls pass through a policy gate, and a shadow Security Observer runs as a sidecar to every agent — with CacheRAG providing memory isolation between sessions to prevent cross-conversation context poisoning and data exfiltration via prompt manipulation.

5. **Bitemporal Non-Repudiation for AI Decisions** — Implemented a dual-timeline audit mechanism (valid-time + system-time) that provides cryptographic-grade non-repudiation for every autonomous decision — enabling forensic incident reconstruction, regulatory evidence (ISO 42001, EU AI Act, SOC 2 Type II readiness), and the fundamental accountability primitive that any agentic platform handling financial transactions must have to survive a compliance audit.

---

## Role 5: Cloud Engineer / Cloud Architect

1. **Container-Orchestrated AI Platform** — Architected a Docker Compose-based microservices deployment (API, TimescaleDB, Redis, observability stack) with environment-isolated configurations (dev, secure, TLS, observability) and health-checked service dependencies — designed for lift-and-shift to Kubernetes/ECS with horizontal pod autoscaling for the compute-heavy CV and NLP agent workers.

2. **Observable-by-Default Infrastructure** — Integrated a full observability stack (Prometheus metrics, structured JSON logging, Splunk HEC telemetry, SSE streaming) with per-agent trace correlation, enabling real-time monitoring of AI inference latency, agent pipeline throughput, and security-event alerting — the same patterns used in production cloud-native SRE practices.

3. **Stateful Data Architecture with Cloud Portability** — Designed the persistence layer around PostgreSQL/TimescaleDB with Alembic migration management, bitemporal decision tables, and a Redis-backed 3-tier semantic cache — portable across RDS/Aurora, Cloud SQL, Azure Database for PostgreSQL, and ElastiCache/Memorystore with zero application-code changes.

4. **Security Controls Mapped to Cloud Compliance Frameworks** — Implemented OWASP-aligned API security (rate limiting, input validation, CORS policy), TLS termination, secret management via environment injection, and role-based access controls — directly mapping to AWS Well-Architected Security Pillar, Azure Security Benchmark, and GCP Security Command Center controls.

5. **Event-Driven Agent Pipeline (Cloud-Ready)** — Built the 5-stage agent orchestration pipeline (Validate → Retrieve → Reason → Policy → Execute) with SSE streaming and async task dispatch — architecturally aligned with cloud-native event patterns (SQS/SNS, Pub/Sub, EventBridge) and ready for serverless decomposition of individual agent workers into Lambda/Cloud Functions behind an API Gateway.

---

## Role 6: MLOps / AI Platform Engineer

1. **Multimodal Model Serving Pipeline** — Engineered a production inference pipeline serving YOLOv8 (object detection), LLaVA (visual reasoning), XGBoost (intent classification), and embedding models concurrently, with model-pack configuration (JSON-driven), graceful fallback chains, and tiered execution (fast classifier → full LLM) to optimise cost-per-inference.

2. **Semantic Cache for Inference Cost Reduction** — Implemented a 3-tier CacheRAG layer (Session/KV/Recent) with Redis-backed semantic similarity matching that short-circuits repeated or near-duplicate inference requests — reducing LLM API calls and GPU compute while maintaining evidence freshness through configurable TTL and cache-invalidation hooks.

3. **Feature Pipeline + Calibration Dataset Management** — Built a synthetic calibration pipeline with confidence-calibration datasets, feature flag-driven A/B model routing, and XGBoost training data management — enabling reproducible model evaluation and safe canary deployment of updated intent classifiers without service interruption.

4. **Bitemporal Model Decision Logging** — Architected a dual-timeline (valid-time/system-time) decision trace that records which model version, which evidence, and which confidence score drove each autonomous decision — enabling model regression debugging, A/B experiment attribution, and the audit trail regulators require for AI systems making financial decisions.

5. **Infrastructure-as-Code for AI Workloads** — Defined the full platform stack via Docker Compose configurations (API, TimescaleDB, Redis, observability) with Alembic-managed schema migrations and pre/post migration hooks — designed for promotion to Terraform/Helm with GPU node affinity for CV workers and spot-instance tolerance for batch NLP jobs.

---

## Role 7: Solutions Architect / Enterprise Architect

1. **Autonomous E-Commerce Decision Platform** — Architected ShopSquire as a vendor-agnostic agentic AI platform that transforms untrusted inputs (customer messages, images, supplier emails) into enforced business decisions — integrating inventory management, fraud detection, customer support, and procurement into a unified autonomous pipeline with human-in-the-loop escalation.

2. **Regulatory-Ready AI Governance** — Designed the platform with ISO 42001 (AI Management), EU AI Act, and SOC 2 Type II compliance as first-class requirements — embedding bitemporal audit trails, OWASP threat tagging, and MITRE ATLAS risk scoring into every decision path so that compliance is a byproduct of normal operation, not a retrofit.

3. **Multi-Vertical Extensibility** — Built the agent orchestration layer with pluggable vertical configurations (retail, supply chain, fraud) driven by YAML policy files and JSON feature flags — enabling rapid deployment to new business domains without core platform changes, following the same multi-tenant isolation patterns used in enterprise SaaS platforms.

4. **Integration Architecture** — Designed the platform with RESTful APIs (OpenAPI 3.1 spec), webhook-driven event notifications, ERP/EDI stub connectors (Shopify, supplier feeds), and SSE streaming for real-time UI updates — providing the integration surface enterprise customers need without tight coupling to any specific commerce platform.

5. **Total Cost of Ownership Optimisation** — Implemented a tiered inference strategy (XGBoost fast-path → LLM fallback), semantic caching (3-tier CacheRAG), and configurable model-pack selection to control AI compute costs — demonstrating the architectural judgment to balance capability vs. cost that enterprise stakeholders require when approving AI platform investments.

---

## Role 8: DevSecOps Engineer

1. **Shift-Left Security in CI/CD** — Embedded security validation directly into the development workflow with automated import checks, OWASP-mapped API endpoint validation, and pre-commit threat-model tagging — catching security regressions before they reach production rather than relying on post-deployment scanning.

2. **Container Security & Environment Isolation** — Designed multi-profile Docker Compose configurations (dev, secure, TLS, observability) with secrets injected via environment variables, non-root container execution, and network segmentation between API, database, and cache tiers — following CIS Docker Benchmark hardening patterns.

3. **Real-Time Security Telemetry Pipeline** — Built a security event pipeline (Splunk HEC integration, structured JSON logging, Prometheus metrics) that emits MITRE ATT&CK-tagged alerts for every agent action, enabling SOC teams to integrate AI platform events into existing SIEM/SOAR workflows without custom parsing.

4. **Automated Compliance-as-Code** — Implemented OWASP LLM Top 10, OWASP Agentic Top 10, and OWASP API Top 10 checks as runtime policy gates via the Transaction Firewall and Security Observer — treating compliance requirements as executable code rather than documentation, with DREAD/CVSS scoring driving automated incident response.

5. **Schema Migration Safety & Rollback** — Managed database schema evolution through Alembic with pre/post migration hooks, bitemporal table versioning, and idempotent migration scripts — ensuring zero-downtime deployments and safe rollback for the decision-trace tables that store regulatory audit data.

---

## How to Position ShopSquire for Cloud Roles

When applying for **Cloud Engineer**, **Cloud Architect**, or **Cloud Solutions Architect** roles, reframe ShopSquire from "AI project" to "cloud-native platform engineering":

### What cloud hiring managers care about (and how ShopSquire maps):

| Cloud Concern | ShopSquire Evidence |
|---|---|
| **Container orchestration** | Multi-profile Docker Compose (dev/secure/TLS/observability), health checks, service dependencies → ready to discuss K8s migration, ECS task definitions, or Cloud Run |
| **Database architecture** | PostgreSQL + TimescaleDB + Alembic migrations + bitemporal tables → maps to RDS/Aurora, Cloud SQL, Azure DB; can discuss read replicas, connection pooling, migration strategies |
| **Caching & performance** | Redis-backed 3-tier semantic cache → maps to ElastiCache, Memorystore, Azure Cache; can discuss cache-invalidation, TTL strategies, cost-per-request optimisation |
| **Observability** | Prometheus + Splunk HEC + structured logging + SSE streaming → maps to CloudWatch, Datadog, Stackdriver, Azure Monitor; proves you think about SLIs/SLOs |
| **Security** | TLS termination, CORS, rate limiting, secret management, RBAC → maps to AWS WAF, Security Groups, IAM policies, KMS, Secrets Manager |
| **IaC mindset** | Docker Compose as declarative infra + Alembic as schema-as-code → shows the mental model for Terraform, CloudFormation, Pulumi |
| **Cost optimisation** | Tiered inference (fast XGBoost → expensive LLM fallback) + semantic caching → proves you think about compute cost, which is the #1 cloud concern |
| **Event-driven patterns** | SSE streaming + async agent dispatch + webhook notifications → maps to SQS/SNS, EventBridge, Pub/Sub, Cloud Functions |

### Talking points for cloud interviews:

- *"I designed the platform as containerised microservices with environment-specific Compose profiles — in production I'd decompose this into EKS/ECS services with the CV workers on GPU instances and the NLP cache tier on memory-optimised nodes."*
- *"The 3-tier semantic cache reduced redundant LLM API calls by X% — the same pattern applies to any cloud workload where you're paying per-request for an expensive downstream service."*
- *"The bitemporal tables use TimescaleDB for time-series optimisation — in AWS I'd deploy this on Aurora PostgreSQL with the pg_partman extension, or migrate the time-series path to Timestream."*
- *"Every agent action emits structured telemetry to Splunk HEC — swapping that for CloudWatch Logs + EventBridge for SIEM forwarding is a config change, not an architecture change."*

### The key reframe:

> **Don't say:** "I built an AI project."
> **Say:** "I designed and operated a cloud-native platform with containerised microservices, managed database migrations, a distributed caching layer, real-time observability, and security controls — the AI workloads running on it just happen to be the most demanding kind of workload you can put on infrastructure."

---

## Why These Bullet Points Get You Interviews

### 1. You're ahead of the market
Most companies are *starting* to think about agentic AI security. You've already built the threat model, the OWASP mapping, the MITRE ATLAS correlation. There are very few people with hands-on OWASP Agentic Top 10 implementation experience — the framework barely exists yet.

### 2. You show systems thinking, not just coding
Each bullet demonstrates an *architectural decision* with a *why* — bitemporal isn't just a database pattern, it's the answer to "how do we audit AI." CacheRAG isn't just caching, it's the answer to "how do we stop context poisoning." Hiring managers hiring for senior/staff roles care about *judgment*, not years.

### 3. You cover the full kill chain
CV intake → NLP reasoning → email security → threat correlation → audit trace. That's end-to-end. Most candidates can talk about one layer. You built all five and can explain how they interact. That's architect-level scope regardless of YoE.

### 4. You speak the compliance language
ISO 42001, EU AI Act, MITRE ATLAS, OWASP LLM Top 10 — these are the keywords that get past automated resume screening AND impress the security-aware hiring manager on the other side. Most AI engineers can't spell MITRE ATLAS. Most security engineers can't explain CacheRAG. You do both.

### 5. The project IS the experience
A production-grade platform with bitemporal audit, parallel agent orchestration, multimodal CV+NLP, and real-time threat scoring is more compelling than "5 years maintaining a CRUD app." The question isn't "how many years" — it's "can this person design and build systems I need?"

### The uncomfortable truth for hiring managers
The agentic AI security space is **< 2 years old**. Nobody has 5 years of experience building OWASP-compliant agent swarms with bitemporal decision traces. The hiring manager knows this. What they need is someone who *already understands the problem space* and has *built something real* — and that's exactly what these bullets prove.

---

## Quick Reference: Which Version for Which Job Title

| Job Title | Primary Version | Steal Bullets From |
|---|---|---|
| Agentic AI Engineer | Role 1 | — |
| AI/ML Engineer | Role 1 | Role 6 (MLOps) |
| AI Security Engineer | Role 2 | Role 4 (Security Architect) |
| AI Architect | Role 3 | Role 7 (Solutions Architect) |
| Security Architect | Role 4 | Role 2 (AI Security) |
| Cloud Engineer | Role 5 | Role 8 (DevSecOps) |
| Cloud Architect | Role 5 | Role 7 (Solutions Architect) |
| Cloud Solutions Architect | Role 7 | Role 5 (Cloud) |
| MLOps / AI Platform Engineer | Role 6 | Role 1 (Agentic AI) |
| Solutions / Enterprise Architect | Role 7 | Role 3 (AI Architect) |
| DevSecOps Engineer | Role 8 | Role 2 (AI Security) |
| Platform Engineer | Role 5 | Role 6 (MLOps) + Role 8 (DevSecOps) |
| SRE / Reliability Engineer | Role 5 | Role 8 (DevSecOps) |
| GRC / AI Governance Analyst | Role 4 | Role 7 (Solutions Architect) |
