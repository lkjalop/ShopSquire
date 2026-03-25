# ShopSquire Production-Grade Upgrade — Master Roadmap
*Generated 2026-03-25 | Current branch: wip/docker-real-env-20260213*

---

## Executive Summary

ShopSquire has strong bones — 26-signal fraud scoring, real image forensics, a 4-phase orchestrator, SSE streaming, and a full Neo4j/pgvector stack. What it lacks is the **last mile wiring**: the stubs are never promoted to production calls, ML models are placeholders, graph analytics run in-memory instead of against live data, and LLM responses still leak technical JSON to business users.

This roadmap covers four production-grade upgrades in dependency order:

| # | Upgrade | Effort | Business Impact |
|---|---------|--------|-----------------|
| 1 | Orchestrator Vision Reasoning | Large | "Upload a photo → get the right product" actually works |
| 2 | Real Vulnerability Scanning | Medium | Security posture visible to merchant, not just logs |
| 3 | Robust ML Anomaly Detection | Medium | Fraud/anomaly signals based on learned patterns, not Z-scores |
| 4 | pgvector + Graph Analytics Everywhere | Large | Semantic search, fraud ring detection, graph dashboards |

**UX thread (cuts across all four):** Every agent output must be translated to plain English before it reaches the UI. JSON is for the trace panel only.

---

## How These Changes Alter the Architecture

```
BEFORE                                     AFTER
──────────────────────────────────────     ──────────────────────────────────────
Image upload                               Image upload
  └─ image_intake.py (sanitize)              └─ image_intake.py (sanitize + threat scan)
  └─ image_intent_router.py (classify)       └─ image_intent_router.py (classify)
  └─ cv_triage_basic.py ← LABEL STUB         └─ VisionReasoningService ← REAL LLM
       returns keyword scores                     GPT-4V / Gemini / local LLaVA
                                                  Product_Identity_Agent wired
                                                  spec extraction → NQE seed

Fraud scoring                              Fraud scoring
  └─ fraud_scorer.py (26 signals)           └─ fraud_scorer.py (26 signals)
  └─ anomaly_detector.py ← Z-SCORE          └─ anomaly_detector.py ← IsolationForest
       returns z≥3.0 only                        + Prophet (time series)
  └─ gnn_fraud_detector.py ← OPTIONAL       └─ gnn_fraud_detector.py ← ALWAYS ON
       zero-features if Neo4j off                real features from Neo4j

Vector search                              Vector search
  └─ vector_store.py (pgvector adapter)     └─ vector_store.py (pgvector adapter)
  └─ recommend.py calls keyword SQL         └─ recommend.py calls vector similarity
  └─ pgvector fallback: returns []          └─ pgvector REQUIRED, migration enforced

Vulnerability awareness                    Vulnerability scanning
  └─ dread_scorer.py (maps signals)         └─ VulnScanService
  └─ intake_gate.py (policy check)               nuclei/semgrep/trivy wired
  └─ NO CVE database                             CVE lookup → risk score
  └─ NO active scanning                          merchant security score card

Response generation                        Response generation
  └─ _summarize_results() → LLM text       └─ _summarize_results() → LLM text
  └─ trace panel leaks JSON                 └─ ResponseNormalizer strips all JSON
  └─ agent steps shown raw                  └─ agent steps → plain English bullets
```

---

## Dependency Order

```
pgvector migrations (Day 1)
    ↓
Neo4j provisioning (Day 2)
    ↓
GNN training pipeline (Day 3-4)
    ↓
Anomaly Detector upgrade (Day 5)
    ↓
Vision LLM wiring (Day 5-6)
    ↓
Vuln scanning integration (Day 7-8)
    ↓
UX / Response normalizer (Day 9-10)
    ↓
End-to-end integration tests (Day 11-12)
```

---

## Files Modified Across All Upgrades

| File | Change Count | Reason |
|------|-------------|--------|
| `src/app/services/anomaly_detector.py` | Major rewrite | Replace Z-score with IsolationForest + Prophet |
| `src/app/services/cv_triage_basic.py` | Major rewrite | Replace label stub with vision LLM |
| `src/app/services/vector_store.py` | Extensions | Multi-table support, batch indexing |
| `src/app/routers/recommend.py` | Line edits | Wire pgvector search, vector re-rank |
| `src/app/services/orchestrator.py` | Extensions | Hook VisionReasoningService into EVALUATE phase |
| `src/app/services/llm_provider.py` | Line edits | Fix multimodal scoring bug |
| `src/app/services/gnn_fraud_detector.py` | Extensions | Remove Neo4j guard, training pipeline |
| `src/app/routers/query.py` | Extensions | ResponseNormalizer integration |
| `src/app/routers/support.py` | Extensions | ResponseNormalizer integration |
| NEW: `src/app/services/vision_reasoning.py` | New file | Vision LLM wrapper + spec extractor |
| NEW: `src/app/services/vuln_scanner.py` | New file | nuclei/semgrep/trivy/CVE wrapper |
| NEW: `src/app/services/response_normalizer.py` | New file | JSON → plain English translator |
| NEW: `alembic/versions/xxxx_pgvector.py` | New migration | Ensure pgvector extension + indexes |
| `docker-compose.yml` | Extensions | Add vuln scanner sidecar, Neo4j volumes |
| `src/app/config.py` | Extensions | New env vars for all four providers |

