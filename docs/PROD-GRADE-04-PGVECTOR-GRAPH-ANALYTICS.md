# Production-Grade: pgvector + Graph Analytics Everywhere
*ShopSquire — Deep Dive Implementation Guide | 2026-03-25*

---

## What Is Broken Today

### pgvector — Connected but Never Used for Recommendations

**File:** `src/app/services/vector_store.py`

The pgvector adapter exists and works. The problem:
- `recommend.py` never calls `vector_store.query()` — all product search is keyword SQL
- There are no embeddings indexed for the product catalog
- There is no embedding generation pipeline (products must be embedded before you can search them)
- The `index()` method returns `{ok: False, reason: "no_engine"}` silently on failure with no alerting

### Neo4j Graph — Conditionally Disabled

**File:** `src/app/services/neo4j_graph.py` lines 49–55

```python
# Current guard — returns disabled signal if not configured
if not self._enabled:
    return {"enabled": False, "reason": "FRAUD_GRAPH_NEO4J_ENABLED not set"}
```

The fraud ring signals `shipping_address_clustered` and `account_device_ip_ring_hit` are always 0.0 in a standard deployment because Neo4j isn't required.

### graph_builder.py — Never Called from the Dashboard

**File:** `src/app/analytics/graph_builder.py`

The `build_graph()` function builds a fraud ring visualization. There is no API endpoint that exposes it, no dashboard widget consuming it, and no scheduled job that keeps it fresh.

---

## Architecture: Production pgvector + Graph Stack

```
CURRENT:
  recommend.py → keyword SQL → products[]
  vector_store.py → (never called)
  neo4j_graph.py → (disabled by default)
  graph_builder.py → (never called from any endpoint)

PRODUCTION:

  Product catalog (Postgres)
       ↓
  EmbeddingPipeline (runs at ingest + nightly)
  embed each product: name + specs + description → 1536-dim vector
       ↓
  vector_store.py .index(sku, embedding, payload)
       ↓
  pgvector table: products_vec (id, embedding VECTOR(1536), payload JSONB)

  User query ("gaming laptop under $2000")
       ↓
  QueryEmbedder → embed query text → query_vector
       ↓
  vector_store.query(query_vector, table="products_vec", top_k=20)
       ↓ (semantic results: finds "esports" even if query says "gaming")
  Keyword SQL (existing — for hard filters: price, brand)
       ↓
  RRF merge: Reciprocal Rank Fusion of vector + keyword results
       ↓
  Orchestrator EVALUATE phase reranks final 10

  Neo4j (always-on, local if needed):
  session events → upsert_account_device_ip_event()
  Celery task: refresh_fraud_rings() every 4 hours
  graph_analytics endpoint → fraud ring visualization
  admin dashboard: "5 accounts share device ABC-123"
```

---

## Step 1 — Enforce pgvector Migration

**New file:** `alembic/versions/20260325_pgvector.py`

```python
"""ensure pgvector extension and products_vec table

Revision ID: 20260325_pgvector
Revises: <previous_revision>
Create Date: 2026-03-25
"""
from alembic import op
import sqlalchemy as sa

def upgrade():
    # Enable pgvector extension (idempotent)
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # Products vector table
    op.execute("""
        CREATE TABLE IF NOT EXISTS products_vec (
            id          TEXT PRIMARY KEY,
            embedding   VECTOR(1536),
            payload     JSONB NOT NULL DEFAULT '{}'
        )
    """)

    # Approximate nearest neighbour index (HNSW — faster than IVFFlat for <1M rows)
    op.execute("""
        CREATE INDEX IF NOT EXISTS products_vec_hnsw_idx
        ON products_vec USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
    """)

    # Session embeddings table (for conversation memory retrieval)
    op.execute("""
        CREATE TABLE IF NOT EXISTS session_embeddings (
            session_id  TEXT,
            turn_idx    INTEGER,
            embedding   VECTOR(1536),
            summary     TEXT,
            created_at  TIMESTAMPTZ DEFAULT NOW(),
            PRIMARY KEY (session_id, turn_idx)
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS session_embeddings_hnsw_idx
        ON session_embeddings USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
    """)

    # FAQ embeddings (semantic FAQ matching)
    op.execute("""
        CREATE TABLE IF NOT EXISTS faq_embeddings (
            id          TEXT PRIMARY KEY,
            embedding   VECTOR(1536),
            question    TEXT,
            answer      TEXT,
            category    TEXT
        )
    """)

def downgrade():
    op.execute("DROP TABLE IF EXISTS faq_embeddings")
    op.execute("DROP TABLE IF EXISTS session_embeddings")
    op.execute("DROP TABLE IF EXISTS products_vec")
```

