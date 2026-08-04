# ShopSquire on Azure AI Foundry — Deployment Architecture & Theorycraft

**Author context:** Kevin Jalop — prepared 2026‑07‑03 as (a) a reference architecture for porting ShopSquire onto Microsoft Azure AI Foundry, and (b) interview/portfolio evidence for the Wipro / Sydney Water "MS Foundry" AI Solutions Architect engagement.

**Status:** Design + theorycraft. Grounded in the actual codebase (file/line references throughout). Nothing here is deployed yet; a thin slice can be stood up later to make the claims hands‑on.

> **One‑paragraph answer.** ShopSquire's application tier is a **stateless, CPU‑only** FastAPI service (`python:3.11-slim`, no model weights baked in). Every AI/ML component either calls an **external inference endpoint** or falls back to a CPU heuristic. The *only* GPU‑hungry dependency is the **Ollama inference host** (qwen3 text models, `llava` vision, `nomic-embed` embeddings). Because the code **already ships an OpenAI‑compatible provider path** (`OPENAI_API_URL`, `EMBEDDINGS_PROVIDER=openai`), and **Azure OpenAI / Azure AI Foundry is OpenAI‑API‑compatible**, "deploy ShopSquire on Foundry" is mostly **repointing environment variables** — not a rewrite. That means you get two clean deployment shapes: **managed models (no GPU to run)** or **self‑hosted open models on a GPU node pool (sovereign, but you own the GPUs)**. High availability is a solved problem on the app tier (a Helm chart with 2 replicas + HPA + pod anti‑affinity already exists); the interesting HA/cost question is *entirely* about the model tier.

---

## How to read this document

| If you want… | Go to |
|---|---|
| The honest codebase picture (what actually runs, on what compute) | **Part A** |
| What "Foundry" means and the exact seam to repoint | **Part B** |
| The target Azure reference architecture | **Part C** |
| The "minimum 2 VMs or Kubernetes?" HA answer | **Part D** |
| The GPU pros/cons and sizing (the core of your question) | **Part E** |
| The eBGP / summary route‑table / networking answer | **Part F** |
| MLOps / LLMOps / CI‑CD | **Part G** |
| Why this wins for Sydney Water (SOCI / ISO 42001 / EU AI Act) | **Part H** |
| What's already done vs what to build | **Part I** |
| Phased rollout + rough cost | **Part J–K** |
| Interview talking points mapped to the JD | **Part L** |

---

## Part A — Codebase deep dive (ground truth)

### A.1 What the system is

- **Backend:** FastAPI (Python), ~99 routers / 200+ services, 4‑phase agent orchestrator (EXPLORE → EVALUATE → PLAN → ACTION). Entry `src/app/main.py`, served by `uvicorn` on `:8080`.
- **Frontend:** Vite/React SPA (`frontend/`, React 18 + Zustand + i18next). Builds to static assets — no server runtime.
- **Datastores:** PostgreSQL + **pgvector** (`pgvector/pgvector:pg16`), Redis 7 (session/agent memory), optional Neo4j 5 (fraud‑graph, profile‑gated and off by default).
- **Workers:** `sync-worker` (inventory), `security-crowdstrike-poll`, `security-syslog-listener`, `security-celery-worker` + `security-celery-beat` (Redis broker), `db-backup`, optional `graph-refresh`.
- **Observability:** Prometheus + Alertmanager + Grafana already wired in compose; OpenTelemetry instrumentation in `pyproject.toml`.

### A.2 The compute footprint — where GPU actually matters

This is the single most important finding for an Azure sizing decision. **The app container carries no model weights and needs no GPU.** The frozen runtime (`migration_artifacts/requirements-export.txt`) is CPU‑only (numpy/scipy/scikit‑learn/pandas/pillow/pytesseract/pyzbar). The heavy libraries in `pyproject.toml` (torch, paddleocr, sentence‑transformers, faiss, ultralytics, open‑clip, prophet, torch‑geometric) are **soft imports wrapped in try/except with CPU heuristic fallbacks** — most aren't even installed in the frozen env.

