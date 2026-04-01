# ShopSquire — Cloud Architecture, Deployment & Scaling Blueprint

**Version:** 1.0 · **Date:** 2026-03-29  
**Scope:** End-to-end production deployment across public cloud, hybrid, and colo topologies.

---

## Table of Contents

1. [Component Inventory & Compute Requirements](#1-component-inventory--compute-requirements)
2. [Network Architecture — Subnets, DMZ & Blast-Radius Isolation](#2-network-architecture)
3. [ASCII Architecture Diagrams](#3-ascii-architecture-diagrams)
4. [User Flow Walkthrough](#4-user-flow-walkthrough)
5. [Scaling Matrix: 100 → 25,000 Concurrent Users](#5-scaling-matrix)
6. [Horizontal Auto-Scaling & K8s Pod Strategy](#6-horizontal-auto-scaling--k8s-pod-strategy)
7. [GPU Placement Strategy](#7-gpu-placement-strategy)
8. [Hybrid Multi-Cloud & Colocation Strategy](#8-hybrid-multi-cloud--colocation-strategy)
9. [FinOps Management](#9-finops-management)
10. [SWOT Analysis](#10-swot-analysis)
11. [PESTEL Analysis](#11-pestel-analysis)
12. [Pros & Cons Summary](#12-pros--cons-summary)
13. [Pushbacks, Alternatives & Open Questions](#13-pushbacks-alternatives--open-questions)

---

## 1. Component Inventory & Compute Requirements

Based on the actual codebase analysis:

```
┌──────────────────────────┬────────────────────┬──────────┬─────────┬────────────┬─────────────────────┐
│ Component                │ Codebase Source     │ CPU/GPU  │ Min RAM │ Stateful?  │ Scaling Pattern     │
├──────────────────────────┼────────────────────┼──────────┼─────────┼────────────┼─────────────────────┤
│ API Gateway / Ingress    │ nginx ingress       │ CPU      │ 256 Mi  │ No         │ HPA on connections  │
│ FastAPI Core API         │ src/app/main.py     │ CPU      │ 512 Mi  │ No         │ HPA CPU/RPS         │
│ Frontend (Vite/React)    │ frontend/           │ CPU      │ 128 Mi  │ No         │ CDN + static        │
│ Sync Worker              │ scripts/sync_worker │ CPU      │ 256 Mi  │ No         │ 1-3 replicas        │
│ Task Runner (Redis Strm) │ workers/task_runner │ CPU      │ 256 Mi  │ No         │ HPA queue depth     │
│ RQ / Celery Workers      │ workers/rq_queue    │ CPU      │ 512 Mi  │ No         │ HPA queue depth     │
│ Email Connector Worker   │ workers/email_conn  │ CPU      │ 256 Mi  │ No         │ HPA queue depth     │
│ CrowdStrike Poll Worker  │ security_crowdstrik │ CPU      │ 128 Mi  │ No         │ Singleton           │
│ LLM Router / Provider    │ services/llm_router │ CPU*     │ 1 Gi    │ No         │ HPA on latency      │
│ Ollama Sidecar (Vision)  │ services/ollama_cli │ GPU      │ 4 Gi    │ Model wts  │ VPA + node pool     │
│ CV Pipeline (YOLO)       │ src/app/cv/         │ GPU      │ 2 Gi    │ Model wts  │ VPA + node pool     │
│ Embedding Pipeline       │ services/embeddings │ CPU/GPU† │ 1 Gi    │ No         │ HPA on queue        │
│ RAG Index / Retrieve     │ src/app/rag/        │ CPU      │ 512 Mi  │ No         │ HPA with API        │
│ Voice ASR/TTS            │ services/voice_*    │ GPU      │ 2 Gi    │ No         │ HPA on sessions     │
│ Semantic Search / Vector │ services/vector_sto │ CPU      │ 512 Mi  │ pgvector   │ With DB             │
│ PostgreSQL 16 + pgvector │ pgvector/pgvector   │ CPU      │ 2 Gi    │ Yes        │ Read replicas       │
│ TimescaleDB (metrics)    │ timescaledb compose │ CPU      │ 1 Gi    │ Yes        │ Vertical + shards   │
│ Redis 7                  │ redis:7-alpine      │ CPU‡     │ 512 Mi  │ Yes(AOF)   │ Cluster mode        │
│ Prometheus               │ observability stack │ CPU      │ 512 Mi  │ Yes(TSDB)  │ Federation          │
│ Grafana                  │ observability stack │ CPU      │ 256 Mi  │ Config     │ Singleton           │
│ Loki                     │ observability stack │ CPU      │ 512 Mi  │ Yes        │ Microservices mode  │
│ Promtail                 │ observability stack │ CPU      │ 128 Mi  │ No         │ DaemonSet           │
│ Jaeger                   │ observability stack │ CPU      │ 512 Mi  │ Yes        │ Collector scaling   │
│ Alertmanager             │ observability stack │ CPU      │ 128 Mi  │ HA pair    │ Mesh 2-3 replicas   │
│ KEV Cron                 │ observability/cron  │ CPU      │ 64 Mi   │ No         │ CronJob             │
│ Alembic Migrations       │ helm migrations job │ CPU      │ 256 Mi  │ No         │ Job (run-once)      │
└──────────────────────────┴────────────────────┴──────────┴─────────┴────────────┴─────────────────────┘

* LLM Router is CPU if calling external APIs (OpenAI); GPU if self-hosting via Ollama
† Embedding can be CPU (BoW/TF-IDF) or GPU (sentence-transformers, OpenAI API = CPU)
‡ Redis is CPU; see Section 7 for GPU/SmartNIC acceleration discussion
```

---

## 2. Network Architecture

### 2.1 Subnet Topology — Five-Tier Isolation

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              VPC  10.0.0.0/16                               │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  TIER 1 — DMZ / PUBLIC SUBNET  10.0.101-103.0/24  (3 AZs)         │    │
│  │  ┌──────────┐  ┌──────────┐  ┌─────────────────────┐              │    │
│  │  │ ALB/NLB  │  │ WAF/     │  │ CloudFront CDN      │              │    │
│  │  │ Ingress  │  │ Shield   │  │ (frontend static)   │              │    │
│  │  └────┬─────┘  └──────────┘  └─────────────────────┘              │    │
│  │       │                                                            │    │
│  └───────┼────────────────────────────────────────────────────────────┘    │
│          │ (only port 443 inbound)                                         │
│  ┌───────┼────────────────────────────────────────────────────────────┐    │
│  │  TIER 2 — APP SUBNET (PRIVATE)  10.0.1-3.0/24  (3 AZs)           │    │
│  │       ▼                                                            │    │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌───────────────┐        │    │
│  │  │ FastAPI  │ │ FastAPI  │ │ FastAPI  │ │ Sync Workers  │        │    │
│  │  │ Pod (n)  │ │ Pod (n)  │ │ Pod (n)  │ │ Task Runners  │        │    │
│  │  └────┬─────┘ └────┬─────┘ └────┬─────┘ │ Email Workers │        │    │
│  │       │             │            │        └──────┬────────┘        │    │
│  └───────┼─────────────┼────────────┼───────────────┼─────────────────┘    │
│          │             │            │               │                       │
│  ┌───────┼─────────────┼────────────┼───────────────┼─────────────────┐    │
│  │  TIER 3 — ML/AI SUBNET (PRIVATE)  10.0.11-13.0/24  (GPU nodes)   │    │
│  │       ▼             ▼            ▼               ▼                 │    │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────────┐ ┌──────────────┐     │    │
│  │  │ Ollama   │ │ CV/YOLO  │ │ Voice ASR/   │ │ Embedding    │     │    │
│  │  │ Vision   │ │ Pipeline │ │ TTS Pods     │ │ Pipeline     │     │    │
│  │  │ Pods     │ │ Pods     │ │              │ │ (if GPU)     │     │    │
│  │  └──────────┘ └──────────┘ └──────────────┘ └──────────────┘     │    │
│  └────────────────────────────────────────────────────────────────────┘    │
│                                                                             │
│  ┌────────────────────────────────────────────────────────────────────┐    │
│  │  TIER 4 — CACHE SUBNET (PRIVATE)  10.0.21-23.0/24                 │    │
│  │  ┌──────────────────────┐  ┌──────────────────────┐               │    │
│  │  │ Redis Cluster        │  │ Semantic Cache        │               │    │
│  │  │ (ElastiCache)        │  │ (services/semantic_   │               │    │
│  │  │ Primary + Replicas   │  │  cache.py companion)  │               │    │
│  │  └──────────────────────┘  └──────────────────────┘               │    │
│  └────────────────────────────────────────────────────────────────────┘    │
│                                                                             │
│  ┌────────────────────────────────────────────────────────────────────┐    │
│  │  TIER 5 — DATA SUBNET (PRIVATE)  10.0.31-33.0/24                  │    │
│  │  ┌──────────────────────┐  ┌──────────────────────┐               │    │
│  │  │ PostgreSQL 16        │  │ TimescaleDB           │               │    │
│  │  │ + pgvector           │  │ (metrics/time-series) │               │    │
│  │  │ Multi-AZ RDS         │  │                       │               │    │
│  │  └──────────────────────┘  └──────────────────────┘               │    │
│  └────────────────────────────────────────────────────────────────────┘    │
│                                                                             │
│  ┌────────────────────────────────────────────────────────────────────┐    │
│  │  TIER 6 — OBSERVABILITY SUBNET (PRIVATE)  10.0.41-43.0/24         │    │
│  │  ┌───────────┐ ┌────────┐ ┌──────┐ ┌──────────┐ ┌─────────────┐  │    │
│  │  │Prometheus │ │Grafana │ │Loki  │ │Jaeger    │ │Alertmanager │  │    │
│  │  │(federat.) │ │        │ │      │ │          │ │             │  │    │
│  │  └───────────┘ └────────┘ └──────┘ └──────────┘ └─────────────┘  │    │
│  └────────────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 2.2 Security Group (Firewall) Rules

```
┌────────────────────┬───────────────────────┬──────────────────────────────────┐
│ Source              │ Destination           │ Allowed Ports / Protocol         │
├────────────────────┼───────────────────────┼──────────────────────────────────┤
│ Internet           │ ALB (DMZ)             │ 443/tcp only                     │
│ ALB (DMZ)          │ App Subnet            │ 8080/tcp (API pods)              │
│ App Subnet         │ ML/AI Subnet          │ 11434/tcp (Ollama), 8000/tcp     │
│ App Subnet         │ Cache Subnet          │ 6379/tcp (Redis)                 │
│ App Subnet         │ Data Subnet           │ 5432/tcp (Postgres)              │
│ ML/AI Subnet       │ Cache Subnet          │ 6379/tcp (model cache)           │
│ ML/AI Subnet       │ Data Subnet           │ 5432/tcp (embedding writes)      │
│ Workers (App Sub)  │ Cache Subnet          │ 6379/tcp (task streams)          │
│ Workers (App Sub)  │ Data Subnet           │ 5432/tcp                         │
│ Obs Subnet         │ App Subnet            │ 8080/tcp (metrics scrape)        │
│ App Subnet         │ Obs Subnet            │ 3100/tcp (Loki push)             │
│ NOTHING            │ Data Subnet → Internet│ DENIED (no egress)               │
│ NOTHING            │ Cache → Internet      │ DENIED (no egress)               │
│ NAT GW only        │ App → Internet        │ 443/tcp (OpenAI, Shopify, etc.)  │
└────────────────────┴───────────────────────┴──────────────────────────────────┘
```

### 2.3 Blast-Radius Isolation

```
BLAST RADIUS STRATEGY
═════════════════════

1. ACCOUNT-LEVEL ISOLATION (AWS Organizations / GCP Folders)
   ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
   │ Prod Account     │  │ Staging Account  │  │ Security/Audit  │
   │ (workloads)      │  │ (pre-prod)       │  │ Account         │
   └─────────────────┘  └─────────────────┘  └─────────────────┘

2. SUBNET-LEVEL ISOLATION (per diagram above)
   - Data subnet has NO internet route table entry
   - Cache subnet has NO internet route table entry
   - ML/AI subnet: egress only for model downloads via NAT (deny-by-default ACL)

3. KUBERNETES NAMESPACE ISOLATION
   ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
   │ ns: api      │ │ ns: workers  │ │ ns: ml       │ │ ns: obs      │
   │ NetworkPolicy│ │ NetworkPolicy│ │ NetworkPolicy│ │ NetworkPolicy│
   │ deny-all +   │ │ deny-all +   │ │ deny-all +   │ │ deny-all +   │
   │ explicit     │ │ explicit     │ │ explicit     │ │ explicit     │
   │ ingress only │ │ redis,db     │ │ redis,db     │ │ scrape only  │
   └──────────────┘ └──────────────┘ └──────────────┘ └──────────────┘

4. DATABASE ISOLATION
   - Separate RDS instance for transactional data (Postgres+pgvector)
   - Separate TimescaleDB for time-series / observability metrics
   - Separate Redis cluster for cache vs. task queues (logical DBs or clusters)
   - Encrypted at rest (AES-256), in transit (TLS 1.3)
   - Secrets in AWS Secrets Manager (already in terraform/main.tf)
```

---

## 3. ASCII Architecture Diagrams

### 3.1 Full Production Architecture

```
                                    ┌──────────────┐
                                    │   INTERNET   │
                                    └──────┬───────┘
                                           │
                                    ┌──────┴───────┐
                                    │  CloudFront  │ ← static frontend (Vite/React)
                                    │     CDN      │   HTML/JS/CSS from S3 bucket
                                    └──────┬───────┘
                                           │
                              ┌────────────┴────────────┐
                              │  AWS WAF + Shield Adv   │ ← L7 DDoS, OWASP rulesets,
                              │  (or Cloudflare)        │   rate_limit.py rules synced
                              └────────────┬────────────┘
                                           │
════════════════════════════ DMZ ═══════════╪══════════════════════════════════
                                           │
                              ┌────────────┴────────────┐
                              │   Application Load      │ ← TLS termination
                              │   Balancer (ALB/NLB)    │   Health: /healthz
                              │   + NGINX Ingress       │   Sticky sessions for WS
                              └──┬──────────┬────────┬──┘
                                 │          │        │
════════════════════ APP PRIVATE SUBNET ════╪════════╪════════════════════════
                                 │          │        │
                    ┌────────────┴──┐  ┌────┴─────┐  │   ┌─────────────────┐
                    │  FastAPI API  │  │ FastAPI  │  │   │  Chat/WS Stream │
                    │  Pod (HPA)   │  │ API Pod  │  │   │  Pods (HPA)     │
                    │              │  │ (HPA)    │  │   │ chat_stream.py  │
                    │ routers/*    │  │          │  │   │ voice.py        │
                    │ security/*   │  │          │  │   └────────┬────────┘
                    │ email_sec*   │  │          │  │            │
                    └──┬───┬───┬──┘  └──┬───┬───┘  │            │
                       │   │   │        │   │      │            │
         ┌─────────────┤   │   │        │   │      │            │
         │             │   │   │        │   │      │            │
    ┌────┴────────┐    │   │   │   ┌────┴───┴──────┴───┐   ┌───┴──────────────┐
    │ Sync Worker │    │   │   │   │  Background Task   │   │ Email Workers    │
    │ (1-3 pods)  │    │   │   │   │  Runner (HPA)      │   │ email_connector  │
    │ shopify,csv │    │   │   │   │  rq_queue.py       │   │ crowdstrike_poll │
    │ erp/edi     │    │   │   │   │  celery_app.py     │   │ (1-2 pods)       │
    └──┬──────────┘    │   │   │   └──┬─────────────────┘   └──┬───────────────┘
       │               │   │   │      │                         │
═══════╪═══════════════╪═══╪═══╪══════╪═════════════════════════╪════════════════
       │               │   │   │      │     ML/AI SUBNET        │
       │          ┌────┴───┴───┴──────┴─────────────────────────┴──┐
       │          │                                                 │
       │    ┌─────┴──────┐ ┌──────────────┐ ┌──────────┐ ┌────────┴───────┐
       │    │ Ollama     │ │ CV Pipeline  │ │ Voice    │ │ Embedding      │
       │    │ Vision     │ │ YOLO + OCR   │ │ ASR/TTS  │ │ Pipeline       │
       │    │ LLM Pods   │ │ Tesseract    │ │ Whisper? │ │ sentence-xfmr  │
       │    │ (GPU)      │ │ (GPU)        │ │ (GPU)    │ │ (CPU or GPU)   │
       │    │            │ │ roi_detector │ │          │ │                │
       │    └──────┬─────┘ └──────┬───────┘ └────┬─────┘ └───────┬────────┘
       │           │              │              │               │
═══════╪═══════════╪══════════════╪══════════════╪═══════════════╪════════════
       │           │              │    CACHE SUBNET              │
       │    ┌──────┴──────────────┴──────────────┴───────────────┴──┐
       │    │                                                       │
       │    │  ┌──────────────────────┐  ┌────────────────────────┐ │
       │    │  │ Redis Cluster        │  │ Semantic Cache          │ │
       │    │  │ (ElastiCache)        │  │ (hot LLM responses,    │ │
       │    │  │ • Task streams       │  │  embedding cache)       │ │
       │    │  │ • Session state      │  │                         │ │
       │    │  │ • Rate limit counters│  │                         │ │
       │    │  │ • Feature flags cache│  │                         │ │
       │    │  └──────────────────────┘  └────────────────────────┘ │
       │    └──────────────────────┬────────────────────────────────┘
       │                           │
═══════╪═══════════════════════════╪══════════════════════════════════════════
       │                           │    DATA SUBNET (NO INTERNET)
       │    ┌──────────────────────┴───────────────────────────────────┐
       │    │                                                          │
       │    │  ┌────────────────────────┐  ┌─────────────────────────┐ │
       │    │  │ PostgreSQL 16          │  │ TimescaleDB              │ │
       │    │  │ + pgvector extension   │  │ (time-series metrics,    │ │
       │    │  │ • Products, orders     │  │  agent decision logs,    │ │
       │    │  │ • Users, tenants       │  │  drift metrics)          │ │
       │    │  │ • Embeddings           │  │                          │ │
       │    │  │ • Audit chain          │  │                          │ │
       │    │  │ • Email security       │  │                          │ │
       │    │  │ Multi-AZ, encrypted    │  │ Multi-AZ, encrypted      │ │
       │    │  └────────────────────────┘  └──────────────────────────┘ │
       │    └──────────────────────────────────────────────────────────┘
       │
═══════╪════════════════════════════════════════════════════════════════════
       │    OBSERVABILITY SUBNET
       │    ┌──────────────────────────────────────────────────────────┐
       │    │  ┌───────────┐ ┌────────┐ ┌──────┐ ┌──────┐ ┌────────┐ │
       │    │  │Prometheus │ │Grafana │ │Loki  │ │Jaeger│ │Alert-  │ │
       │    │  │(federated)│ │        │ │+Prom-│ │      │ │manager │ │
       └────┤  │           │ │        │ │tail  │ │      │ │(HA)    │ │
            │  └───────────┘ └────────┘ └──────┘ └──────┘ └────────┘ │
            └──────────────────────────────────────────────────────────┘

EXTERNAL SERVICES (via NAT Gateway egress-only):
  ┌───────────┐ ┌───────────┐ ┌──────────┐ ┌───────────┐ ┌──────────┐
  │ OpenAI    │ │ Shopify   │ │ SendGrid │ │ CrowdStrike│ │ Splunk   │
  │ API       │ │ API       │ │ Email    │ │ Falcon API │ │ HEC      │
  └───────────┘ └───────────┘ └──────────┘ └───────────┘ └──────────┘
```

### 3.2 Kubernetes Cluster Layout

```
                    EKS CLUSTER (private endpoint)
┌──────────────────────────────────────────────────────────────────────┐
│                                                                      │
│  NAMESPACE: shopsquire-api                                           │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │  Deployment: api          Deployment: chat-stream              │  │
│  │  replicas: 2-50 (HPA)    replicas: 2-20 (HPA)                 │  │
│  │  nodeSelector:            nodeSelector:                         │  │
│  │    pool: cpu-general      pool: cpu-general                    │  │
│  │  resources:               resources:                            │  │
│  │    req: 250m/512Mi        req: 250m/512Mi                      │  │
│  │    lim: 1000m/1Gi         lim: 1000m/1Gi                      │  │
│  │                                                                │  │
│  │  Service: api-svc (ClusterIP:8080)                             │  │
│  │  Ingress: api.shopsquire.io → api-svc                         │  │
│  └────────────────────────────────────────────────────────────────┘  │
│                                                                      │
│  NAMESPACE: shopsquire-workers                                       │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │  Deployment: sync-worker     replicas: 1-3                     │  │
│  │  Deployment: task-runner     replicas: 2-10 (HPA/KEDA)        │  │
│  │  Deployment: email-worker    replicas: 1-5                     │  │
│  │  Deployment: crowdstrike     replicas: 1 (singleton)           │  │
│  │  CronJob: kev-cron           schedule: daily                   │  │
│  │  CronJob: db-backup          schedule: 0 2 * * *              │  │
│  │  nodeSelector: pool: cpu-general                               │  │
│  └────────────────────────────────────────────────────────────────┘  │
│                                                                      │
│  NAMESPACE: shopsquire-ml                                            │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │  Deployment: ollama-vision   replicas: 1-4                     │  │
│  │    nodeSelector: pool: gpu-inference                           │  │
│  │    resources:                                                  │  │
│  │      req:  2000m CPU / 4Gi RAM / 1 nvidia.com/gpu             │  │
│  │      lim:  4000m CPU / 8Gi RAM / 1 nvidia.com/gpu             │  │
│  │    tolerations: nvidia.com/gpu=present:NoSchedule              │  │
│  │                                                                │  │
│  │  Deployment: cv-pipeline     replicas: 1-3                     │  │
│  │    nodeSelector: pool: gpu-inference                           │  │
│  │    resources:                                                  │  │
│  │      req:  1000m CPU / 2Gi RAM / 1 nvidia.com/gpu             │  │
│  │      lim:  2000m CPU / 4Gi RAM / 1 nvidia.com/gpu             │  │
│  │                                                                │  │
│  │  Deployment: embedding-svc   replicas: 1-4                     │  │
│  │    nodeSelector: pool: cpu-general (or gpu-inference)          │  │
│  │                                                                │  │
│  │  Deployment: voice-asr-tts   replicas: 0-3 (scale-to-zero)    │  │
│  │    nodeSelector: pool: gpu-inference                           │  │
│  └────────────────────────────────────────────────────────────────┘  │
│                                                                      │
│  NAMESPACE: shopsquire-obs                                           │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │  StatefulSet: prometheus     replicas: 2 (HA/Thanos)          │  │
│  │  Deployment:  grafana        replicas: 1                       │  │
│  │  StatefulSet: loki           replicas: 1-3                     │  │
│  │  DaemonSet:   promtail       (every node)                     │  │
│  │  Deployment:  jaeger-coll    replicas: 1-2                     │  │
│  │  Deployment:  alertmanager   replicas: 2 (mesh HA)            │  │
│  │  nodeSelector: pool: cpu-general                               │  │
│  └────────────────────────────────────────────────────────────────┘  │
│                                                                      │
│  NODE POOLS                                                          │
│  ┌─────────────────────┐  ┌──────────────────────────────────────┐  │
│  │ cpu-general          │  │ gpu-inference                        │  │
│  │ t3.xlarge / m6i.xl   │  │ g5.xlarge (1x A10G, 24GB VRAM)     │  │
│  │ min: 3, max: 30      │  │ min: 1, max: 8                      │  │
│  │ Spot + On-Demand mix  │  │ On-Demand (model loading latency)   │  │
│  │ AZ spread: 3          │  │ AZ spread: 2                        │  │
│  └─────────────────────┘  └──────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 4. User Flow Walkthrough

### 4.1 Storefront User (Buy-Side)

```
    CUSTOMER                                    SHOPSQUIRE
    ────────                                    ──────────

    ┌─────────┐   HTTPS/443   ┌──────────┐   ┌──────────┐   ┌──────────┐
    │ Browser │──────────────►│CloudFront│──►│   ALB    │──►│ API Pod  │
    │         │  GET /ui/     │  (CDN)   │   │(TLS term)│   │ ui.py    │
    └─────────┘  static HTML  └──────────┘   └──────────┘   └────┬─────┘
                                                                   │
    ┌──────────────────────────────────────────────────────────────┘
    │
    ▼  POST /api/v1/recommend  {"query": "65-inch 4K TV under $1500"}
    ┌──────────┐     ┌──────────────┐     ┌────────────┐     ┌──────────┐
    │ API Pod  │────►│ LLM Router   │────►│ Embedding  │────►│ pgvector │
    │recommend │     │ (llm_router) │     │ Pipeline   │     │ ANN index│
    │ .py      │     └──────────────┘     └────────────┘     └────┬─────┘
    └────┬─────┘                                                   │
         │  ◄─── ranked product IDs ──────────────────────────────┘
         │
         ▼  Enrich from Redis cache (product cards, inventory counts)
    ┌──────────┐     ┌──────────┐
    │ Redis    │────►│ API Pod  │────► JSON response → browser renders
    │ cache    │     │ serialize│
    └──────────┘     └──────────┘

    LATENCY BUDGET: CDN hit 10ms + ALB 2ms + API 30ms + LLM 80ms
                    + embedding 20ms + pgvector 15ms + Redis 2ms
                    = ~160ms P95 target
```

### 4.2 Agentic Chat Flow

```
    MERCHANT                                      SHOPSQUIRE
    ────────                                      ──────────

    ┌─────────┐  WSS://  ┌──────────┐   ┌────────────────┐
    │ Browser │─────────►│   ALB    │──►│ chat_stream.py │ (WebSocket pod)
    │ Chat UI │  upgrade │(sticky)  │   │                │
    └─────────┘          └──────────┘   └───────┬────────┘
                                                │
                            ┌───────────────────┘
                            ▼
                   ┌─────────────────┐  Agent orchestrator
                   │  orchestrator.py │  determines tool calls
                   │  agent_dag_*     │  policy_evaluator.py
                   └────────┬────────┘
                            │
        ┌───────────┬───────┼───────────┬──────────────┐
        ▼           ▼       ▼           ▼              ▼
   ┌─────────┐ ┌────────┐ ┌─────────┐ ┌──────────┐ ┌────────────┐
   │ LLM     │ │ CV     │ │ Semantic│ │ Decision │ │ Inventory  │
   │ Provider│ │Pipeline│ │ Search  │ │ Gate     │ │ Rules      │
   │(OpenAI/ │ │(YOLO)  │ │(RAG)   │ │(ml_dec)  │ │            │
   │ Ollama) │ │        │ │        │ │          │ │            │
   └────┬────┘ └────┬───┘ └────┬───┘ └────┬─────┘ └─────┬──────┘
        │           │          │          │              │
        ▼           ▼          ▼          ▼              ▼
   ┌────────────────────────────────────────────────────────────┐
   │              Redis (session state, semantic cache)          │
   │              PostgreSQL (audit_chain, decisions, products)  │
   └────────────────────────────────────────────────────────────┘
        │
        ▼  streamed token-by-token back via WebSocket
   ┌─────────┐
   │ Browser │  displays agent response in real-time
   └─────────┘
```

### 4.3 Email Security Scan Flow

```
    INBOUND EMAIL                                 SHOPSQUIRE
    ─────────────                                 ──────────

    ┌──────────┐   Webhook/Poll   ┌───────────────────┐
    │ M365 /   │─────────────────►│ ingest_m365.py /  │ (Email Worker pod)
    │ Gmail    │                  │ ingest_gmail.py   │
    └──────────┘                  └────────┬──────────┘
                                           │
                            ┌──────────────┘
                            ▼
                   ┌─────────────────────────┐
                   │ email_security_rules.py  │ ← YOUR CURRENT FILE
                   │ extract_indicators()     │
                   │ • SPF/DKIM/DMARC/ARC    │
                   │ • BEC pattern detection  │
                   │ • Homoglyph detection    │
                   │ • IOC extraction         │
                   │ • Prompt injection guard │
                   │ • LOLBin detection       │
                   └────────┬────────────────┘
                            │
        ┌───────────┬───────┼───────────┬────────────────┐
        ▼           ▼       ▼           ▼                ▼
   ┌─────────┐ ┌────────┐ ┌─────────┐ ┌──────────┐ ┌─────────────┐
   │ CV/OCR  │ │ YARA   │ │Phishing │ │ MISP     │ │ email_      │
   │ attach- │ │ scan   │ │page det │ │ feed     │ │ security_   │
   │ ment    │ │        │ │         │ │ lookup   │ │ verdict.py  │
   │ parse   │ │        │ │         │ │          │ │ (score +    │
   │ (GPU)   │ │ (CPU)  │ │ (CPU)   │ │ (CPU)    │ │  action)    │
   └─────────┘ └────────┘ └─────────┘ └──────────┘ └──────┬──────┘
                                                            │
                                                            ▼
                                                   ┌──────────────┐
                                                   │ Playbook     │
                                                   │ Engine       │
                                                   │ quarantine / │
                                                   │ escalate /   │
                                                   │ allow        │
                                                   └──────────────┘
```

---

## 5. Scaling Matrix

### 5.1 Concurrent Users: 100 / 1,000 / 5,000 / 10,000 / 25,000

```
┌─────────────────────┬──────────┬──────────┬──────────┬───────────┬───────────┐
│ Component           │ 100 CCU  │ 1K CCU   │ 5K CCU   │ 10K CCU   │ 25K CCU   │
├─────────────────────┼──────────┼──────────┼──────────┼───────────┼───────────┤
│                     │          │          │          │           │           │
│ API Pods            │ 2        │ 4        │ 12       │ 24        │ 50+       │
│ API CPU total       │ 2 vCPU   │ 4 vCPU   │ 12 vCPU  │ 24 vCPU   │ 50 vCPU   │
│ Chat/WS Pods        │ 1        │ 2        │ 6        │ 12        │ 25        │
│                     │          │          │          │           │           │
│ CPU Node Pool       │ 2 nodes  │ 3 nodes  │ 6 nodes  │ 12 nodes  │ 25 nodes  │
│   Instance type     │ t3.large │ m6i.xl   │ m6i.xl   │ m6i.2xl   │ m6i.2xl   │
│   (4/8/16 vCPU)     │ (2 vCPU) │ (4 vCPU) │ (4 vCPU) │ (8 vCPU)  │ (8 vCPU)  │
│                     │          │          │          │           │           │
│ GPU Node Pool       │ 1 node   │ 1 node   │ 2 nodes  │ 3 nodes   │ 5 nodes   │
│   Instance type     │ g5.xl    │ g5.xl    │ g5.xl    │ g5.2xl    │ g5.2xl    │
│   GPUs total        │ 1 A10G   │ 1 A10G   │ 2 A10G   │ 3 A10G    │ 5 A10G    │
│                     │          │          │          │           │           │
│ Sync Workers        │ 1        │ 1        │ 2        │ 3         │ 3         │
│ Task Runners        │ 1        │ 2        │ 4        │ 8         │ 15        │
│ Email Workers       │ 1        │ 1        │ 2        │ 3         │ 5         │
│                     │          │          │          │           │           │
│ Ollama Pods (GPU)   │ 1        │ 1        │ 2        │ 3         │ 4         │
│ CV/YOLO Pods (GPU)  │ 1        │ 1        │ 1        │ 2         │ 3         │
│ Embedding Pods      │ 1        │ 1        │ 2        │ 4         │ 6         │
│ Voice Pods (GPU)    │ 0        │ 0-1      │ 1        │ 2         │ 3         │
│                     │          │          │          │           │           │
│ PostgreSQL          │ db.t3.   │ db.r6g.  │ db.r6g.  │ db.r6g.   │ db.r6g.   │
│                     │ medium   │ large    │ xlarge   │ 2xlarge   │ 4xlarge   │
│   Read Replicas     │ 0        │ 1        │ 2        │ 3         │ 5         │
│   Storage           │ 20 GB    │ 50 GB    │ 200 GB   │ 500 GB    │ 1 TB      │
│                     │          │          │          │           │           │
│ Redis               │ cache.t3 │ cache.r6g│ cache.r6g│ cache.r6g │ cache.r6g │
│                     │ .micro   │ .large   │ .xlarge  │ .xlarge   │ .2xlarge  │
│   Cluster mode      │ No       │ No       │ Yes(3)   │ Yes(3)    │ Yes(6)    │
│                     │          │          │          │           │           │
│ TimescaleDB         │ shared   │ db.t3.md │ db.r6g.lg│ db.r6g.xl │ db.r6g.2xl│
│                     │          │          │          │           │           │
│ ALB                 │ 1        │ 1        │ 1        │ 1         │ 2 (x-reg) │
│                     │          │          │          │           │           │
│ Est. Monthly Cost   │ ~$800    │ ~$2,500  │ ~$8,000  │ ~$18,000  │ ~$45,000  │
│ (excl. OpenAI API)  │          │          │          │           │           │
└─────────────────────┴──────────┴──────────┴──────────┴───────────┴───────────┘

Notes:
- CCU = Concurrent Connected Users (not RPM; assume 10 req/sec per 100 CCU avg)
- OpenAI API costs are VARIABLE (~$0.01-0.06 per agent turn); budget separately
- Spot instances for CPU pool can reduce cost by 50-70%
- GPU spot is volatile; use On-Demand + Savings Plans for GPU
```

### 5.2 Scaling Topology Evolution

```
100 CCU — "STARTUP"                    1,000 CCU — "GROWTH"
═══════════════════                    ══════════════════════

 1 AZ is acceptable                    Multi-AZ required
 Single DB, no replicas               1 read replica
 Spot-only CPU pool                   Spot + OD CPU mix
 1 GPU node (shared Ollama+CV)        1 GPU node (dedicated pods)
 Redis standalone                     Redis with replica
 No CDN needed                        CDN for static + edge cache
 HPA only                             HPA + PDB + node auto-scaler


5,000 CCU — "SCALE-UP"                10,000 CCU — "ENTERPRISE"
════════════════════════               ══════════════════════════

 3 AZ spread mandatory                 3 AZ + consider multi-region warm
 2 read replicas + pgBouncer           3 read replicas + pgBouncer
 Redis cluster mode (3 shards)         Redis cluster (3 shards, 6 nodes)
 2 GPU nodes (Ollama separated)        3 GPU nodes, model sharding
 KEDA for queue-based autoscaling      KEDA + custom metrics + VPA
 Prometheus federation                 Thanos for long-term metrics
 Loki microservices mode               Loki + S3 chunk store
 Consider read-through cache layer     Cache-aside + write-behind


25,000 CCU — "HYPERSCALE"
══════════════════════════

 Multi-region active-active (or active-passive failover)
 5 read replicas + Citus/pgBouncer connection pooling
 Redis cluster (6 shards, 12+ nodes)
 5 GPU nodes, consider inference-as-a-service (SageMaker/Triton)
 Cell-based architecture consideration (tenant sharding)
 Global load balancer (Route 53 latency-based)
 S3 + CloudFront for all static + media
 Dedicated observability cluster (separate EKS)
 Cost optimization: Reserved Instances / Savings Plans mandatory
```

---

## 6. Horizontal Auto-Scaling & K8s Pod Strategy

### 6.1 HPA Definitions

```yaml
# API PODS — scale on CPU and custom RPS metric
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: api-hpa
  namespace: shopsquire-api
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: api
  minReplicas: 2
  maxReplicas: 50
  behavior:
    scaleUp:
      stabilizationWindowSeconds: 30     # react fast
      policies:
      - type: Pods
        value: 4
        periodSeconds: 60               # add up to 4 pods/min
    scaleDown:
      stabilizationWindowSeconds: 300    # cool down slow
      policies:
      - type: Percent
        value: 25
        periodSeconds: 120
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
  - type: Pods
    pods:
      metric:
        name: http_requests_per_second   # Prometheus adapter
      target:
        type: AverageValue
        averageValue: "50"               # 50 RPS per pod
```

```yaml
# TASK RUNNER — scale on Redis stream lag via KEDA
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: task-runner-scaledobject
  namespace: shopsquire-workers
spec:
  scaleTargetRef:
    name: task-runner
  minReplicaCount: 1
  maxReplicaCount: 15
  triggers:
  - type: redis-streams
    metadata:
      address: redis-cluster.cache-subnet.svc:6379
      stream: shopsquire:tasks
      consumerGroup: task-workers
      lagCount: "10"        # scale up when >10 pending messages
```

```yaml
# GPU PODS — scale on inference queue depth (VPA preferred, HPA as backup)
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: ollama-hpa
  namespace: shopsquire-ml
spec:
  scaleTargetRef:
    name: ollama-vision
  minReplicas: 1
  maxReplicas: 4
  metrics:
  - type: Pods
    pods:
      metric:
        name: inference_queue_depth
      target:
        type: AverageValue
        averageValue: "5"
```

### 6.2 Pod Disruption Budgets

```
┌─────────────────────┬───────────┬────────────────────────────┐
│ Deployment          │ PDB       │ Rationale                  │
├─────────────────────┼───────────┼────────────────────────────┤
│ api                 │ minAvail 2│ Always serve traffic       │
│ chat-stream         │ minAvail 1│ WS connections preserved   │
│ sync-worker         │ maxUnav 1 │ Can tolerate brief gap     │
│ task-runner         │ minAvail 1│ Don't lose all consumers   │
│ ollama-vision       │ maxUnav 1 │ GPU pods are expensive     │
│ prometheus          │ minAvail 1│ Metrics collection         │
│ alertmanager        │ minAvail 1│ Alert routing              │
└─────────────────────┴───────────┴────────────────────────────┘
```

### 6.3 Cluster Auto-Scaler / Karpenter

```
CPU POOL (Karpenter Provisioner):
  instanceTypes: [m6i.large, m6i.xlarge, m6i.2xlarge, m5.xlarge]
  capacityType: ["spot", "on-demand"]        # 70/30 mix
  consolidation: enabled                     # bin-pack and remove underused nodes
  ttlSecondsAfterEmpty: 60
  limits:
    cpu: "200"                               # max 200 vCPU total

GPU POOL (Karpenter Provisioner):
  instanceTypes: [g5.xlarge, g5.2xlarge]
  capacityType: ["on-demand"]                # GPU spot is too volatile
  taints:
    - key: nvidia.com/gpu
      value: present
      effect: NoSchedule
  limits:
    gpu: "8"                                 # max 8 GPUs
```

---

## 7. GPU Placement Strategy

### 7.1 Where GPU Is Required vs. Optional vs. Not Needed

```
┌────────────────────────┬──────────┬──────────────────────────────────────────┐
│ Workload               │ GPU?     │ Rationale                                │
├────────────────────────┼──────────┼──────────────────────────────────────────┤
│ Ollama Vision LLM      │ YES      │ VRAM-bound model inference; 7B+ params   │
│                        │          │ need ≥8GB VRAM. A10G (24GB) ideal.       │
│                        │          │                                          │
│ CV Pipeline (YOLO v8)  │ YES      │ Real-time object detection; YOLOv8s/n    │
│                        │          │ on GPU: 5-15ms vs 200ms+ on CPU.         │
│                        │          │ Tesseract OCR is CPU-only (no GPU).      │
│                        │          │                                          │
│ Voice ASR (Whisper)    │ YES      │ Real-time transcription needs GPU for    │
│                        │          │ <500ms latency. Can use whisper.cpp on   │
│                        │          │ CPU for non-realtime batch.              │
│                        │          │                                          │
│ Voice TTS              │ OPTIONAL │ Depends on model; Piper TTS is CPU-ok.  │
│                        │          │ Neural TTS (e.g. XTTS) needs GPU.       │
│                        │          │                                          │
│ Embedding Pipeline     │ OPTIONAL │ sentence-transformers on GPU: 2-5ms.    │
│ (sentence-transformers)│ (PREFER) │ On CPU: 20-50ms. At scale, GPU wins.    │
│                        │          │ If using OpenAI API embeddings: CPU.     │
│                        │          │                                          │
│ GNN Fraud Detector     │ OPTIONAL │ gnn_fraud_detector.py — small graph     │
│                        │          │ models can run CPU; GPU for >1M edges.  │
│                        │          │                                          │
│ Adversarial Image Det  │ OPTIONAL │ adversarial_image_detector.py —         │
│                        │          │ can share CV GPU pod or run CPU.        │
│                        │          │                                          │
│ Diffusion Detection    │ NO (CPU) │ diffusion_detection.py — statistical    │
│                        │          │ checks, not inference. CPU fine.        │
│                        │          │                                          │
│ FastAPI API            │ NO       │ I/O bound, not compute bound.           │
│ Redis                  │ NO**     │ See discussion below.                   │
│ PostgreSQL             │ NO       │ Disk + memory bound, not GPU bound.     │
│ All Security Rules     │ NO       │ Regex + heuristics, CPU-bound.          │
│ Sync/Email Workers     │ NO       │ I/O bound (API calls, DB writes).       │
│ Observability Stack    │ NO       │ Prometheus/Grafana/Loki are CPU/disk.   │
└────────────────────────┴──────────┴──────────────────────────────────────────┘

** GPU at Redis/Cache — see section 7.2
```

### 7.2 GPU for Redis / Cache Layer — Analysis

Your instinct about GPU acceleration at the cache layer is interesting. Here's the honest assessment:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ QUESTION: Should Redis / Cache get a GPU for faster agent interactions?     │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│ SHORT ANSWER: No — but the SEMANTIC CACHE should be GPU-adjacent.          │
│                                                                             │
│ WHY NOT REDIS ITSELF:                                                       │
│ • Redis is memory-bound, not compute-bound. Operations are O(1) or O(logN)│
│ • Redis latency is <1ms for most ops. GPU adds PCIe transfer overhead.    │
│ • No production-grade GPU-accelerated Redis exists.                        │
│ • SmartNICs (NVIDIA BlueField DPU) can accelerate network I/O for Redis   │
│   but only at extreme scale (>1M ops/sec); your 25K CCU won't hit that.   │
│                                                                             │
│ WHERE GPU HELPS AGENT INTERACTIONS:                                         │
│                                                                             │
│ 1. SEMANTIC CACHE (services/semantic_cache.py):                            │
│    Instead of re-running LLM inference for similar queries, the semantic   │
│    cache computes embedding similarity. GPU-accelerated embedding          │
│    comparison (cosine distance over 768-1536 dim vectors) is 10-50x       │
│    faster on GPU than CPU at batch sizes >32.                              │
│                                                                             │
│ 2. ARCHITECTURE RECOMMENDATION:                                            │
│    ┌────────────┐    ┌───────────────────────┐    ┌──────────────┐        │
│    │ API Pod    │───►│ Semantic Cache Pod     │───►│ Ollama LLM   │        │
│    │            │    │ (GPU: embedding check) │    │ (GPU: if     │        │
│    │            │    │ Cache HIT → Redis      │    │  cache miss) │        │
│    │            │    │ Cache MISS → LLM call  │    │              │        │
│    └────────────┘    └───────────────────────┘    └──────────────┘        │
│                                                                             │
│    • Place semantic cache pod ON SAME GPU NODE as Ollama/Embedding         │
│    • Share the GPU: embedding lookup uses <5% GPU, LLM uses 80-95%        │
│    • Redis stays CPU (stores serialized cache entries, session state)      │
│                                                                             │
│ 3. AT 25K CCU: Consider NVIDIA Triton Inference Server or vLLM with       │
│    continuous batching — this is where GPU utilization matters most.       │
│                                                                             │
│ BOTTOM LINE:                                                                │
│ Put GPU budget on LLM inference + semantic cache co-located embedding,    │
│ NOT on Redis itself. You get 10-100x more bang per GPU dollar.            │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 7.3 Recommended GPU Allocation by Scale

```
┌──────────┬──────────────────────────────────────────────────────────────────┐
│ Scale    │ GPU Allocation                                                   │
├──────────┼──────────────────────────────────────────────────────────────────┤
│ 100 CCU  │ 1x g5.xlarge (24GB A10G)                                       │
│          │   • Ollama 7B model (~6GB VRAM)                                 │
│          │   • YOLO v8n/s (~1GB VRAM)                                      │
│          │   • Embedding model (~1GB VRAM)                                 │
│          │   • All share one GPU via time-slicing (MPS)                    │
│          │                                                                  │
│ 1K CCU   │ 1x g5.xlarge                                                    │
│          │   Same as above; GPU utilization ~40-60%                         │
│          │                                                                  │
│ 5K CCU   │ 2x g5.xlarge                                                    │
│          │   • GPU-1: Ollama + Semantic Cache embedding                    │
│          │   • GPU-2: CV pipeline + Embedding service                      │
│          │   OR: Switch to API-based LLM (OpenAI) + 1 GPU for CV          │
│          │                                                                  │
│ 10K CCU  │ 3x g5.xlarge (or 2x g5.2xlarge)                                │
│          │   • GPU-1,2: Ollama replicas (load balanced)                    │
│          │   • GPU-3: CV + Embedding                                       │
│          │   Consider: vLLM or Triton for batched inference                │
│          │                                                                  │
│ 25K CCU  │ 5x g5.xlarge + consider p4d/p5 for large models                │
│          │   OR: Hybrid — use SageMaker endpoints for LLM (pay-per-token) │
│          │   • 2-3 GPUs: self-hosted inference (low-latency tier)          │
│          │   • 2 GPUs: CV + Voice                                          │
│          │   • SageMaker burst: overflow LLM traffic                       │
└──────────┴──────────────────────────────────────────────────────────────────┘
```

---

## 8. Hybrid Multi-Cloud & Colocation Strategy

### 8.1 Recommended Topology: Hybrid Public Cloud + Colo

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                         HYBRID ARCHITECTURE                                      │
│                                                                                  │
│   ┌──────────────────────────────────────┐     ┌──────────────────────────────┐ │
│   │      PUBLIC CLOUD (AWS/GCP/Azure)    │     │  COLOCATION DATA CENTER      │ │
│   │      Region: Closest to users        │     │  (data sovereignty zone)     │ │
│   │                                      │     │                              │ │
│   │  ┌──────────────────────────────┐    │     │  ┌────────────────────────┐  │ │
│   │  │ DMZ                          │    │     │  │ PostgreSQL Primary     │  │ │
│   │  │ • CloudFront CDN             │    │     │  │ + pgvector             │  │ │
│   │  │ • WAF / Shield               │    │     │  │ • All PII / PCI data  │  │ │
│   │  │ • ALB / Ingress              │    │     │  │ • Audit chain         │  │ │
│   │  └──────────────────────────────┘    │     │  │ • Tenant configs      │  │ │
│   │                                      │     │  └────────────────────────┘  │ │
│   │  ┌──────────────────────────────┐    │     │                              │ │
│   │  │ App Tier (EKS)               │    │     │  ┌────────────────────────┐  │ │
│   │  │ • API pods                   │════╬═════╬══│ TimescaleDB            │  │ │
│   │  │ • Chat/WS pods              │ VPN│     │  │ • Decision logs       │  │ │
│   │  │ • Workers                    │ /  │     │  │ • Security events     │  │ │
│   │  │ • Email security pipeline   │ DX │     │  └────────────────────────┘  │ │
│   │  └──────────────────────────────┘    │     │                              │ │
│   │                                      │     │  ┌────────────────────────┐  │ │
│   │  ┌──────────────────────────────┐    │     │  │ Redis (Sentinel HA)   │  │ │
│   │  │ ML/AI Tier (GPU nodes)       │    │     │  │ • Session state       │  │ │
│   │  │ • Ollama                     │    │     │  │ • Cache hot data      │  │ │
│   │  │ • CV pipeline                │    │     │  │                        │  │ │
│   │  │ • Embedding                  │    │     │  └────────────────────────┘  │ │
│   │  └──────────────────────────────┘    │     │                              │ │
│   │                                      │     │  ┌────────────────────────┐  │ │
│   │  ┌──────────────────────────────┐    │     │  │ HSM / Key Vault       │  │ │
│   │  │ Observability                │    │     │  │ • Encryption keys     │  │ │
│   │  │ • Cloud Prometheus (write)   │    │     │  │ • mTLS certs          │  │ │
│   │  │ • Grafana Cloud (optional)   │    │     │  │ • Secrets at rest     │  │ │
│   │  └──────────────────────────────┘    │     │  └────────────────────────┘  │ │
│   │                                      │     │                              │ │
│   └──────────────────────────────────────┘     └──────────────────────────────┘ │
│                         │                                    │                    │
│                         │          VPN / Direct Connect      │                    │
│                         └────────────────────────────────────┘                    │
│                              encrypted, <5ms latency target                       │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### 8.2 What Goes Where — Decision Matrix

```
┌──────────────────────────┬───────────┬────────────┬──────────────────────────────┐
│ Component                │ Cloud?    │ Colo?      │ Reason                       │
├──────────────────────────┼───────────┼────────────┼──────────────────────────────┤
│ CDN / WAF / ALB          │ ✓         │            │ Edge presence, DDoS absorb   │
│ API Pods                 │ ✓         │            │ Auto-scale, burst capacity   │
│ Workers                  │ ✓         │            │ Ephemeral, cloud-native      │
│ GPU / ML Pods            │ ✓         │            │ GPU availability on-demand   │
│ Observability (metrics)  │ ✓         │            │ Scalable storage (S3/GCS)    │
│                          │           │            │                              │
│ PostgreSQL (PII/PCI)     │           │ ✓          │ Data sovereignty, blast rad  │
│ TimescaleDB (audit logs) │           │ ✓          │ Regulatory retention         │
│ Redis (session/cache)    │ ✓ or      │ ✓          │ Depends on latency budget*   │
│ HSM / Key Management     │           │ ✓          │ Keys never leave your rack   │
│ Backup media (cold)      │           │ ✓          │ Air-gap for ransomware       │
│                          │           │            │                              │
│ Disaster Recovery site   │ ✓ (2nd    │            │ Cloud multi-region is faster │
│                          │ region)   │            │ to failover than 2nd colo    │
└──────────────────────────┴───────────┴────────────┴──────────────────────────────┘

* Redis latency: If colo → cloud hop is <3ms (Direct Connect), keep Redis in colo
  with databases. If >5ms, deploy Redis read-replicas in cloud for hot-path reads.
```

### 8.3 Multi-Cloud Alternative (Active-Active)

```
OPTION B: MULTI-CLOUD ACTIVE-ACTIVE
════════════════════════════════════

┌────────────────┐    GSLB     ┌────────────────┐
│ AWS Region 1   │◄──────────►│ GCP Region 1   │
│ (Primary)      │  (Route 53  │ (Secondary)    │
│                │   + Cloud   │                │
│ Full stack     │   DNS)      │ Full stack     │
│ EKS + RDS      │             │ GKE + CloudSQL │
│ ElastiCache    │             │ Memorystore    │
└───────┬────────┘             └───────┬────────┘
        │                              │
        │     Cross-cloud DB sync      │
        └──────────────────────────────┘
          (via Postgres logical rep +
           conflict resolution)

VERDICT: Adds significant complexity. Only justified if:
  - Regulatory requires presence in specific clouds
  - Need to survive full cloud provider outage
  - For ShopSquire at 25K CCU: OVERKILL — single cloud + colo is better ROI
```

---

## 9. FinOps Management

### 9.1 Cost Visibility Framework

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         FINOPS PILLARS                                       │
│                                                                              │
│  1. INFORM ──────────►  2. OPTIMIZE ──────────►  3. OPERATE                 │
│                                                                              │
│  Cost tagging           Right-sizing              Budget alerts              │
│  Showback reports       Spot/Reserved mix          Anomaly detection         │
│  Unit economics         GPU time-sharing           Chargeback per tenant     │
│  Per-tenant metering    Autoscaling tuning         Commitment management     │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 9.2 Tagging Strategy

```
MANDATORY TAGS (enforce via SCP / Organization Policy)
═══════════════════════════════════════════════════════
  project:      shopsquire
  environment:  production | staging | development
  component:    api | worker | ml | cache | database | obs
  team:         platform | ml | security
  cost-center:  CC-{tenant} | CC-shared
  managed-by:   terraform | helm
```

### 9.3 Cost Optimization Levers

```
┌─────────────────────────────┬────────────────────────────────────────────────┐
│ Lever                       │ Estimated Savings                              │
├─────────────────────────────┼────────────────────────────────────────────────┤
│ Spot instances (CPU pool)   │ 50-70% on compute (use Karpenter)             │
│ Reserved / Savings Plans    │ 30-40% on baseline GPU + DB                   │
│   (1yr commit for DB, GPU)  │                                                │
│ Scale-to-zero ML pods       │ 20-40% GPU cost (voice pods idle at night)    │
│ Right-size RDS              │ 10-30% (use Performance Insights data)        │
│ S3 Intelligent-Tiering      │ 30-50% on log/backup storage                  │
│ OpenAI API vs. self-hosted  │ At <5K CCU: API cheaper than GPU infra        │
│   LLM (break-even analysis) │ At >10K CCU: self-host may be cheaper         │
│ Semantic cache hit rate     │ 30-60% fewer LLM calls (~$0.03 saved/hit)    │
│ CDN cache for static + API  │ 20-40% reduction in API pod count             │
│ Graviton instances (ARM)    │ 20-30% vs x86 for CPU workloads              │
│ NAT Gateway optimization    │ Use VPC endpoints for S3, Secrets Manager     │
│   (S3 VPC endpoint etc.)    │ saves $0.045/GB NAT charges                   │
└─────────────────────────────┴────────────────────────────────────────────────┘
```

### 9.4 Per-Tenant Unit Economics

```
UNIT COST MODEL (target metrics for FinOps dashboards)
══════════════════════════════════════════════════════

  Cost per active tenant per month (CPAT)
  ├── Compute:   API pods allocated time / active tenants
  ├── LLM:       OpenAI tokens consumed per tenant (metered)
  ├── GPU:       Inference seconds per tenant (label-based)
  ├── Storage:   DB rows × avg row size × storage $/GB
  ├── Cache:     Redis memory per tenant namespace
  ├── Bandwidth: Egress per tenant (CloudFront logs)
  └── Support:   Ticket volume per tenant

  Target CPAT <  $15/tenant/month at 1K tenants
  Target CPAT <  $8/tenant/month at 10K tenants
  Target CPAT <  $5/tenant/month at 25K tenants (economies of scale)

  LLM-SPECIFIC TRACKING:
  ┌──────────────────────┬────────────┬──────────┬──────────────┐
  │ Metric               │ Source     │ Tag      │ Alert If     │
  ├──────────────────────┼────────────┼──────────┼──────────────┤
  │ tokens_in_per_turn   │ llm_router │ tenant   │ >4k/turn     │
  │ tokens_out_per_turn  │ llm_router │ tenant   │ >2k/turn     │
  │ cache_hit_rate       │ sem_cache  │ global   │ <40%         │
  │ llm_cost_per_day     │ billing    │ tenant   │ >$50/day     │
  │ gpu_seconds_per_req  │ ollama     │ model    │ P99 >30s     │
  └──────────────────────┴────────────┴──────────┴──────────────┘
```

---

## 10. SWOT Analysis

```
┌─────────────────────────────────────┬─────────────────────────────────────┐
│         STRENGTHS (S)               │         WEAKNESSES (W)              │
├─────────────────────────────────────┼─────────────────────────────────────┤
│                                     │                                     │
│ • Comprehensive security stack      │ • Large surface area — 100+ routers│
│   (email BEC, YARA, MISP, DREAD,   │   increases operational complexity  │
│   LOLBin, ransomware detection)     │   and attack surface                │
│                                     │                                     │
│ • Multi-modal AI (LLM + CV + Voice  │ • GPU dependency for core features │
│   + embeddings + semantic search)   │   creates supply/cost pressure      │
│                                     │                                     │
│ • Existing IaC (Terraform + Helm    │ • Monolith-ish single container    │
│   + Docker Compose) ready to deploy │   image; all code in one Dockerfile│
│                                     │                                     │
│ • Defence-in-depth security model   │ • Single database for all data;    │
│   (mTLS, RBAC, PCI boundary, DLP,  │   no CQRS or event sourcing yet    │
│   audit chain)                      │                                     │
│                                     │ • Tight coupling between security  │
│ • Observability built-in            │   modules and API (same pod)       │
│   (Prometheus, Grafana, Loki,       │                                     │
│   Jaeger, alerting rules)           │ • No multi-region failover config  │
│                                     │   in current Terraform             │
│ • Tenant-aware config + feature     │                                     │
│   flags per tenant                  │ • Voice/ASR not yet mature         │
│                                     │                                     │
│ • Agent orchestration with policy   │ • OpenAI API dependency for LLM   │
│   gates and guardrails              │   (vendor lock-in risk)            │
│                                     │                                     │
└─────────────────────────────────────┴─────────────────────────────────────┘
┌─────────────────────────────────────┬─────────────────────────────────────┐
│         OPPORTUNITIES (O)           │         THREATS (T)                 │
├─────────────────────────────────────┼─────────────────────────────────────┤
│                                     │                                     │
│ • SOC-as-a-Service for e-commerce   │ • Cloud provider price increases   │
│   (email security is rare in        │   (especially GPU instances)        │
│   commerce platforms)               │                                     │
│                                     │ • LLM API cost volatility          │
│ • Multi-tenant SaaS — each tenant   │   (OpenAI pricing changes)         │
│   is a revenue stream               │                                     │
│                                     │ • Supply chain attacks on model    │
│ • Compliance-as-feature (PCI, SOC2  │   weights / dependencies           │
│   GDPR, data sovereignty)           │                                     │
│                                     │ • Competitors (Shopify native AI,  │
│ • Edge inference (on-prem GPU for   │   BigCommerce, Salesforce Commerce │
│   latency-sensitive markets)        │   Cloud adding similar features)   │
│                                     │                                     │
│ • Marketplace for security          │ • GPU shortage during AI demand    │
│   playbooks and agent policies      │   spikes (hard to scale GPU pool)  │
│                                     │                                     │
│ • Colo offering for data sovereign  │ • Regulatory changes (EU AI Act,   │
│   customers (premium tier)          │   GDPR enforcement, PCI DSS 4.0)  │
│                                     │                                     │
│ • Hybrid cloud for govt/finance     │ • Model hallucination liability    │
│   verticals requiring on-prem data  │   in automated commerce decisions  │
│                                     │                                     │
│ • B2B API / SDK revenue channel     │ • Key person risk (complex stack   │
│   (sdk/ already exists)             │   requires deep domain knowledge)  │
│                                     │                                     │
└─────────────────────────────────────┴─────────────────────────────────────┘
```

---

## 11. PESTEL Analysis

```
┌───────────────────────────────────────────────────────────────────────────────┐
│                           PESTEL ANALYSIS                                     │
├───────────────┬───────────────────────────────────────────────────────────────┤
│               │                                                               │
│  POLITICAL    │ • Data sovereignty laws (GDPR, Australia Privacy Act,        │
│               │   Singapore PDPA) — drives colo/hybrid architecture need     │
│               │ • US-China tech tensions may restrict GPU supply chains      │
│               │ • Government procurement requires FedRAMP/IRAP compliance    │
│               │ • Trade sanctions affect which cloud regions are usable      │
│               │ • Political pressure for AI transparency (EU AI Act 2026)   │
│               │                                                               │
├───────────────┼───────────────────────────────────────────────────────────────┤
│               │                                                               │
│  ECONOMIC     │ • Cloud compute costs trending up (GPU 20-40% YoY increase) │
│               │ • LLM API costs declining (GPT-4o-mini is 10x cheaper than  │
│               │   GPT-4 was) — favors API over self-hosted at mid-scale     │
│               │ • FinOps discipline is critical for SaaS unit economics     │
│               │ • Reserved/Savings Plans offer 30-40% discount for commit   │
│               │ • Multi-tenant amortization improves with scale             │
│               │ • Recession risk: customers may cut SaaS spend —            │
│               │   security features become hard to justify vs. core commerce│
│               │ • Exchange rate risk for multi-region cloud billing          │
│               │                                                               │
├───────────────┼───────────────────────────────────────────────────────────────┤
│               │                                                               │
│  SOCIAL       │ • Consumer trust in AI-assisted commerce is growing but     │
│               │   fragile — one publicized hallucination can damage brand    │
│               │ • Merchant demand for AI agents in support/chat is surging  │
│               │ • BEC (Business Email Compromise) awareness increasing —    │
│               │   ShopSquire's email security is a differentiator           │
│               │ • Sustainability pressure: GPU-heavy workloads have high    │
│               │   carbon footprint — choose green cloud regions             │
│               │ • Remote/hybrid workforce increases email attack surface    │
│               │                                                               │
├───────────────┼───────────────────────────────────────────────────────────────┤
│               │                                                               │
│  TECHNOLOGICAL│ • NVIDIA H100/B200 price and availability improving         │
│               │ • Edge AI chips (Apple M-series, Qualcomm) enable on-device │
│               │   inference — future ShopSquire mobile SDK possibility      │
│               │ • Serverless GPU (Modal, Banana, RunPod) emerging for burst │
│               │ • vLLM/TGI continuous batching makes self-hosting viable    │
│               │ • pgvector + HNSW index performance improving rapidly       │
│               │ • WebAssembly + ONNX-runtime for browser-side inference     │
│               │ • Kubernetes GPU time-slicing (MPS/MIG) maturing            │
│               │ • eBPF-based observability reducing agent overhead           │
│               │                                                               │
├───────────────┼───────────────────────────────────────────────────────────────┤
│               │                                                               │
│  ENVIRONMENTAL│ • GPU-heavy workloads: ~300W per A10G GPU × 24/7            │
│               │ • Choose AWS us-west-2 (>90% renewable) or eu-north-1       │
│               │ • Right-sizing and scale-to-zero directly reduce carbon     │
│               │ • Colo partner selection: prioritize PUE <1.3              │
│               │ • Scope 3 emissions reporting may become mandatory          │
│               │ • Carbon-aware scheduling (shift batch GPU jobs to low-     │
│               │   carbon hours) is emerging best practice                   │
│               │                                                               │
├───────────────┼───────────────────────────────────────────────────────────────┤
│               │                                                               │
│  LEGAL        │ • GDPR Article 28: processor obligations for tenant data    │
│               │ • PCI DSS 4.0 (March 2025 mandate): network segmentation   │
│               │   requirements align with subnet isolation strategy         │
│               │ • SOC 2 Type II: audit trail (audit_chain.py) is asset      │
│               │ • EU AI Act: high-risk classification if AI makes pricing/  │
│               │   fraud decisions — requires human oversight mechanism       │
│               │ • Model licensing: YOLO is AGPL, Ollama models may have    │
│               │   restrictive licenses — affects distribution               │
│               │ • Liability for automated security verdicts (false positive │
│               │   quarantine of legitimate supplier emails)                 │
│               │ • Cross-border data transfer: Schrems II / data adequacy   │
│               │                                                               │
└───────────────┴───────────────────────────────────────────────────────────────┘
```

---

## 12. Pros & Cons Summary

### 12.1 Pure Public Cloud

```
PROS                                    CONS
════                                    ════
+ Fastest time to market               - Vendor lock-in (EKS → hard to migrate)
+ Elastic GPU scaling                   - Data sovereignty concerns
+ Managed services (RDS, ElastiCache)   - Egress costs add up at scale
+ Global CDN/edge presence              - No physical control over hardware
+ Built-in DDoS protection              - GPU spot interruptions
+ Compliance certs (SOC2, ISO27001)     - Costs scale linearly (no cap)
+ DR via multi-region is turnkey        - OpenAI API double-hop latency
```

### 12.2 Hybrid Cloud + Colo

```
PROS                                    CONS
════                                    ════
+ Data sovereignty guaranteed           - Higher upfront capex (colo hardware)
+ Reduced blast radius (DB isolated)    - Operational complexity (2 platforms)
+ Fixed-cost DB/cache infra             - Cross-premises networking overhead
+ Keys/HSM on your own hardware         - GPU procurement lead time
+ Regulatory compliance (PCI, GDPR)     - Colo failover is slower than cloud DR
+ Lower long-term TCO at scale          - Need on-site or remote-hands team
+ Air-gapped backup possible            - Direct Connect / VPN adds ~2-5ms
```

### 12.3 Multi-Cloud Active-Active

```
PROS                                    CONS
════                                    ════
+ Survive full cloud provider outage    - 2-3x operational complexity
+ Negotiate better pricing              - Cross-cloud DB sync is hard
+ Best-of-breed per provider            - Developer tooling divergence
+ Zero vendor lock-in (in theory)       - Cost of dual egress
                                        - Conflict resolution for writes
                                        - Testing matrix explosion
                                        - NOT RECOMMENDED at <25K CCU
```

---

## 13. Pushbacks, Alternatives & Open Questions

### 13.1 Pushbacks (Devil's Advocate)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ PUSHBACK 1: "Do you actually need self-hosted LLM at this stage?"          │
│                                                                             │
│ At <5K CCU, OpenAI API is cheaper than GPU infrastructure:                 │
│   • g5.xlarge = ~$1.01/hr = ~$730/month                                   │
│   • 5K CCU × 5 agent turns/day × 1K tokens/turn × $0.002/1K tokens        │
│     = ~$50/day = ~$1,500/month                                             │
│   • GPU infra + maintenance + on-call > API cost until ~10-15K CCU        │
│                                                                             │
│ RECOMMENDATION: Start with OpenAI API + GPU only for CV/Voice.            │
│ Switch to self-hosted when API costs exceed GPU infra by 30%.              │
├─────────────────────────────────────────────────────────────────────────────┤
│ PUSHBACK 2: "Five subnet tiers is over-engineered for a startup"           │
│                                                                             │
│ Valid at <1K CCU. Simplify to:                                             │
│   • Public subnet (ALB)                                                    │
│   • Private subnet (everything else)                                       │
│   • Isolated subnet (database only, no NAT)                                │
│ Add ML/AI subnet and Obs subnet when you hit 5K CCU.                      │
├─────────────────────────────────────────────────────────────────────────────┤
│ PUSHBACK 3: "Colo adds complexity you don't need yet"                      │
│                                                                             │
│ True unless your customers require data sovereignty NOW. If you're         │
│ selling to EU/AU/SG enterprises, colo is a day-1 sales requirement.       │
│ Otherwise, defer to Phase 2 (post 5K CCU).                                │
├─────────────────────────────────────────────────────────────────────────────┤
│ PUSHBACK 4: "Monolith container image should be split"                     │
│                                                                             │
│ The current Dockerfile builds a single image for API + workers + ML.       │
│ This wastes memory (API pods carry YOLO weights they don't use).           │
│                                                                             │
│ RECOMMENDATION: Split into 3 images by Phase 2:                            │
│   • shopsquire-api (slim: FastAPI + routers + security)                   │
│   • shopsquire-worker (slim: workers + connectors)                        │
│   • shopsquire-ml (full: CV + Ollama client + models)                     │
├─────────────────────────────────────────────────────────────────────────────┤
│ PUSHBACK 5: "Redis doesn't need its own subnet"                            │
│                                                                             │
│ For PCI DSS 4.0 compliance, CDE (cardholder data environment) components  │
│ should be in the tightest-possible network boundary. If Redis ever caches  │
│ PCI-scoped data, separate subnet is justified. If it only caches product  │
│ catalog data, merge cache subnet into app private subnet.                  │
├─────────────────────────────────────────────────────────────────────────────┤
│ PUSHBACK 6: "25K CCU estimate may never happen — you're overplanning"      │
│                                                                             │
│ Fair. Design for 5K, plan for 25K. The scaling matrix shows exactly        │
│ which decisions to defer. Don't buy Reserved Instances for 25K on day 1.   │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 13.2 Alternatives Worth Evaluating

```
┌──────────────────────────┬──────────────────────────────────────────────────┐
│ Alternative              │ When to Consider                                 │
├──────────────────────────┼──────────────────────────────────────────────────┤
│ Serverless GPU           │ Burst CV/LLM workloads without owning GPU nodes │
│ (Modal, Replicate, Beam) │ Good for <1K CCU with sporadic ML usage         │
│                          │                                                  │
│ AWS Bedrock / Azure      │ Managed LLM API with VPC integration            │
│ OpenAI Service           │ Data stays in your VPC (vs public OpenAI API)   │
│                          │                                                  │
│ Cloudflare Workers +     │ Edge compute for API, R2 for storage            │
│ Durable Objects          │ Radical cost reduction at global scale          │
│                          │ BUT: no GPU, limited Python support             │
│                          │                                                  │
│ Fly.io / Railway         │ Simpler Kubernetes alternative for small teams  │
│                          │ GPU machines available. Less enterprise-ready.  │
│                          │                                                  │
│ Managed Kubernetes       │ EKS Anywhere / Anthos for hybrid scenarios     │
│ (EKS Anywhere, Anthos)   │ Unified K8s control plane across cloud + colo  │
│                          │                                                  │
│ CQRS + Event Sourcing    │ If decision replay and audit chain become       │
│                          │ critical (you already have decision_replay.py)  │
│                          │                                                  │
│ Cell-based Architecture  │ At >25K CCU with multi-tenant isolation needs   │
│ (tenant sharding)        │ Each "cell" is an independent deployment        │
└──────────────────────────┴──────────────────────────────────────────────────┘
```

### 13.3 Open Questions to Answer Before Deploying

```
 1. What is the target P95 latency for /recommend and /chat endpoints?
    → Determines whether self-hosted LLM or API is the right call.

 2. Which regulatory frameworks are required Day 1?
    → PCI DSS 4.0, SOC 2, GDPR, or all three? Drives subnet isolation depth.

 3. What is the expected ratio of storefront (read-heavy) vs. admin (write-heavy)?
    → Determines read-replica count and CQRS investment.

 4. Is multi-tenant data isolation logical (shared DB, row-level) or physical?
    → Physical = separate DB per tenant = very different cost model.

 5. What is the LLM token budget per tenant per month?
    → Directly impacts FinOps and whether GPU investment is justified.

 6. Is edge/on-prem deployment a requirement for any customer?
    → If yes, start building shopsquire-ml as a standalone distributable.

 7. What is the RTO/RPO target?
    → Drives multi-AZ vs. multi-region vs. active-active decisions.

 8. Who manages the colo hardware?
    → In-house team vs. managed hosting vs. partner (Equinix Metal, etc.)

 9. Should the observability stack be self-hosted or managed?
    → Grafana Cloud + Datadog vs. self-hosted saves ops burden.

10. What is the monthly infrastructure budget ceiling?
    → Hard constraint that overrides all architecture ideals.
```

---

*This document is version-controlled alongside the codebase and should be revisited at each scaling milestone (100 → 1K → 5K → 10K → 25K CCU).*