---

## Sprint Breakdown

### Sprint 1 — Infrastructure Foundation (Days 1–4)
**Goal:** pgvector and Neo4j running with real data; GNN produceable

| Task | File | Owner |
|------|------|-------|
| Run alembic migration: pgvector extension + 3 tables | `alembic/versions/20260325_pgvector.py` | Infra |
| Swap `postgres:16` → `pgvector/pgvector:pg16` in docker-compose | `docker-compose.yml` | Infra |
| Add Neo4j service to docker-compose + set env vars | `docker-compose.yml` | Infra |
| Enable FRAUD_GRAPH_NEO4J_ENABLED=1 | `.env` | Config |
| Run `scripts/index_catalog.py` initial product embedding | `scripts/index_catalog.py` (new) | Dev |
| Write GNN training script | `scripts/train_gnn.py` (new) | Dev |

### Sprint 2 — ML Anomaly Detection (Days 5–6)
**Goal:** IsolationForest + Prophet replace Z-score; GNN uses networkx fallback

| Task | File | Lines |
|------|------|-------|
| Rewrite `AnomalyDetector.detect()` | `src/app/services/anomaly_detector.py` | Full rewrite (~41 → ~200 lines) |
| Add networkx fallback to GNN | `src/app/services/gnn_fraud_detector.py` | Replace `_zero_features()` call ~line 84 |
| Wire anomaly detector into fraud scorer | `src/app/services/fraud_scorer.py` | ~line 300 in `score_with_enrichment()` |
| Add Celery hourly snapshot task | `src/app/tasks/anomaly_snapshots.py` (new) | New file |
| Add `pip install scikit-learn prophet pandas` | `requirements.txt` | Add lines |

### Sprint 3 — Vision Reasoning (Days 7–8)
**Goal:** Real vision LLM replaces cv_triage_basic stub; Product_Identity_Agent wired

| Task | File | Lines |
|------|------|-------|
| Create `VisionReasoningService` | `src/app/services/vision_reasoning.py` (new) | New file |
| Rewrite `cv_triage_basic.analyze()` to call VisionReasoningService | `src/app/services/cv_triage_basic.py` | Replace lines 27–85 |
| Fix multimodal complexity scoring | `src/app/services/llm_provider.py` | ~line 139–155 |
| Wire vision spec extraction into recommend.py | `src/app/routers/recommend.py` | After image sanitize block |
| Wire vision into orchestrator EVALUATE phase | `src/app/services/orchestrator.py` | In EVALUATE candidate scoring |
| Add OPENAI_API_KEY / OLLAMA_VISION_MODEL config | `src/app/config.py` | Add to Settings class |
| Add LLaVA to docker-compose ollama service | `docker-compose.yml` | ollama service |

### Sprint 4 — Vulnerability Scanning (Days 9–10)
**Goal:** Trivy + Nuclei + CISA KEV active; merchant security scorecard visible

| Task | File | Lines |
|------|------|-------|
| Create `VulnScanService` | `src/app/services/vuln_scanner.py` (new) | New file |
| Create `/api/v1/security/scan/full` endpoint | `src/app/routers/vuln_scan.py` (new) | New file |
| Register router in main.py | `src/app/main.py` | Add `include_router(vuln_scan.router)` |
| Wire VulnReport into DREAD scorer | `src/app/security/dread_scorer.py` | Add `score_vuln_report()` method |
| Auto-escalate critical CVEs to incidents | `src/app/routers/vuln_scan.py` | After scan completion |
| Add trivy/nuclei to Dockerfile or docker-compose | `docker-compose.yml` / `Dockerfile` | Add services |
| Add VULN_SCAN_ENABLED env var | `src/app/config.py` | Add to Settings class |

### Sprint 5 — pgvector Search + Graph Analytics (Days 11–13)
**Goal:** Semantic search active; fraud rings visible in dashboard; FAQ semantic matching