| Component | Code location | Compute | Notes |
|---|---|---|---|
| **Text LLM** (small→expert tiers) | `services/llm_provider.py:350` (`ollama_generate`), `config/ml/tier_ladder.json` | **GPU** (external Ollama) | qwen3‑vl:8b / qwen3:14b / qwen3.6:27b. This is the real GPU dependency. |
| **Vision LLM** (`llava`) | `services/cv_vision_ollama.py:39`, `services/cv_provider.py` | **GPU** (external Ollama) | Only fires on image‑bearing turns. |
| **Text embeddings** | `services/embeddings.py:109` | GPU (Ollama `nomic-embed`) **or** cloud | `EMBEDDINGS_PROVIDER` = `ollama` / `openai` / `bow` (hash fallback). pgvector dim = **1536**. |
| Vector similarity | `services/vector_store.py:64` | CPU | pgvector `<->` KNN in Postgres. |
| OCR (tesseract default, paddle optional) | `services/cv_ocr.py:46` | CPU | `tesseract-ocr` baked into image. |
| Barcode/QR, perceptual hash, forensics/steg/GAN detectors | `rules/barcode_decode.py`, `services/image_intake.py`, `security/*` | CPU | numpy/PIL DSP math. |
| IsolationForest anomaly, XGBoost intent | `analytics/isolation_forest.py`, `analytics/xgb_intent.py` | CPU | sklearn present; z‑score / rules fallbacks. |
| YOLO object detect, CLIP quality, GNN fraud | `services/cv_object_detector.py`, `services/cv_quality.py`, `services/gnn_fraud_detector.py` | Optional torch — **GPU‑capable, runs CPU, not installed → heuristic fallback** | `INSTALL_PYGEOMETRIC=1` (Dockerfile:46) opts into PyG (~1.5 GB). |

**Takeaway for Azure:** you provision GPU **only** for the model tier (Ollama replacement), and you get to *choose* whether that tier is Microsoft‑managed (Azure OpenAI, no GPUs to run) or self‑hosted (your own GPU pool). Everything else is horizontally‑scalable CPU that runs happily on 2‑vCPU/1 GiB pods.

### A.3 The seam that makes this easy

The LLM layer is already provider‑abstracted:

- **Primary:** Ollama over REST (`OLLAMA_URL`, default `http://127.0.0.1:11434`).
- **Cloud fallbacks already coded:** `OpenAIProvider` (`services/llm_providers.py:62`, `OPENAI_API_URL`, default `gpt-4o-mini`), plus Anthropic/Mistral providers, plus a direct `_openai_generate_fallback()` (`services/llm_provider.py:309`) that fires when Ollama is down. Selection via `get_provider()` / `ProviderRouter` (`services/llm_router.py`, env `LLM_PROVIDER_CHAIN`).
- **Embeddings** already support `EMBEDDINGS_PROVIDER=openai` → `text-embedding-3-small` (`services/embeddings.py:76`).

> **Azure OpenAI speaks the OpenAI API.** Point `OPENAI_API_URL` at `https://<resource>.openai.azure.com/openai/deployments/<deployment>/...` with the api‑key/AAD token and the deployment name, and the existing code path serves the platform from Foundry with **near‑zero application change**. (A ~1‑day hardening task adds an explicit `AzureOpenAIProvider` that sets `api-version` and AAD `DefaultAzureCredential` cleanly rather than reusing the OpenAI shape — see Part I.)

### A.4 Statefulness & secrets (what must move to managed services)

- **Postgres + pgvector** — catalog, auth tokens, decision‑trace/audit‑chain tables, `product_embeddings vector(1536)` (`services/vector_store.py:144`).
- **Redis** — session/agent memory (`session:{uid}:summary|kv_state|recent_retrieval|agent_steps|…`, `services/memory.py:10`), episodic memory + rate‑limit/replay dedup. **Graceful in‑memory fallback** when Redis is down.
- **Neo4j** — optional, `FRAUD_GRAPH_NEO4J_ENABLED` + `NEO4J_*`; degrades to 0 for two fraud signals when absent.
- **WORM audit** — S3 Object‑Lock (`observability/worm.py`, optional) and a local WORM file volume (`AUDIT_CHAIN_WORM_ARCHIVE_PATH`).
- **Secrets manager** already abstracts providers: `SECRETS_PROVIDER = env | vault | aws-sm`, with `NAME_REF` pointers like `vault://path#key` (`services/secrets_manager.py`). **No native Azure Key Vault provider yet** — see Part I for the two clean ways to close that (CSI driver = zero code, or add an `azure-kv` provider).
- **Production startup guards** (fail‑closed, `config.py:151`, `main.py:215`): live `STRIPE_API_KEY`; `REDIS_URL` must be `rediss://` + password; `PG_ENCRYPTION_AT_REST` + `RETENTION_CLEANUP_ENABLED` truthy; `AUDIT_CHAIN_EXTERNAL_ANCHOR_MODE` set; `BACKUP_ENCRYPTION_KEY|PASSPHRASE`; `AUDIT_CHAIN_SECRET` ≥32 chars. These map cleanly onto Azure managed features (see Appendix).

---

## Part B — What "deploy on Azure AI Foundry" means, and the mapping