---

## Step 2 — Extend vector_store.py for Multi-Table Support

**File:** `src/app/services/vector_store.py`
**Current:** Single `vectors` table, no batch support, no embedding generation

```python
# vector_store.py — additions after existing PgVectorStore class

from typing import Optional, List, Dict, Any, Tuple

class PgVectorStore:
    # ... existing code unchanged ...

    async def batch_index(
        self,
        records: List[Tuple[str, List[float], Dict[str, Any]]],
        table: str = "vectors",
    ) -> Dict[str, Any]:
        """
        Bulk-upsert embeddings.
        records: list of (id, embedding_list, payload_dict)
        Returns: {indexed: N, errors: []}
        """
        if not self._engine:
            return {"indexed": 0, "errors": ["no_engine"]}
        if not self._safe_table(table):
            return {"indexed": 0, "errors": [f"invalid table name: {table}"]}

        errors = []
        indexed = 0
        async with self._engine.begin() as conn:
            for rec_id, embedding, payload in records:
                try:
                    await conn.execute(
                        sa.text(f"""
                            INSERT INTO {table} (id, embedding, payload)
                            VALUES (:id, :emb::VECTOR, :payload::JSONB)
                            ON CONFLICT (id) DO UPDATE
                            SET embedding = EXCLUDED.embedding,
                                payload   = EXCLUDED.payload
                        """),
                        {"id": rec_id, "emb": str(embedding), "payload": json.dumps(payload)}
                    )
                    indexed += 1
                except Exception as exc:
                    errors.append(f"{rec_id}: {exc}")
        return {"indexed": indexed, "errors": errors}

    async def query_with_filter(
        self,
        embedding: List[float],
        table: str = "vectors",
        top_k: int = 20,
        filter_sql: str = "",       # e.g. "payload->>'brand' = 'apple'"
        filter_params: Dict = None,
    ) -> List[Dict[str, Any]]:
        """
        Vector similarity search with optional SQL filter on JSONB payload.
        """
        if not self._engine:
            return []
        if not self._safe_table(table):
            return []
        where = f"AND ({filter_sql})" if filter_sql else ""
        async with self._engine.connect() as conn:
            rows = await conn.execute(
                sa.text(f"""
                    SELECT id, payload,
                           1 - (embedding <=> :emb::VECTOR) AS similarity
                    FROM {table}
                    WHERE 1=1 {where}
                    ORDER BY embedding <=> :emb::VECTOR
                    LIMIT :k
                """),
                {"emb": str(embedding), "k": top_k, **(filter_params or {})}
            )
            return [{"id": r.id, "payload": r.payload, "similarity": r.similarity} for r in rows]
```

---

## Step 3 — Create EmbeddingPipeline Service

**New file:** `src/app/services/embedding_pipeline.py`