| Task | File | Lines |
|------|------|-------|
| Extend `PgVectorStore` with `batch_index()` and `query_with_filter()` | `src/app/services/vector_store.py` | Add methods after line 100 |
| Create `EmbeddingPipeline` service | `src/app/services/embedding_pipeline.py` (new) | New file |
| Wire `_merged_search()` into recommend.py (RRF fusion) | `src/app/routers/recommend.py` | Replace keyword-only search |
| Add `/api/v1/analytics/fraud-rings` endpoint | `src/app/routers/graph.py` or analytics | New endpoint |
| Semantic FAQ resolution | `src/app/services/faq_v2.py` | Add `resolve_semantic()` method |
| Celery tasks: graph refresh + nightly re-index | `src/app/tasks/graph_refresh.py` (new) | New file |

### Sprint 6 — UX / Response Quality (Days 14–15)
**Goal:** Zero raw JSON in chat; all agent outputs in plain English; budget questions answered directly

| Task | File | Lines |
|------|------|-------|
| Create `ResponseNormalizer` | `src/app/services/response_normalizer.py` (new) | New file |
| Polish LLM answer before SSE emit | `src/app/routers/chat_stream.py` | ~line 75 |
| CV/forensics → plain English in vision router | `src/app/routers/vision.py` | Response builder |
| Add `to_merchant_dict()` to fraud scorer | `src/app/services/fraud_scorer.py` | After existing score methods |
| Strip raw similarity scores from support/query responses | `src/app/routers/support.py`, `query.py` | Response dicts |
| Fix budget question model routing | `src/app/services/llm_provider.py` | ~line 139 (add budget_question signal +2) |
| Frontend: render `agent_steps_readable` | `frontend/src/components/ChatMessage` | Step renderer |

---

## New Files Created by This Roadmap

```
src/app/services/vision_reasoning.py       ← Vision LLM wrapper (GPT-4V/Gemini/LLaVA)
src/app/services/vuln_scanner.py           ← Trivy/Nuclei/Semgrep/CVE orchestrator
src/app/services/response_normalizer.py    ← JSON → plain English translator
src/app/services/embedding_pipeline.py    ← OpenAI/sentence-transformers embedder
src/app/routers/vuln_scan.py              ← /api/v1/security/scan/* endpoints
src/app/tasks/anomaly_snapshots.py        ← Celery hourly anomaly feed
src/app/tasks/graph_refresh.py            ← Celery Neo4j + catalog refresh
alembic/versions/20260325_pgvector.py     ← pgvector extension + HNSW indexes
scripts/index_catalog.py                  ← One-shot catalog embedding
scripts/train_gnn.py                      ← GNN model training
```

## Environment Variables Required

```bash
# Vision LLM (pick one)
OPENAI_API_KEY=sk-...
GOOGLE_AI_API_KEY=...
OLLAMA_VISION_MODEL=llava:13b          # local fallback

# Graph fraud detection
FRAUD_GRAPH_NEO4J_ENABLED=1
NEO4J_URI=bolt://neo4j:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=shopSquire_neo4j

# Vulnerability scanning
VULN_SCAN_ENABLED=true
VULN_SCAN_WEB_ENABLED=false            # opt-in only

# GNN model path (after training)
GNN_MODEL_PATH=config/gnn_model.pt

# Feature flags
VECTOR_SEARCH_ENABLED=1               # enables RRF-merged search
```

---

## Detailed Docs (one per upgrade area)

| Doc | Contents |
|-----|----------|
| [PROD-GRADE-01-ORCHESTRATOR-VISION.md](PROD-GRADE-01-ORCHESTRATOR-VISION.md) | Vision LLM providers, spec extraction, NQE seeding, complexity scoring fix |
| [PROD-GRADE-02-VULNERABILITY-SCANNING.md](PROD-GRADE-02-VULNERABILITY-SCANNING.md) | VulnScanService code, DREAD wiring, CISA KEV, auto-escalation |
| [PROD-GRADE-03-ML-ANOMALY-DETECTION.md](PROD-GRADE-03-ML-ANOMALY-DETECTION.md) | Full AnomalyDetector rewrite, GNN networkx fallback, training pipeline |
| [PROD-GRADE-04-PGVECTOR-GRAPH-ANALYTICS.md](PROD-GRADE-04-PGVECTOR-GRAPH-ANALYTICS.md) | Migration, embedding pipeline, RRF search, fraud ring endpoint, Celery tasks |
| [PROD-GRADE-05-UX-RESPONSE-QUALITY.md](PROD-GRADE-05-UX-RESPONSE-QUALITY.md) | ResponseNormalizer, SSE polish, plain-English patterns, budget fix |