**Azure AI Foundry** (formerly Azure AI Studio) is Microsoft's unified plane for building/deploying/governing GenAI. The pieces relevant here:

| Foundry capability | What it does | ShopSquire counterpart |
|---|---|---|
| **Model catalog + Azure OpenAI deployments** | Hosted GPT‑4o/4o‑mini/o‑series + open/partner models | Replaces Ollama text models |
| **Foundry Managed Compute** | Deploy an open model (Llama/Mistral/Phi/Qwen) onto Microsoft‑managed GPU behind an endpoint | Self‑host option without running your own AKS GPU pool |
| **Azure AI Agent Service** | Managed agent runtime, tools, threads | Optional façade over the existing orchestrator |
| **Prompt flow + Evaluations** | Author, version, and eval prompts/agents (groundedness, safety, relevance) | Formalises the RAGAS/eval hooks (`RAGAS_ENABLED`) |
| **Azure AI Content Safety + Prompt Shields** | Jailbreak/prompt‑injection/harmful‑content filters | Defense‑in‑depth **in front of** the existing deterministic policy gates |
| **Grounding with Azure AI Search** | Managed vector + hybrid RAG | Alternative/complement to pgvector |
| **Tracing / observability** | Token, latency, eval telemetry → App Insights | Feeds the bitemporal decision trace |

### The mapping (ShopSquire → Azure)

| ShopSquire | Azure target | Effort |
|---|---|---|
| Ollama text models (`OLLAMA_URL`, `OLLAMA_*_MODEL`) | **Azure OpenAI deployment** via `OPENAI_API_URL`, **or** self‑hosted open model on **Foundry Managed Compute / AKS GPU** | Config (managed) / medium (self‑host) |
| Complexity router 0–10 → tier (`tier_ladder.json`) | Map tiers to **two Azure OpenAI deployments** (e.g. `gpt-4o-mini` small/med, `gpt-4o` large/expert); nano tier still calls no model | Config |
| `llava` vision | `gpt-4o` vision, or self‑hosted VLM on Managed Compute | Config |
| `nomic-embed` / `EMBEDDINGS_PROVIDER=openai` | **Azure OpenAI `text-embedding-3-large/small`** (1536‑dim compatible) | Config |
| pgvector (1536) | **Azure Database for PostgreSQL Flexible Server** + `pgvector` (keep), optionally **Azure AI Search** for grounding | Lift‑and‑shift |
| Redis session/memory | **Azure Cache for Redis** (Enterprise for zone‑redundancy + TLS/ACL) | Lift‑and‑shift |
| Neo4j (optional) | **Neo4j Aura** or self‑host on AKS | Optional |
| Deterministic policy gates + security agents | **Keep authoritative**; add **Content Safety / Prompt Shields** as an outer layer | Additive |
| Bitemporal decision trace + WORM | Keep in Postgres; anchor WORM to **Blob Storage w/ immutability (legal hold)**; telemetry → **App Insights / Log Analytics** | Small adapter |
| `.env` / Vault secrets | **Azure Key Vault** (CSI driver or `azure-kv` provider) | Small |
| Frontend SPA | **Azure Static Web Apps** or Blob + **Front Door** | Config |
| Celery workers / pollers | **AKS Deployments** or **Azure Container Apps jobs** | Lift‑and‑shift |

**Design stance (recommended):** keep ShopSquire's **deterministic‑first control plane authoritative** (its whole value is that scoring/policy owns the verdict and the LLM only narrates). Use Foundry for **model hosting, guardrails, evaluation, and tracing** — i.e. Foundry as the *inference + safety + observability substrate*, not as the decision engine. This is both the honest engineering choice and the differentiated architecture story.

---

## Part C — Target Azure reference architecture

```
                          Internet (buyers / merchant admin)
                                    │
                    ┌───────────────▼────────────────┐
                    │  Azure Front Door (global anycast│  WAF, TLS, caching
                    │  + WAF)  →  Static Web App (SPA) │  bot mgmt, geo
                    └───────────────┬────────────────┘
                                    │  (API origin, private)
        ┌───────────────────────────▼───────────────────────────┐
        │            HUB VNet (Australia East)                    │
        │  Azure Firewall  •  Azure Route Server  •  Bastion      │
        │  ExpressRoute / VPN GW  ── eBGP ──►  Sydney Water DC     │
        └───────────────┬───────────────────────┬────────────────┘
                        │ peering               │ peering
        ┌───────────────▼──────────┐  ┌─────────▼───────────────────┐
        │  SPOKE: App (AKS)         │  │  SPOKE: Data + AI (PaaS)     │
        │  ┌──────────────────────┐ │  │  Private Endpoints only:     │
        │  │ App Gateway Ingress   │ │  │  • Azure OpenAI / Foundry    │
        │  │  (WAF v2) → nginx     │ │  │  • PostgreSQL Flexible (pgvec)│
        │  ├──────────────────────┤ │  │  • Azure Cache for Redis      │
        │  │ shopsquire-api x2..10 │ │  │  • Azure AI Search (optional) │
        │  │ (HPA, anti-affinity)  │ │  │  • Key Vault                  │
        │  │ celery / workers      │ │  │  • Blob (WORM audit, backups) │
        │  │ [opt] GPU nodepool    │◄┼──┤  • Container Registry (ACR)   │
        │  │   vLLM/Ollama x2       │ │  │  • Log Analytics / App Insts  │
        │  └──────────────────────┘ │  └──────────────────────────────┘
        └───────────────────────────┘
   3 Availability Zones • NSGs + UDRs force egress via Azure Firewall
```