```python
# src/app/services/embedding_pipeline.py
from __future__ import annotations
import logging
from typing import List, Dict, Any, Optional
from src.app.config import settings

log = logging.getLogger(__name__)


class EmbeddingPipeline:
    """
    Generates embeddings for products, FAQs, and conversation turns.
    Provider priority: OpenAI text-embedding-3-small → sentence-transformers (local)
    """

    def __init__(self):
        self._provider = self._detect_provider()

    def _detect_provider(self) -> str:
        if getattr(settings, "OPENAI_API_KEY", None):
            return "openai"
        try:
            from sentence_transformers import SentenceTransformer
            return "sentence_transformers"
        except ImportError:
            pass
        return "none"

    async def embed_text(self, text: str) -> Optional[List[float]]:
        if self._provider == "openai":
            return await self._openai_embed(text)
        if self._provider == "sentence_transformers":
            return self._st_embed(text)
        log.warning("No embedding provider configured. Set OPENAI_API_KEY or pip install sentence-transformers")
        return None

    async def embed_batch(self, texts: List[str]) -> List[Optional[List[float]]]:
        if self._provider == "openai":
            return await self._openai_embed_batch(texts)
        if self._provider == "sentence_transformers":
            return [self._st_embed(t) for t in texts]
        return [None] * len(texts)

    async def _openai_embed(self, text: str) -> List[float]:
        import openai
        client = openai.AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        resp = await client.embeddings.create(
            model="text-embedding-3-small",   # 1536-dim, cost-effective
            input=text[:8000],               # truncate to model limit
        )
        return resp.data[0].embedding

    async def _openai_embed_batch(self, texts: List[str]) -> List[List[float]]:
        import openai
        client = openai.AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        resp = await client.embeddings.create(
            model="text-embedding-3-small",
            input=[t[:8000] for t in texts],
        )
        return [d.embedding for d in resp.data]

    def _st_embed(self, text: str) -> List[float]:
        from sentence_transformers import SentenceTransformer
        if not hasattr(self, "_st_model"):
            self._st_model = SentenceTransformer("all-MiniLM-L6-v2")  # 384-dim, fast
        return self._st_model.encode(text).tolist()

    def product_text(self, product: Dict[str, Any]) -> str:
        """Build the text that represents a product for embedding."""
        parts = [
            product.get("name", ""),
            product.get("brand", ""),
            product.get("description", "")[:300],
            f"CPU: {product.get('cpu', '')}",
            f"RAM: {product.get('ram', '')}",
            f"Display: {product.get('display', '')}",
            f"Price: ${product.get('price', '')}",
            " ".join(product.get("tags", [])),
        ]
        return " | ".join(p for p in parts if p.strip())
```

---

## Step 4 — Catalog Indexing Script

**New file:** `scripts/index_catalog.py`

```python
#!/usr/bin/env python3
"""
Embed and index all products in pgvector.
Run: python scripts/index_catalog.py [--batch-size 50]
Also run nightly via Celery Beat to pick up new products.
"""
import asyncio, argparse, logging, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
log = logging.getLogger(__name__)

async def main(batch_size: int = 50):
    from src.app.db import get_async_session
    from src.app.services.vector_store import PgVectorStore
    from src.app.services.embedding_pipeline import EmbeddingPipeline
    from sqlalchemy import text

    store = PgVectorStore(table="products_vec")
    pipeline = EmbeddingPipeline()

    if pipeline._provider == "none":
        print("ERROR: No embedding provider configured.")
        print("Set OPENAI_API_KEY or: pip install sentence-transformers")
        sys.exit(1)

    async with get_async_session() as db:
        count_row = await db.execute(text("SELECT COUNT(*) FROM products"))
        total = count_row.scalar()
        print(f"Indexing {total} products...")

        offset = 0
        indexed = 0
        while offset < total:
            rows = await db.execute(
                text("SELECT id, name, brand, description, price, specs FROM products ORDER BY id LIMIT :lim OFFSET :off"),
                {"lim": batch_size, "off": offset}
            )
            products = [dict(r._mapping) for r in rows]
            if not products:
                break

            texts = [pipeline.product_text(p) for p in products]
            embeddings = await pipeline.embed_batch(texts)

            records = []
            for product, embedding in zip(products, embeddings):
                if embedding is None:
                    continue
                records.append((
                    str(product["id"]),
                    embedding,
                    {"name": product["name"], "brand": product["brand"], "price": float(product["price"] or 0)},
                ))

            result = await store.batch_index(records, table="products_vec")
            indexed += result["indexed"]
            if result["errors"]:
                log.warning("Batch errors: %s", result["errors"][:3])

            offset += batch_size
            print(f"  {min(offset, total)}/{total} products indexed...")

    print(f"Done. {indexed}/{total} products embedded and indexed.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch-size", type=int, default=50)
    args = parser.parse_args()
    asyncio.run(main(batch_size=args.batch_size))
```

---

## Step 5 — Wire Vector Search Into recommend.py

**File:** `src/app/routers/recommend.py`
**Insert:** Before or alongside the existing keyword SQL search

Find the product search block in `recommend.py` (look for the main SQL query building section, roughly around the area that builds product filters). Add:

```python
# recommend.py — add vector search alongside keyword search
from src.app.services.vector_store import PgVectorStore
from src.app.services.embedding_pipeline import EmbeddingPipeline

_vector_store = PgVectorStore(table="products_vec")
_embedder = EmbeddingPipeline()

async def _vector_search(
    query: str,
    constraints: Dict[str, Any],
    top_k: int = 20,
) -> List[Dict[str, Any]]:
    """Run semantic vector search, return list of {sku, similarity, payload}."""
    embedding = await _embedder.embed_text(query)
    if embedding is None:
        return []

    # Build filter from hard constraints (pgvector supports JSONB filter)
    filter_parts = []
    filter_params = {}
    if constraints.get("brand"):
        filter_parts.append("LOWER(payload->>'brand') = :brand")
        filter_params["brand"] = constraints["brand"].lower()
    if constraints.get("price_max"):
        filter_parts.append("(payload->>'price')::FLOAT <= :price_max")
        filter_params["price_max"] = float(constraints["price_max"])

    filter_sql = " AND ".join(filter_parts) if filter_parts else ""

    return await _vector_store.query_with_filter(
        embedding,
        table="products_vec",
        top_k=top_k,
        filter_sql=filter_sql,
        filter_params=filter_params,
    )


async def _merged_search(query: str, constraints: Dict, keyword_results: List) -> List:
    """
    Merge vector search + keyword search using Reciprocal Rank Fusion (RRF).
    RRF score = sum(1 / (rank + 60)) across all result lists.
    """
    vector_results = await _vector_search(query, constraints, top_k=20)

    # Build RRF score map
    rrf_scores: Dict[str, float] = {}
    K = 60   # RRF constant

    for rank, item in enumerate(keyword_results):
        sku = item.get("sku") or item.get("id")
        rrf_scores[sku] = rrf_scores.get(sku, 0) + 1.0 / (rank + K)

    for rank, item in enumerate(vector_results):
        sku = item.get("id")
        rrf_scores[sku] = rrf_scores.get(sku, 0) + (1.0 / (rank + K)) * item.get("similarity", 0.5)

    # Merge payloads — prefer keyword results (have full product data)
    sku_to_product = {
        (item.get("sku") or item.get("id")): item
        for item in keyword_results
    }
    # Add vector-only results (not in keyword results)
    for item in vector_results:
        sku = item.get("id")
        if sku not in sku_to_product:
            sku_to_product[sku] = item.get("payload", {})

    # Sort by RRF score
    ranked = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)
    return [sku_to_product[sku] for sku, _ in ranked if sku in sku_to_product]
```

**In the main recommendation handler, replace:**
```python
# BEFORE:
results = await _keyword_search(query, constraints)

# AFTER:
keyword_results = await _keyword_search(query, constraints)
results = await _merged_search(query, constraints, keyword_results)
```

---

## Step 6 — Graph Analytics API Endpoint

**File:** `src/app/routers/graph.py` (file likely exists — add endpoint)
**If graph router exists, extend it. Otherwise add to analytics router.**

```python
# In graph.py or analytics.py router

from src.app.analytics.graph_builder import build_graph
from src.app.services.neo4j_graph import Neo4jGraph

@router.get("/api/v1/analytics/fraud-rings")
async def get_fraud_rings(min_degree: int = 3, _=Depends(require_owner)):
    """
    Returns fraud ring candidates for the admin dashboard.
    Uses Neo4j if available, falls back to in-memory graph_builder.
    """
    neo4j = Neo4jGraph()

    if neo4j._enabled:
        # Pull ring candidates from Neo4j
        rings = await neo4j.get_ring_candidates(min_shared_nodes=min_degree)
        source = "neo4j"
    else:
        # Build from Postgres event data
        from src.app.db import get_async_session
        from sqlalchemy import text
        async with get_async_session() as db:
            rows = await db.execute(text("""
                SELECT account_id, device_fingerprint, shipping_address_hash,
                       payment_hash, ip_address
                FROM session_events
                WHERE created_at > NOW() - INTERVAL '30 days'
                LIMIT 10000
            """))
            events = [dict(r._mapping) for r in rows]
        graph_data = build_graph(events)
        rings = graph_data.get("ring_candidates", [])
        source = "in_memory"

    return {
        "ring_count": len(rings),
        "source": source,
        "plain_english": _rings_to_plain_english(rings),
        "rings": rings[:50],   # cap at 50 for UI
    }

def _rings_to_plain_english(rings: list) -> str:
    if not rings:
        return "No fraud ring patterns detected in the last 30 days."
    high_risk = [r for r in rings if r.get("degree", 0) >= 5]
    if high_risk:
        return (
            f"{len(high_risk)} high-risk account cluster{'s' if len(high_risk) > 1 else ''} detected — "
            f"groups of accounts sharing devices, addresses, or payment methods. "
            f"Largest cluster involves {max(r.get('degree', 0) for r in high_risk)} accounts."
        )
    return (
        f"{len(rings)} potential fraud cluster{'s' if len(rings) > 1 else ''} found. "
        f"These accounts share identifiers that may indicate coordinated abuse."
    )
```