Landing‑zone principles: **hub‑spoke** VNet topology; **private endpoints** for every PaaS service (no public data‑plane); **Private DNS zones**; **NSGs + UDRs** forcing all egress through Azure Firewall; **AAD/Managed Identity** for service‑to‑service auth (no static keys where avoidable); everything pinned to **Australia East** (+ Australia Southeast for DR) for data residency.

---

## Part D — High availability: "minimum 2 VMs, or Kubernetes?"

Direct answer: **run the app tier as ≥2 replicas across ≥2 (ideally 3) Availability Zones, and put a load balancer in front.** The codebase already assumes this — `helm/shopsquire/values.yaml` ships `replicaCount: 2`, HPA `minReplicas: 2 / maxReplicas: 10`, and pod **anti‑affinity** so replicas land on different nodes. Two VMs is the *floor*; the only real decision is **VMs vs Container Apps vs AKS**.

| Option | What it is | Pros | Cons | Verdict |
|---|---|---|---|---|
| **2× VMs** (VMSS) behind Load Balancer / App Gateway | IaaS; run the container (or uvicorn) on 2+ VMs in an Availability Set/Zones | Simplest mental model; full control; fine for a quick pilot | You patch/scale/monitor OS; no native rolling deploy; workers + GPU pool are separate concerns you wire by hand | OK for a **thin POC**, not for the target |
| **Azure Container Apps** | Serverless containers, KEDA autoscale, scale‑to‑zero | No cluster to run; built‑in ingress + revisions/rollbacks; cheap for spiky load; good for the **workers/pollers** | Less control over networking/GPU; GPU support is limited | Great for **workers + a low‑ops pilot** |
| **AKS** (Azure Kubernetes Service) | Managed Kubernetes | The Helm chart already targets it; multi‑AZ node pools; HPA/PDB/anti‑affinity; **dedicated GPU node pool** for self‑hosted models; matches the JD (K8s, microservices, distributed) | More to operate (mitigated by managed AKS + AGIC) | **Recommended target** — especially if self‑hosting models |

**HA building blocks (AKS target):**
- **App tier:** Deployment `replicas ≥ 3` across 3 AZs, `HorizontalPodAutoscaler` (already 2→10), `PodDisruptionBudget minAvailable: 2`, pod anti‑affinity (already present), `topologySpreadConstraints` per zone. Liveness/readiness probes already defined (`/healthz`).
- **Ingress:** **Application Gateway Ingress Controller (AGIC)** with **WAF v2** (OWASP CRS) — or keep nginx ingress. Front Door in front for global anycast + TLS + WAF + failover to a DR region.
- **Data tier:** **PostgreSQL Flexible Server — Zone‑Redundant HA** (hot standby in another AZ, automatic failover, PITR). **Azure Cache for Redis — Enterprise/zone‑redundant**, TLS + ACL (satisfies the `rediss://` + password prod guard). Both consumed over **private endpoints**.
- **Model tier HA (the crux):**
  - *Managed (Azure OpenAI):* Microsoft owns the SLA; you get multi‑replica capacity by buying **PTUs** or spreading across two regions with Front Door / APIM load‑balancing. **No GPU nodes to make redundant.**
  - *Self‑hosted:* the inference host is a **single point of failure unless you run ≥2 GPU nodes.** That doubles GPU cost — the central tension in Part E.
- **Stateless‑ness caveat:** Redis memory has an in‑memory fallback, so a Redis blip degrades (loses cross‑turn memory) rather than failing — good, but for real HA use zone‑redundant Redis so you don't silently lose session continuity.

**Bottom line:** 2 is the minimum for the app; **3 AZs on AKS** is the target. HA of the *model tier* is where "2 nodes minimum" costs real money — and is the reason managed Azure OpenAI is attractive for a first deployment.

---

## Part E — GPU: where it matters, sizing, and the pros/cons (the core question)

**Restating the key fact:** the only GPU workload is the model tier (text LLM + `llava` vision + `nomic` embeddings). So the GPU decision is a **build‑vs‑buy on inference**, independent of the rest of the platform.

### E.1 Two (or three) ways to serve models

| Approach | GPU you manage | Data boundary | Cost model | Ops burden |
|---|---|---|---|---|
| **A. Managed — Azure OpenAI / Foundry** | **None** | Stays in your Azure tenant/region (Australia East), not used to train Microsoft models | Pay‑per‑token, or **PTU** for reserved throughput/latency | Lowest — Microsoft runs the GPUs, SLA, patching, scaling |
| **B. Self‑host open model** — vLLM/Ollama on **AKS GPU pool** or **Foundry Managed Compute** | **Yes (2× for HA)** | Fully inside your VNet; **air‑gap possible** (matches the JanuSec sovereignty pattern) | Flat GPU rental (24×7) regardless of tokens | Highest — drivers, quotas, autoscaling cold‑start, model updates, no built‑in content safety |
| **C. Hybrid** — small/med tier self‑hosted, burst large/expert to Azure OpenAI | Some | Sensitive/routine in‑house; hard cases to managed | Mixed | Medium — but maps **exactly** onto the existing complexity router |

### E.2 GPU sizing if you self‑host (Option B/C)

Rough guidance (quantized served via vLLM/Ollama; VRAM is the binding constraint):

| Model (tier) | Params | ~VRAM (Q4/AWQ) | Azure GPU SKU (single node) |
|---|---|---|---|
| qwen3‑vl:8b (small/vision) | 8B | ~8–10 GB | **NCasT4_v3** (T4 16 GB) or **NVadsA10 v5** (A10 24 GB) |
| qwen3:14b (medium) | 14B | ~12–18 GB | **NVadsA10 v5** (A10 24 GB) |
| qwen3.6:27b (large/expert) | 27B | ~24–40 GB | **A10 24 GB (tight)** → **NC A100 v4** (A100 40/80 GB) |
| mixtral 8×7b (email/security tier) | 47B (MoE) | ~40–48 GB | **NC A100 v4 (80 GB)** or 2× A10 |

For HA multiply by **2 nodes**. In **Australia East**, A100 (ND/NC A100 v4) quota is scarce and must be requested; A10 (NVadsA10 v5) is easier to get and is the pragmatic sovereign choice for ≤14B tiers.

### E.3 Pros / cons — decision table