---

## Step 7 — Semantic FAQ Matching (Replace Keyword Lookup)

**File:** `src/app/services/faq_v2.py`

The FAQ currently uses keyword matching. Replace with vector search:

```python
# faq_v2.py — new semantic resolve() method

async def resolve_semantic(self, query: str, top_k: int = 3) -> List[Dict]:
    """Find the most relevant FAQ entries using vector similarity."""
    from src.app.services.vector_store import PgVectorStore
    from src.app.services.embedding_pipeline import EmbeddingPipeline

    store = PgVectorStore(table="faq_embeddings")
    pipeline = EmbeddingPipeline()

    embedding = await pipeline.embed_text(query)
    if embedding is None:
        return self.resolve_keyword(query)   # graceful fallback

    results = await store.query_with_filter(embedding, table="faq_embeddings", top_k=top_k)

    return [
        {
            "question": r["payload"].get("question", ""),
            "answer": r["payload"].get("answer", ""),
            "similarity": r["similarity"],
            "category": r["payload"].get("category", ""),
        }
        for r in results
        if r["similarity"] >= 0.70   # minimum relevance threshold
    ]
```

**Index FAQ bank at startup:**
```python
# scripts/index_faqs.py or in app startup
async def index_faqs():
    from src.app.services.faq_bank import FAQ_ENTRIES
    from src.app.services.vector_store import PgVectorStore
    from src.app.services.embedding_pipeline import EmbeddingPipeline
    store = PgVectorStore(table="faq_embeddings")
    pipeline = EmbeddingPipeline()
    records = []
    for entry in FAQ_ENTRIES:
        emb = await pipeline.embed_text(entry["question"] + " " + entry["answer"][:200])
        if emb:
            records.append((entry["id"], emb, entry))
    await store.batch_index(records, table="faq_embeddings")
```

---

## Step 8 — Docker: Neo4j + pgvector Setup

**File:** `docker-compose.yml`

```yaml
  neo4j:
    image: neo4j:5.18-community
    environment:
      NEO4J_AUTH: "neo4j/${NEO4J_PASSWORD:-shopSquire_neo4j}"
      NEO4J_PLUGINS: '["apoc", "graph-data-science"]'
      NEO4J_dbms_memory_pagecache_size: "512M"
      NEO4J_dbms_memory_heap_initial__size: "512M"
      NEO4J_dbms_memory_heap_max__size: "1G"
    ports:
      - "7474:7474"  # Neo4j Browser
      - "7687:7687"  # Bolt protocol
    volumes:
      - neo4j_data:/data
      - neo4j_logs:/logs
    healthcheck:
      test: ["CMD", "neo4j", "status"]
      interval: 30s
      timeout: 10s
      retries: 5

  db:
    image: pgvector/pgvector:pg16   # Official pgvector image — replaces postgres:16
    environment:
      POSTGRES_DB: shopsquire
      POSTGRES_USER: shopsquire
      POSTGRES_PASSWORD: ${DB_PASSWORD}
    volumes:
      - postgres_data:/var/lib/postgresql/data
    command: >
      postgres
      -c shared_preload_libraries=vector
      -c max_connections=100
      -c shared_buffers=256MB

volumes:
  neo4j_data:
  neo4j_logs:
  postgres_data:
```

**Environment variables:**
```bash
# .env additions
FRAUD_GRAPH_NEO4J_ENABLED=1
NEO4J_URI=bolt://neo4j:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=shopSquire_neo4j
```