| Dimension | Managed (A) | Self‑host (B) |
|---|---|---|
| Time‑to‑first‑deploy | **Hours** (set env vars) | Days–weeks (quota, node pool, serving stack) |
| GPU HA | **Free** (Microsoft's SLA) | Costs 2× GPU nodes |
| Cost at low/spiky volume | **Cheaper** (pay per token) | Wasteful (paying 24×7 for idle GPUs) |
| Cost at high steady volume | Can get expensive per‑token → move to **PTU** | **Cheaper** once GPUs are saturated |
| Data sovereignty | In‑region, in‑tenant, not trained on — **strong**, but a managed service | **Strongest** (in‑VNet, air‑gap possible) — the SOCI/critical‑infra story |
| Content safety / jailbreak filters | **Built‑in** (Content Safety, Prompt Shields) | You add it (or reuse ShopSquire's gates) |
| Model choice / control | Curated catalog | **Any open weights**, full control, fine‑tune freely |
| Ops burden | **Minimal** | Real (drivers, cold‑start, upgrades) |

### E.4 Recommendation

- **POC / pilot → Option A (managed Azure OpenAI in Australia East, private endpoints).** Fastest, governed, sovereign‑enough (in‑region, in‑tenant, contractually not trained on). Zero GPUs to run. This is what you demo to the Sydney Water panel first.
- **If the client mandates hard sovereignty / air‑gap → Option C (hybrid).** Self‑host the small+medium tiers on a **2‑node A10 pool** for routine/sensitive traffic; burst the rare large/expert cases to Azure OpenAI. This is the exact behaviour the complexity router (`tier_ladder.json`) already implements — you're just choosing a different backend per tier. It's also the cleanest expression of your "deterministic control + reserve AI for genuinely complex cases" thesis.
- **Never** self‑host on a single GPU node in production — that reintroduces the single point of failure the rest of the design eliminates.

---

## Part F — Networking: eBGP, summary route tables, and "traffic to users"

Two different problems get conflated here; separating them is exactly the architect‑level precision worth showing the panel.

### F.1 Distributing traffic to *users* (north‑south) — **not** BGP

User‑facing load distribution in Azure is done with L7/L4 services, not routing protocols:

- **Azure Front Door** — global anycast entry, TLS termination, **WAF**, caching, and **multi‑region failover** (health‑probe based). This is your "spread users across regions/instances" layer.
- **Application Gateway (WAF v2)** / **Azure Load Balancer** — regional L7/L4 distribution to the AKS ingress / VMSS.
- **AKS ingress (AGIC or nginx)** + **Service** → spreads across pods/zones.

So: *"increase availability and distribute users"* = Front Door + App Gateway + AKS ingress + multi‑AZ replicas. **eBGP plays no role in app‑user load balancing** — Azure's data‑plane is software‑defined.

### F.2 Where eBGP and summary route tables *actually* live (east‑west / hybrid)

BGP in Azure is an **edge / hybrid‑connectivity** concern — relevant precisely because Sydney Water is an enterprise/critical‑infrastructure client that will want private connectivity between its own network and Azure:

- **ExpressRoute** — private circuit from Sydney Water's data centre to Azure. The ExpressRoute peerings (private peering, Microsoft peering) run **eBGP sessions** between the customer/provider edge and Microsoft Enterprise Edge routers. This is the canonical place you'd discuss eBGP.
- **VPN Gateway (route‑based)** — supports **BGP** over IPsec for dynamic route exchange as ExpressRoute backup or standalone.
- **Azure Route Server** — lets a network virtual appliance (e.g. a third‑party firewall/router in the hub) exchange routes with the Azure SDN via **BGP**, so you don't hand‑maintain UDRs when using an NVA.
- **Route summarization / summary route tables** — you advertise **aggregate prefixes** over BGP (e.g. Sydney Water advertises a summarized `10.x.0.0/12` into Azure instead of dozens of `/24`s, and Azure advertises the VNet summary back) to keep routing tables small and stable. Inside Azure you complement this with **User Defined Routes (UDRs)** in route tables that **force egress through Azure Firewall** (`0.0.0.0/0 → AzureFirewall`) and keep PaaS traffic on **private endpoints**.

### F.3 The realistic network design for a SOCI‑regulated client

1. **Hub‑spoke VNet** in Australia East; **Azure Firewall** in the hub.
2. **ExpressRoute** (with **eBGP** peering) for private, sovereign connectivity to Sydney Water's environment; VPN Gateway w/ BGP as failover.
3. **Route summarization** over BGP between on‑prem and Azure; **UDRs** in each spoke forcing egress via the firewall; **NSGs** for micro‑segmentation.
4. **Private Endpoints + Private DNS** for **every** PaaS data‑plane (Azure OpenAI, PostgreSQL, Redis, Key Vault, Storage, ACR, AI Search) — nothing sensitive traverses the public internet.
5. **Front Door + WAF** for the public buyer/admin surface; **Azure Route Server** only if an NVA firewall is used in the hub.

**One‑liner for interview:** *"User traffic is spread with Front Door + App Gateway + multi‑AZ ingress; eBGP and route summarization belong to the ExpressRoute/hybrid edge that privately connects the client's network, with UDRs forcing all egress through Azure Firewall and private endpoints keeping the AI and data planes off the public internet."*

---

## Part G — MLOps / LLMOps & CI/CD

The JD asks for MLOps/LLMOps + CI/CD; the repo already gives you a real story to build on (Helm chart, alembic migrations init‑container, db‑backup CronJob, Prometheus/Grafana, RAGAS eval hooks).

- **Build/release:** GitHub Actions or Azure DevOps → build image → push **Azure Container Registry (ACR)** → `helm upgrade` to AKS (blue/green or canary via two revisions + Front Door weighting). Migrations run as the existing init‑container job (`alembic upgrade head`).
- **LLMOps:** **Foundry Prompt Flow** for prompt/agent authoring + versioning; **Evaluations** (groundedness, relevance, safety) as a **release gate** — wire them to the existing `RAGAS_ENABLED` path so a prompt change that regresses faithfulness fails CI. Pin model **deployment names** per environment so prod/stage use different Azure OpenAI deployments.
- **Model registry / versioning:** Azure ML registry (for any self‑hosted/fine‑tuned weights) or Foundry model versions; ShopSquire already externalises model choice via `OLLAMA_*_MODEL` / tier ladder, so promotion = config change.
- **Observability:** OTel → **Application Insights** + **Log Analytics**; Prometheus/Grafana already present for infra. Token/cost/latency dashboards from Foundry tracing.
- **Governance gate:** the config‑integrity, prompt‑hash‑verify, and audit‑chain‑verify Celery beat jobs already exist — surface their results into the release pipeline as compliance evidence.

---

## Part H — Why this design wins for Sydney Water (the differentiator)

Sydney Water is **critical infrastructure regulated under the SOCI Act** (water is one of the designated sectors). For an agentic AI platform that means auditability, data residency, and human‑in‑the‑loop control aren't nice‑to‑haves — they're gating requirements. ShopSquire's architecture is unusually well‑suited to demonstrate the pattern:

- **Deterministic‑first control** — scoring/policy owns the verdict, the LLM only narrates. Predictable, explainable, cost‑bounded (nano tier calls no model at all).
- **Bitemporal decision trace + WORM audit** — reconstruct *what evidence, policy, and risk state existed at decision time*; anchor to immutable storage. This is exactly what an auditor or incident reviewer needs.
- **Security inside the decision path** — inputs scored and passed through policy gates **before** any action executes; Content Safety / Prompt Shields add a managed outer layer.
- **Sovereignty options** — in‑region managed inference, or fully in‑VNet / air‑gapped self‑hosting (the JanuSec pattern). Data stays on‑shore.
- **Governance‑by‑design mapping** — each significant AI action traceable to **ISO 27001 / ISO 42001 / EU AI Act / NIST AI RMF** controls. That's evidence by design, not retrofitted reporting — the thing regulated clients actually struggle to buy.

This is the pitch: *most contractors can wire Foundry; the value here is the auditable, sovereign, policy‑bounded governance layer a SOCI‑regulated water utility needs on top of it.*

---

## Part I — What's already done vs what to build

**Already in place (reusable as‑is):**
- Stateless CPU app + Helm chart (2 replicas, HPA 2→10, anti‑affinity, ingress, TLS via cert‑manager, migrations job, db‑backup CronJob).
- OpenAI‑compatible provider path + embeddings provider switch (the Azure OpenAI seam).
- Secrets abstraction (`env|vault|aws-sm`) with `NAME_REF` pointers.
- Production fail‑closed guards (audit secret, Redis TLS, PG encryption, backup encryption).
- Observability (Prometheus/Grafana/OTel), Celery integrity/audit beat jobs.

**To build before a real Azure deploy (rough effort):**
1. **`AzureOpenAIProvider`** (~1 day) — proper `api-version` + AAD `DefaultAzureCredential` instead of reusing the OpenAI URL shape; add to `LLM_PROVIDER_CHAIN`. Map tier ladder → two Azure OpenAI deployments.
2. **Azure Key Vault integration** (~1–2 days) — either **Key Vault CSI driver** projecting secrets into pods (zero code change), or add an `azure-kv` provider to `services/secrets_manager.py` alongside the existing Vault/AWS‑SM providers.
3. **Managed data tier** — provision PostgreSQL Flexible Server (zone‑redundant HA, pgvector extension) + Azure Cache for Redis (Enterprise, TLS/ACL) + set `rediss://`/`PG_ENCRYPTION_AT_REST` to satisfy prod guards.
4. **WORM anchor on Azure** — repoint the S3 WORM path to **Blob immutable storage (legal hold)** or add a small Azure adapter next to `observability/worm.py`.
5. **Networking** — hub‑spoke, private endpoints + Private DNS for all PaaS, Front Door + WAF, ExpressRoute/UDRs (Part F).
6. **CI/CD + eval gates** — ACR + Helm pipeline; Foundry evaluations wired to `RAGAS_ENABLED` as a release gate.
7. **Content Safety / Prompt Shields** — front the LLM calls (additive; gates stay authoritative).
8. **Sovereignty decision** — managed vs hybrid GPU (Part E) drives whether you also stand up a GPU node pool + vLLM.
9. **Real integrations' secrets** (only if in scope) — SMTP/OAuth for email, CrowdStrike, Stripe, Shopify.

---

## Part J — Phased rollout

1. **Phase 0 — Local‑to‑Azure smoke (days):** container to ACR; run on **Azure Container Apps** with **managed Azure OpenAI** (`OPENAI_API_URL` repoint); managed Postgres + Redis; secrets in Key Vault. Proves the seam.
2. **Phase 1 — AKS pilot (1–2 weeks):** Helm deploy to AKS, 3 AZs, AGIC + WAF, Front Door, private endpoints, HPA/PDB. Managed models. Foundry eval gate in CI.
3. **Phase 2 — Governance + sovereignty (2–4 weeks):** ExpressRoute/private connectivity, WORM on Blob, Content Safety, ISO 42001/EU AI Act control mapping surfaced in the decision trace, DR region.
4. **Phase 3 — Hybrid GPU (optional):** stand up a 2‑node A10 pool + vLLM for the small/medium tiers if hard sovereignty is required; keep large/expert on managed.

## Part K — Rough monthly cost sketch (pilot, Australia East, indicative only)

| Item | Managed‑models pilot | Hybrid (self‑host ≤14B) |
|---|---|---|
| AKS (3× D4s v5 system+app) | ~A$700–1,000 | ~A$700–1,000 |
| PostgreSQL Flexible (ZR HA, GP) | ~A$500–800 | ~A$500–800 |
| Azure Cache for Redis (Enterprise, ZR) | ~A$400–700 | ~A$400–700 |
| Front Door + WAF + App Gateway | ~A$300–500 | ~A$300–500 |
| **Model inference** | Azure OpenAI **pay‑per‑token** (scales with usage; tens–hundreds A$ at pilot volume, PTU later) | **2× A10 GPU nodes 24×7** ≈ A$2,500–4,000 |
| Storage / Key Vault / ACR / Log Analytics | ~A$200–400 | ~A$200–400 |

Managed models keep the pilot cheap and turn inference into a usage‑linear line item; self‑hosting front‑loads a fixed GPU cost that only pays off at sustained high volume — the classic build‑vs‑buy crossover.

---

## Part L — Interview talking points, mapped to the JD

| JD requirement | Your evidence |
|---|---|
| **MS Foundry experience** | This reference architecture: Foundry as inference + safety + eval + tracing substrate; Azure OpenAI via the existing OpenAI‑compatible seam; Agent Service as optional façade. |
| ML / NLP / Deep Learning / GenAI | 4‑phase orchestrator, complexity routing, RAG, structured output, vision (llava/CV pipeline), fraud ML (IsolationForest/GNN). |
| LLMs, RAG, Agentic AI frameworks | pgvector RAG, multi‑agent orchestrator, policy‑gated agentic actions, HITL escalation. |
| Python / Java | Python throughout (FastAPI). |
| Cloud: Azure / AWS / GCP | Azure landing zone here; secrets abstraction already supports AWS‑SM; multi‑cloud design experience (Go Cloud Careers). |
| TensorFlow / PyTorch | PyTorch via sentence‑transformers / optional PyG. |
| Data engineering / big data | Postgres/pgvector, embedding pipelines, inventory sync workers, market‑warehouse depth/retention. |
| MLOps / LLMOps + CI/CD | Helm + alembic migrations + ACR pipeline + Foundry evaluations as release gate (Part G). |
| Enterprise architecture / microservices / APIs / distributed | 99 routers, Celery workers, hub‑spoke, private endpoints. |
| DevOps / Docker / Kubernetes | Dockerfile + full Helm chart with HPA/anti‑affinity (Part D). |
| Stakeholder mgmt / translate business → AI / cost‑risk‑perf | Deterministic‑first cost bounding; managed‑vs‑self‑host build/buy; SOCI/ISO 42001 governance framing (Part E, H). |

---

### Appendix — env var → Azure resource

| ShopSquire env | Azure resource |
|---|---|
| `OPENAI_API_URL` / `OPENAI_API_KEY` / model names | Azure OpenAI endpoint + deployment (AAD or key in Key Vault) |
| `OLLAMA_URL`, `OLLAMA_*_MODEL`, `CV_VISION_MODEL` | (self‑host path) vLLM/Ollama endpoint on AKS GPU pool / Foundry Managed Compute |
| `EMBEDDINGS_PROVIDER=openai`, `OPENAI_EMBEDDINGS_MODEL` | Azure OpenAI `text-embedding-3-*` |
| `DATABASE_URL` | Azure Database for PostgreSQL Flexible Server (+ pgvector, ZR‑HA), via private endpoint |
| `REDIS_URL` (`rediss://…`), `REDIS_ACL_*` | Azure Cache for Redis (Enterprise, ZR, TLS/ACL) |
| `NEO4J_*` (optional) | Neo4j Aura / self‑host on AKS |
| `SECRETS_PROVIDER`, `*_REF`, `AUDIT_CHAIN_SECRET`, `JWT_SIGNING_KEY`, `BACKUP_ENCRYPTION_KEY` | Azure Key Vault (CSI driver or `azure-kv` provider) |
| `WORM_S3_*` / `AUDIT_CHAIN_WORM_ARCHIVE_PATH` | Azure Blob immutable storage (legal hold) |
| `AUDIT_CHAIN_EXTERNAL_ANCHOR_MODE` | External anchor (e.g. periodic hash to Blob/ledger) |
| SPA static build | Azure Static Web Apps / Blob + Front Door |
| Prometheus/Grafana/OTel | Managed Grafana / App Insights / Log Analytics |
| Front Door / App Gateway / Firewall / ExpressRoute | Networking (Part C, F) |

*End of document.*