---

## Step 9 — Celery Tasks: Keep Graph + Embeddings Fresh

**File:** `src/app/tasks/` (create or extend)

```python
# src/app/tasks/graph_refresh.py
from src.app.worker import celery_app

@celery_app.task(name="graph.refresh_fraud_rings")
def refresh_fraud_rings():
    """Refresh Neo4j fraud ring graph from Postgres session events. Runs every 4h."""
    import asyncio
    from src.app.services.neo4j_graph import Neo4jGraph
    from src.app.db import get_sync_session
    from sqlalchemy import text

    neo4j = Neo4jGraph()
    if not neo4j._enabled:
        return {"skipped": True, "reason": "neo4j not configured"}

    with get_sync_session() as db:
        rows = db.execute(text("""
            SELECT account_id, device_fingerprint, shipping_address_hash, ip_address
            FROM session_events
            WHERE created_at > NOW() - INTERVAL '7 days'
        """)).fetchall()

    events_upserted = 0
    for row in rows:
        asyncio.run(neo4j.upsert_account_device_ip_event(dict(row._mapping)))
        events_upserted += 1

    return {"events_upserted": events_upserted}


@celery_app.task(name="catalog.reindex_new_products")
def reindex_new_products():
    """Index any products added since last run. Runs nightly."""
    import asyncio
    asyncio.run(_reindex_new())

async def _reindex_new():
    from src.app.db import get_async_session
    from src.app.services.vector_store import PgVectorStore
    from src.app.services.embedding_pipeline import EmbeddingPipeline
    from sqlalchemy import text

    store = PgVectorStore(table="products_vec")
    pipeline = EmbeddingPipeline()

    async with get_async_session() as db:
        rows = await db.execute(text("""
            SELECT p.id, p.name, p.brand, p.description, p.price
            FROM products p
            LEFT JOIN products_vec pv ON pv.id = p.id::TEXT
            WHERE pv.id IS NULL   -- only unindexed products
            ORDER BY p.created_at DESC
            LIMIT 500
        """))
        products = [dict(r._mapping) for r in rows]

    if not products:
        return

    texts = [pipeline.product_text(p) for p in products]
    embeddings = await pipeline.embed_batch(texts)
    records = [
        (str(p["id"]), emb, {"name": p["name"], "brand": p["brand"], "price": float(p["price"] or 0)})
        for p, emb in zip(products, embeddings) if emb is not None
    ]
    await store.batch_index(records, table="products_vec")
```

---

## Business Outcome

| Before | After |
|--------|-------|
| Search "gaming laptop" only returns products with the word "gaming" | Semantic search finds "esports", "high-performance", "RTX" — returns the right products even when user uses different vocabulary |
| FAQ keyword match: "screen wont turn on" → no match | Semantic FAQ: "display not responding" → matches "screen won't power on" with 0.87 similarity |
| Fraud rings require manual investigation | Dashboard: "3 accounts sharing device ID XR-884 and a Melbourne shipping address flagged for review" |
| Neo4j off by default → fraud ring signal always 0.0 | Neo4j always on in docker-compose → real ring signals from day 1 |
| New products not searchable until manual re-index | Celery nightly task keeps vector index < 24h stale |
| `graph_builder.build_graph()` exists but unreachable | `/api/v1/analytics/fraud-rings` endpoint returns plain-English risk summary + ring data |

---

## Rollout Order

```
Day 1:  Run alembic migration (pgvector extension + tables)
Day 2:  Change docker-compose.yml: postgres → pgvector/pgvector:pg16, add neo4j
Day 3:  Run scripts/index_catalog.py (initial embedding of product catalog)
Day 4:  Wire _merged_search() into recommend.py (feature flag: VECTOR_SEARCH_ENABLED=1)
Day 5:  Enable Neo4j (FRAUD_GRAPH_NEO4J_ENABLED=1) + run initial graph seed
Day 6:  Wire /api/v1/analytics/fraud-rings endpoint
Day 7:  Add Celery Beat tasks for nightly re-index + 4h graph refresh
Day 8:  Shadow-test: run vector + keyword in parallel, compare results for 48h
Day 9:  Switch to RRF merge as primary search
Day 10: Semantic FAQ active
```
