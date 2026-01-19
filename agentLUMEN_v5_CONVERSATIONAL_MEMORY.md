# agentLUMEN v5 - CONVERSATIONAL MEMORY + SCALE ARCHITECTURE
**6-Week MVP → Production-Ready E-Commerce Agent Platform**

---

## Slide 1: AGENTIC FLASHLIGHT CO

```
┌────────────────────────────────────────────────────────────────┐
│                         agentLUMEN                             │
│                   AGENTIC FLASHLIGHT CO                        │
│                                                                │
│        Agents handle routine operations                        │
│        Humans govern strategy, exceptions, and                 │
│             high-stakes decisions                              │
│                                                                │
│  CORE PRINCIPLE: Memory Hygiene > Model Learning               │
│  "Retrieve-then-answer" beats "remember-then-hallucinate"      │
└────────────────────────────────────────────────────────────────┘
```

---

## Slide 2: THE MEMORY PROBLEM (Why Chatbots Hallucinate)

```
┌─────────────────────────────────────────────────────────────────────────┐
│                   THE CONVERSATIONAL MEMORY PROBLEM                     │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  SYMPTOM: "Context Rot" After 10+ Turns                                │
│  ────────────────────────────────────────────────────────────           │
│                                                                         │
│  Turn 1:  "Show me laptops under $800"                                 │
│  Turn 2:  Agent retrieves 15 models (prices verified)                  │
│  Turn 3:  "What about RAM upgrade options?"                            │
│  Turn 4:  Agent retrieves specs (still accurate)                       │
│  ...                                                                    │
│  Turn 15: "What was the price of that Dell again?"                     │
│  Turn 16: Agent hallucinates "$749" (actually $799 now - sale ended)   │
│                                                                         │
│  WHY THIS HAPPENS:                                                      │
│  ────────────────────────────────────────────────────────────           │
│                                                                         │
│  ❌ WRONG APPROACH: Stuff entire transcript into prompt                │
│     • Context window fills up (8K → 16K → 32K tokens)                  │
│     • Model sees stale data ("$749" from Turn 2)                       │
│     • No forced re-verification of facts that can change               │
│     • Hallucinations increase after Turn 10+                           │
│                                                                         │
│  ✅ RIGHT APPROACH: Memory Hygiene + Retrieval Discipline              │
│     • Chat history ≠ source of truth (it's just conversation)          │
│     • Facts anchored to authoritative stores (DB, not transcript)      │
│     • Force "retrieve-then-answer" for anything that can change        │
│     • Rolling summary (not full transcript) for context                │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

**KEY INSIGHT**: You don't need "recursive learning" - you need **structured memory + forced retrieval**.

---

## Slide 3: THREE-TIER MEMORY ARCHITECTURE

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                     THREE-TIER MEMORY ARCHITECTURE                              │
│               (Solving Context Rot Without Model Fine-Tuning)                   │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│  TIER 0: IN-PROMPT (Last 6-12 Turns Only)                                      │
│  ────────────────────────────────────────────────────────────────────           │
│  • Natural conversational flow (keeps chat human)                               │
│  • Pruned to most recent exchanges                                              │
│  • Lightweight - doesn't grow unbounded                                         │
│                                                                                 │
│  Example:                                                                       │
│  ┌─────────────────────────────────────────────────────────────┐               │
│  │ User: "What about the Dell XPS?"                            │               │
│  │ Agent: "The Dell XPS 13 is $899 (verified live). Want specs?"│              │
│  │ User: "Yes, especially RAM options."                        │               │
│  │ Agent: [retrieving now...]                                  │               │
│  └─────────────────────────────────────────────────────────────┘               │
│                                                                                 │
│  ──────────────────────────────────────────────────────────────────────────    │
│                                                                                 │
│  TIER 1: REDIS SESSION CACHE (3h TTL)                                          │
│  ────────────────────────────────────────────────────────────────────           │
│  • Rolling summary (tight narrative, not full transcript)                       │
│  • Key-Value state (authoritative conversation state)                           │
│  • Recent retrieval results (cached for session)                                │
│                                                                                 │
│  Redis Keys:                                                                    │
│  ┌─────────────────────────────────────────────────────────────┐               │
│  │ session:{user_id}:summary                                   │               │
│  │ → "User wants laptop <$800, 16GB RAM, for coding.           │               │
│  │    Shortlisted: Dell XPS, Lenovo ThinkPad.                  │               │
│  │    Budget constraint: strict. Shipping: 2-day needed."      │               │
│  │                                                              │               │
│  │ session:{user_id}:kv_state                                  │               │
│  │ → {                                                          │               │
│  │     "budget_max": 800,                                       │               │
│  │     "must_haves": ["16GB RAM", "SSD"],                       │               │
│  │     "excluded_brands": ["Acer"],                             │               │
│  │     "shipping_country": "US",                                │               │
│  │     "draft_cart_id": "cart_abc123"                           │               │
│  │   }                                                          │               │
│  │                                                              │               │
│  │ session:{user_id}:recent_retrieval                          │               │
│  │ → [cached product docs, last 3 searches]                    │               │
│  └─────────────────────────────────────────────────────────────┘               │
│                                                                                 │
│  ──────────────────────────────────────────────────────────────────────────    │
│                                                                                 │
│  TIER 2: VECTOR STORE (Semantic Memory - CacheRAG)                             │
│  ────────────────────────────────────────────────────────────────────           │
│  • Product catalog (specs, descriptions, compatibility)                         │
│  • Policies (return policy, warranty, shipping rules)                           │
│  • FAQs + support knowledge base                                                │
│  • Similarity search for "find laptops like this"                               │
│                                                                                 │
│  Storage: QDrant or Pinecone                                                    │
│  Cache Strategy: Cache retrieval results (not raw embeddings)                   │
│                                                                                 │
│  ──────────────────────────────────────────────────────────────────────────    │
│                                                                                 │
│  TIER 3: BI-TEMPORAL DECISION LOG (Immutable Audit Trail)                      │
│  ────────────────────────────────────────────────────────────────────           │
│  • What AI knew at decision time (temporal provenance)                          │
│  • What evidence was retrieved (RAG results logged)                             │
│  • What action was taken (order placed, discount applied)                       │
│  • What policy version applied (for compliance)                                 │
│                                                                                 │
│  Storage: PostgreSQL with temporal columns                                      │
│  Purpose: Regulatory compliance, debugging, model improvement                   │
│                                                                                 │
│  ──────────────────────────────────────────────────────────────────────────    │
│                                                                                 │
│  KEY RULE: Chat history (Tier 0) ≠ Truth.                                      │
│            Truth lives in Tier 1 (KV state) + Tier 2 (catalog) + Tier 3 (logs) │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

## Slide 4: MEMORY PATTERN (How It Works Per Turn)

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                    CONVERSATIONAL TURN FLOW (WITH MEMORY)                       │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│  USER INPUT: "What's the price of that Dell laptop?"                           │
│                                                                                 │
│  ┌────────────────────────────────────────────────────────────────────┐        │
│  │ STAGE 1: RETRIEVE SESSION STATE                                   │        │
│  ├────────────────────────────────────────────────────────────────────┤        │
│  │ Redis GET session:{user_id}:summary                                │        │
│  │ Redis GET session:{user_id}:kv_state                               │        │
│  │                                                                    │        │
│  │ Result:                                                            │        │
│  │ • Summary: "User shortlisted Dell XPS 13, Lenovo ThinkPad"        │        │
│  │ • KV State: {"budget_max": 800, "draft_cart_id": "cart_abc123"}   │        │
│  └────────────────────────────────────────────────────────────────────┘        │
│                     │                                                           │
│                     ▼                                                           │
│  ┌────────────────────────────────────────────────────────────────────┐        │
│  │ STAGE 2: IDENTIFY INTENT + EXTRACT ENTITY                         │        │
│  ├────────────────────────────────────────────────────────────────────┤        │
│  │ Intent: price_inquiry                                              │        │
│  │ Entity: "Dell laptop" → likely "Dell XPS 13" from summary          │        │
│  │                                                                    │        │
│  │ Decision: Need LIVE PRICE (must retrieve, not use cached)         │        │
│  └────────────────────────────────────────────────────────────────────┘        │
│                     │                                                           │
│                     ▼                                                           │
│  ┌────────────────────────────────────────────────────────────────────┐        │
│  │ STAGE 3: FORCED RETRIEVAL (NEVER TRUST MEMORY FOR PRICE)          │        │
│  ├────────────────────────────────────────────────────────────────────┤        │
│  │ Query: SELECT price, stock FROM products                           │        │
│  │        WHERE name LIKE '%Dell XPS 13%' AND active=true             │        │
│  │                                                                    │        │
│  │ Result: {"price": 899, "stock": 12, "last_updated": "now"}        │        │
│  │                                                                    │        │
│  │ WHY THIS MATTERS: Price changed from $849 (session start)          │        │
│  │                  to $899 (sale ended 30 min ago)                   │        │
│  └────────────────────────────────────────────────────────────────────┘        │
│                     │                                                           │
│                     ▼                                                           │
│  ┌────────────────────────────────────────────────────────────────────┐        │
│  │ STAGE 4: GENERATE RESPONSE (WITH EVIDENCE)                         │        │
│  ├────────────────────────────────────────────────────────────────────┤        │
│  │ Prompt to LLM:                                                     │        │
│  │ "User asked about Dell laptop price.                               │        │
│  │  Context: {summary}                                                │        │
│  │  Current price: $899 (verified live from DB)                       │        │
│  │  Stock: 12 units available                                         │        │
│  │  User's budget: $800 (from KV state)                               │        │
│  │                                                                    │        │
│  │  Respond naturally but mention price exceeds budget."              │        │
│  │                                                                    │        │
│  │ LLM Output:                                                        │        │
│  │ "The Dell XPS 13 is currently $899 (I just checked).               │        │
│  │  That's $99 over your $800 budget. Would you like me to            │        │
│  │  find alternatives, or shall I check if there's a coupon?"         │        │
│  └────────────────────────────────────────────────────────────────────┘        │
│                     │                                                           │
│                     ▼                                                           │
│  ┌────────────────────────────────────────────────────────────────────┐        │
│  │ STAGE 5: UPDATE SESSION STATE (ROLLING SUMMARY)                   │        │
│  ├────────────────────────────────────────────────────────────────────┤        │
│  │ Redis SET session:{user_id}:summary (update)                       │        │
│  │ → "User wants laptop <$800. Dell XPS 13 is $899 (over budget).     │        │
│  │    Considering alternatives or coupon."                            │        │
│  │                                                                    │        │
│  │ Redis SET session:{user_id}:recent_retrieval                       │        │
│  │ → [cache the DB result for 5min in case user asks again]           │        │
│  └────────────────────────────────────────────────────────────────────┘        │
│                     │                                                           │
│                     ▼                                                           │
│  ┌────────────────────────────────────────────────────────────────────┐        │
│  │ STAGE 6: LOG DECISION (BI-TEMPORAL)                                │        │
│  ├────────────────────────────────────────────────────────────────────┤        │
│  │ PostgreSQL INSERT INTO decision_logs:                               │        │
│  │ {                                                                  │        │
│  │   "agent_name": "conversation_agent",                              │        │
│  │   "input_data": {"user_query": "What's the price..."},             │        │
│  │   "retrieved_context": {"price": 899, "source": "DB"},             │        │
│  │   "agent_reasoning": "Price exceeds budget, offered alternatives", │        │
│  │   "proposed_action": null,  // Just info query, no action          │        │
│  │   "policy_version": "v1.2",                                        │        │
│  │   "valid_from": "2025-01-19 15:42:00"                              │        │
│  │ }                                                                  │        │
│  └────────────────────────────────────────────────────────────────────┘        │
│                                                                                 │
│  RESULT: User gets ACCURATE price ($899) not HALLUCINATED ($849)               │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

**CRITICAL RULE**: Any claim about price, stock, specs, delivery, promos → FORCED RETRIEVAL

---

## Slide 5: REDIS SCALING STRATEGY (100K+ Concurrent Users)

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                   REDIS SCALING ARCHITECTURE (100K+ USERS)                      │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│  CHALLENGE: 100,000 concurrent sessions × 3h TTL = massive memory footprint    │
│                                                                                 │
│  NAIVE APPROACH (WILL FAIL):                                                    │
│  ────────────────────────────────────────────────────────────────────           │
│  • Single Redis instance (16GB RAM)                                             │
│  • 100K sessions × 50KB/session = 5GB active sessions                           │
│  • + retrieval cache + vector embeddings = 10GB total                           │
│  • Problem: Out of memory after 30K users, no redundancy                        │
│                                                                                 │
│  ──────────────────────────────────────────────────────────────────────────    │
│                                                                                 │
│  PRODUCTION STRATEGY: REDIS CLUSTER + SHARDING                                  │
│  ────────────────────────────────────────────────────────────────────           │
│                                                                                 │
│  ┌───────────────────────────────────────────────────────────────────────┐     │
│  │ REDIS CLUSTER (3 Master + 3 Replica Nodes)                           │     │
│  ├───────────────────────────────────────────────────────────────────────┤     │
│  │                                                                       │     │
│  │  SHARD 1 (Master + Replica)         Hash Slots: 0-5461               │     │
│  │  ┌─────────────────────────┐         ┌─────────────────────────┐     │     │
│  │  │ Master 1 (16GB)         │────────▶│ Replica 1 (16GB)        │     │     │
│  │  │ • session:user_0000-4999│         │ • Read-only failover    │     │     │
│  │  │ • 33% of sessions       │         │ • Automatic promotion   │     │     │
│  │  └─────────────────────────┘         └─────────────────────────┘     │     │
│  │                                                                       │     │
│  │  SHARD 2 (Master + Replica)         Hash Slots: 5462-10922           │     │
│  │  ┌─────────────────────────┐         ┌─────────────────────────┐     │     │
│  │  │ Master 2 (16GB)         │────────▶│ Replica 2 (16GB)        │     │     │
│  │  │ • session:user_5000-9999│         │ • Read-only failover    │     │     │
│  │  │ • 33% of sessions       │         │ • Automatic promotion   │     │     │
│  │  └─────────────────────────┘         └─────────────────────────┘     │     │
│  │                                                                       │     │
│  │  SHARD 3 (Master + Replica)         Hash Slots: 10923-16383          │     │
│  │  ┌─────────────────────────┐         ┌─────────────────────────┐     │     │
│  │  │ Master 3 (16GB)         │────────▶│ Replica 3 (16GB)        │     │     │
│  │  │ • session:user_10000+   │         │ • Read-only failover    │     │     │
│  │  │ • 34% of sessions       │         │ • Automatic promotion   │     │     │
│  │  └─────────────────────────┘         └─────────────────────────┘     │     │
│  │                                                                       │     │
│  │  CAPACITY: 3 × 16GB = 48GB total                                     │     │
│  │  REDUNDANCY: Each shard has replica for failover                     │     │
│  │  SCALABILITY: Add more shards horizontally as traffic grows          │     │
│  │                                                                       │     │
│  └───────────────────────────────────────────────────────────────────────┘     │
│                                                                                 │
│  ──────────────────────────────────────────────────────────────────────────    │
│                                                                                 │
│  KEY OPTIMIZATION: MEMORY EVICTION POLICIES                                     │
│  ────────────────────────────────────────────────────────────────────           │
│                                                                                 │
│  # redis.conf settings                                                          │
│  maxmemory 16gb                                                                 │
│  maxmemory-policy allkeys-lru  # Evict least recently used keys                │
│                                                                                 │
│  # What to cache (by priority):                                                │
│  Priority 1: Session KV state (critical, longer TTL: 3h)                        │
│  Priority 2: Rolling summary (important, 3h TTL)                                │
│  Priority 3: Recent retrieval results (nice-to-have, 5min TTL)                  │
│                                                                                 │
│  # What NOT to cache in Redis:                                                  │
│  ❌ Full conversation transcripts (use Tier 0 in-memory)                        │
│  ❌ Product catalog (use PostgreSQL + vector DB)                                │
│  ❌ Decision logs (use PostgreSQL bi-temporal table)                            │
│                                                                                 │
│  ──────────────────────────────────────────────────────────────────────────    │
│                                                                                 │
│  COST ANALYSIS (AWS ElastiCache):                                               │
│  ────────────────────────────────────────────────────────────────────           │
│                                                                                 │
│  Instance Type: cache.r7g.xlarge (16GB RAM, 4 vCPU)                             │
│  • 3 Masters × $0.302/hour = $0.906/hour                                        │
│  • 3 Replicas × $0.302/hour = $0.906/hour                                       │
│  • Total: ~$1.81/hour = $1,300/month                                            │
│                                                                                 │
│  Capacity: 100K-150K concurrent sessions                                        │
│  Cost per session: $0.01/month                                                  │
│                                                                                 │
│  ──────────────────────────────────────────────────────────────────────────    │
│                                                                                 │
│  AUTOSCALING TRIGGERS:                                                          │
│  ────────────────────────────────────────────────────────────────────           │
│                                                                                 │
│  Scale Out (Add Shard):                                                         │
│  • Memory usage >80% across all masters                                         │
│  • Connection count >10K per shard                                              │
│  • Latency p99 >5ms                                                             │
│                                                                                 │
│  Scale In (Remove Shard):                                                       │
│  • Memory usage <40% across all masters                                         │
│  • Sustained for >30 minutes                                                    │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

## Slide 6: LOG STORAGE ARCHITECTURE (HOT/WARM/COLD TIERS)

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                    AGENTIC LOG STORAGE (TIERED STRATEGY)                        │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│  PROBLEM: Decision logs grow unbounded (1M decisions/day × 1KB/log = 1GB/day)  │
│                                                                                 │
│  SOLUTION: Hot/Warm/Cold Storage Tiers                                          │
│                                                                                 │
│  ┌───────────────────────────────────────────────────────────────────────┐     │
│  │ HOT TIER (Last 7 Days - High Performance)                            │     │
│  ├───────────────────────────────────────────────────────────────────────┤     │
│  │                                                                       │     │
│  │  Storage: PostgreSQL (OLTP - SSD)                                    │     │
│  │  Location: Colocation (low latency <10ms)                            │     │
│  │  Retention: 7 days                                                   │     │
│  │  Query Pattern: Real-time decision lookups, debugging                │     │
│  │                                                                       │     │
│  │  Schema:                                                             │     │
│  │  ┌─────────────────────────────────────────────────────────┐         │     │
│  │  │ decision_logs_hot                                       │         │     │
│  │  ├─────────────────────────────────────────────────────────┤         │     │
│  │  │ id UUID PRIMARY KEY                                     │         │     │
│  │  │ agent_name TEXT                                         │         │     │
│  │  │ valid_from TIMESTAMPTZ (indexed)                        │         │     │
│  │  │ valid_to TIMESTAMPTZ                                    │         │     │
│  │  │ system_from TIMESTAMPTZ (indexed)                       │         │     │
│  │  │ system_to TIMESTAMPTZ                                   │         │     │
│  │  │ input_data JSONB                                        │         │     │
│  │  │ retrieved_context JSONB                                 │         │     │
│  │  │ agent_reasoning TEXT                                    │         │     │
│  │  │ proposed_action JSONB                                   │         │     │
│  │  │ policy_version TEXT                                     │         │     │
│  │  │ execution_status TEXT                                   │         │     │
│  │  │ created_at TIMESTAMPTZ DEFAULT NOW()                    │         │     │
│  │  └─────────────────────────────────────────────────────────┘         │     │
│  │                                                                       │     │
│  │  Size: ~7GB (1M decisions/day × 1KB × 7 days)                        │     │
│  │  Cost: $50/month (PostgreSQL RDS r6g.large)                          │     │
│  │                                                                       │     │
│  └───────────────────────────────────────────────────────────────────────┘     │
│                            │                                                    │
│                            │ Nightly ETL (archive old logs)                     │
│                            ▼                                                    │
│  ┌───────────────────────────────────────────────────────────────────────┐     │
│  │ WARM TIER (8-90 Days - Analytical Queries)                           │     │
│  ├───────────────────────────────────────────────────────────────────────┤     │
│  │                                                                       │     │
│  │  Storage: BigQuery (OLAP - Columnar)                                 │     │
│  │  Location: Cloud (GCP or AWS Redshift)                               │     │
│  │  Retention: 90 days                                                  │     │
│  │  Query Pattern: Analytics, RAGAS evaluation, compliance audits       │     │
│  │                                                                       │     │
│  │  Schema (Partitioned by date):                                       │     │
│  │  ┌─────────────────────────────────────────────────────────┐         │     │
│  │  │ decision_logs_warm                                      │         │     │
│  │  ├─────────────────────────────────────────────────────────┤         │     │
│  │  │ PARTITIONED BY DATE(created_at)                         │         │     │
│  │  │                                                         │         │     │
│  │  │ All fields from hot tier                                │         │     │
│  │  │ + aggregated metrics (computed during ETL):             │         │     │
│  │  │   - avg_confidence FLOAT                                │         │     │
│  │  │   - error_count INT                                     │         │     │
│  │  │   - approval_rate FLOAT                                 │         │     │
│  │  └─────────────────────────────────────────────────────────┘         │     │
│  │                                                                       │     │
│  │  Size: ~90GB (compressed columnar)                                   │     │
│  │  Cost: $5/month storage + $20/month query (on-demand)                │     │
│  │                                                                       │     │
│  └───────────────────────────────────────────────────────────────────────┘     │
│                            │                                                    │
│                            │ Monthly archival                                   │
│                            ▼                                                    │
│  ┌───────────────────────────────────────────────────────────────────────┐     │
│  │ COLD TIER (90+ Days - Long-Term Compliance)                          │     │
│  ├───────────────────────────────────────────────────────────────────────┤     │
│  │                                                                       │     │
│  │  Storage: S3 Glacier (Archive)                                       │     │
│  │  Location: Cloud (multi-region replication)                          │     │
│  │  Retention: 7 years (regulatory requirement)                         │     │
│  │  Query Pattern: Rare - only for audits, litigation                   │     │
│  │                                                                       │     │
│  │  Format: Parquet files (compressed, columnar)                        │     │
│  │  Encryption: AES-256 (at rest)                                       │     │
│  │                                                                       │     │
│  │  File Structure:                                                     │     │
│  │  s3://agentlumen-logs/                                               │     │
│  │  ├── year=2025/                                                      │     │
│  │  │   ├── month=01/                                                   │     │
│  │  │   │   ├── day=01/                                                 │     │
│  │  │   │   │   └── logs_20250101.parquet.gz                            │     │
│  │  │   │   ├── day=02/                                                 │     │
│  │  │   │   │   └── logs_20250102.parquet.gz                            │     │
│  │  │   │   ...                                                         │     │
│  │                                                                       │     │
│  │  Size: ~3TB (7 years × 365 days × 1GB/day compressed)                │     │
│  │  Cost: $10/month (Glacier Deep Archive $0.00099/GB/month)            │     │
│  │                                                                       │     │
│  │  Retrieval: 12-48 hours (on-demand, for audits)                      │     │
│  │                                                                       │     │
│  └───────────────────────────────────────────────────────────────────────┘     │
│                                                                                 │
│  ──────────────────────────────────────────────────────────────────────────    │
│                                                                                 │
│  TOTAL COST (1M Decisions/Day):                                                 │
│  ────────────────────────────────────────────────────────────────────           │
│  • Hot (7 days): $50/month                                                      │
│  • Warm (90 days): $25/month                                                    │
│  • Cold (7 years): $10/month                                                    │
│  • TOTAL: $85/month for complete audit trail                                    │
│                                                                                 │
│  Cost per decision: $0.000085 (~$0.0001)                                        │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

## Slide 7: 6-WEEK MVP vs END-STATE COMPARISON

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                         6-WEEK MVP vs END-STATE                                 │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│  ┌───────────────────────────────────────┬───────────────────────────────────┐ │
│  │ 6-WEEK MVP (MINIMAL VIABLE)           │ END-STATE (PRODUCTION SCALE)      │ │
│  ├───────────────────────────────────────┼───────────────────────────────────┤ │
│  │                                       │                                   │ │
│  │ ORCHESTRATOR                          │ ORCHESTRATOR                      │ │
│  │ ───────────────────────────────────   │ ───────────────────────────────   │ │
│  │ • Python state machine (simple)       │ • Temporal.io workflow engine     │ │
│  │ • Single agent (pricing OR support)   │ • Multi-agent mesh (5-10 agents)  │ │
│  │ • Synchronous execution               │ • Async + event-driven            │ │
│  │                                       │ • Agent-to-agent coordination     │ │
│  │                                       │                                   │ │
│  ├───────────────────────────────────────┼───────────────────────────────────┤ │
│  │                                       │                                   │ │
│  │ MEMORY (CONVERSATIONAL)               │ MEMORY (CONVERSATIONAL)           │ │
│  │ ───────────────────────────────────   │ ───────────────────────────────   │ │
│  │ • Single Redis instance (4GB)         │ • Redis Cluster (3 shards, 48GB) │ │
│  │ • Rolling summary + KV state          │ • Same pattern, scaled out        │ │
│  │ • No vector DB (PostgreSQL FTS)       │ • QDrant/Pinecone (semantic)      │ │
│  │ • 3h session TTL                      │ • 3h session TTL (same)           │ │
│  │ • Capacity: 5K concurrent sessions    │ • Capacity: 100K+ sessions        │ │
│  │                                       │                                   │ │
│  ├───────────────────────────────────────┼───────────────────────────────────┤ │
│  │                                       │                                   │ │
│  │ STORAGE (LOGS)                        │ STORAGE (LOGS)                    │ │
│  │ ───────────────────────────────────   │ ───────────────────────────────   │ │
│  │ • PostgreSQL only (hot tier)          │ • Hot/Warm/Cold tiers             │ │
│  │ • 7-day retention                     │ • 7-year retention                │ │
│  │ • No archival                         │ • S3 Glacier archival             │ │
│  │ • Manual exports for audits           │ • Automated compliance exports    │ │
│  │                                       │                                   │ │
│  ├───────────────────────────────────────┼───────────────────────────────────┤ │
│  │                                       │                                   │ │
│  │ TRANSACTION FIREWALL                  │ TRANSACTION FIREWALL              │ │
│  │ ───────────────────────────────────   │ ───────────────────────────────   │ │
│  │ • Hardcoded Python functions          │ • OPA (Open Policy Agent)         │ │
│  │ • Basic rules (if/then)               │ • ABAC policies (attribute-based) │ │
│  │ • >$250 → human approval              │ • Dynamic thresholds              │ │
│  │ • No policy versioning                │ • Policy version control          │ │
│  │                                       │                                   │ │
│  ├───────────────────────────────────────┼───────────────────────────────────┤ │
│  │                                       │                                   │ │
│  │ SECURITY OBSERVER                     │ SECURITY OBSERVER                 │ │
│  │ ───────────────────────────────────   │ ───────────────────────────────   │ │
│  │ • Basic regex prompt injection        │ • ML classifier (BERT-based)      │ │
│  │ • Manual log review                   │ • MITRE ATLAS threat taxonomy     │ │
│  │ • Slack alerts                        │ • Automated threat scoring        │ │
│  │ • No anomaly detection                │ • Anomaly detection (Arize)       │ │
│  │                                       │                                   │ │
│  ├───────────────────────────────────────┼───────────────────────────────────┤ │
│  │                                       │                                   │ │
│  │ DEPLOYMENT                            │ DEPLOYMENT                        │ │
│  │ ───────────────────────────────────   │ ───────────────────────────────   │ │
│  │ • Single cloud region (AWS/GCP)       │ • Hybrid colo + cloud             │ │
│  │ • Docker Compose                      │ • Kubernetes (multi-region)       │ │
│  │ • No VPC isolation                    │ • 3 VPCs (public/control/data)    │ │
│  │ • Shared subnet                       │ • Microsegmented (zero-trust)     │ │
│  │ • Manual scaling                      │ • Autoscaling (HPA)               │ │
│  │                                       │                                   │ │
│  ├───────────────────────────────────────┼───────────────────────────────────┤ │
│  │                                       │                                   │ │
│  │ INTEGRATIONS                          │ INTEGRATIONS                      │ │
│  │ ───────────────────────────────────   │ ───────────────────────────────   │ │
│  │ • Shopify plugin (pricing agent)      │ • Multi-platform (Shopify,        │ │
│  │ • Stripe webhooks                     │   WooCommerce, Magento)           │ │
│  │ • Basic email notifications           │ • Full event mesh (Kafka)         │ │
│  │                                       │ • Advanced webhooks + SSE         │ │
│  │                                       │                                   │ │
│  ├───────────────────────────────────────┼───────────────────────────────────┤ │
│  │                                       │                                   │ │
│  │ OBSERVABILITY                         │ OBSERVABILITY                     │ │
│  │ ───────────────────────────────────   │ ───────────────────────────────   │ │
│  │ • Basic logging (stdout)              │ • DataDog APM + SIEM              │ │
│  │ • Google Sheets dashboards            │ • PowerBI dashboards              │ │
│  │ • Manual RAGAS evaluation             │ • Automated RAGAS (nightly)       │ │
│  │ • No distributed tracing              │ • OpenTelemetry tracing           │ │
│  │                                       │                                   │ │
│  ├───────────────────────────────────────┼───────────────────────────────────┤ │
│  │                                       │                                   │ │
│  │ COMPLIANCE                            │ COMPLIANCE                        │ │
│  │ ───────────────────────────────────   │ ───────────────────────────────   │ │
│  │ • Bi-temporal logging (basic)         │ • Full audit trail (7 years)      │ │
│  │ • Manual compliance exports           │ • ISO 42001 certification         │ │
│  │ • CSV decision logs                   │ • EU AI Act Article 17 ready      │ │
│  │ • No policy mapping                   │ • NIST AI RMF mapping             │ │
│  │                                       │                                   │ │
│  ├───────────────────────────────────────┼───────────────────────────────────┤ │
│  │                                       │                                   │ │
│  │ AUTONOMY                              │ AUTONOMY                          │ │
│  │ ───────────────────────────────────   │ ───────────────────────────────   │ │
│  │ • 20% (shadow mode → 50% by Week 6)   │ • 80% (mature agents)             │ │
│  │ • <$100 auto-approve                  │ • <$1000 auto-approve             │ │
│  │ • Human queue always available        │ • Same (always human fallback)    │ │
│  │                                       │                                   │ │
│  ├───────────────────────────────────────┼───────────────────────────────────┤ │
│  │                                       │                                   │ │
│  │ TEAM                                  │ TEAM                              │ │
│  │ ───────────────────────────────────   │ ───────────────────────────────   │ │
│  │ • 1-2 engineers (you + contractor)    │ • 5-7 engineers + ops             │ │
│  │ • Part-time security advisor          │ • Full-time security team         │ │
│  │                                       │                                   │ │
│  ├───────────────────────────────────────┼───────────────────────────────────┤ │
│  │                                       │                                   │ │
│  │ COST                                  │ COST                              │ │
│  │ ───────────────────────────────────   │ ───────────────────────────────   │ │
│  │ • Infrastructure: $500/month          │ • Infrastructure: $5K-$10K/month  │ │
│  │   - Cloud compute: $300               │   - Colo: $2K                     │ │
│  │   - Redis: $50                        │   - Cloud: $3K                    │ │
│  │   - PostgreSQL: $50                   │   - Redis Cluster: $1.3K          │ │
│  │   - LLM API: $100                     │   - PostgreSQL HA: $500           │ │
│  │                                       │   - Vector DB: $500               │ │
│  │ • Team: $10K/month (contractors)      │   - LLM API: $2K-$5K              │ │
│  │                                       │   - Monitoring: $500              │ │
│  │ • TOTAL: ~$10.5K/month                │                                   │ │
│  │                                       │ • Team: $50K-$70K/month (FTE)     │ │
│  │                                       │                                   │ │
│  │                                       │ • TOTAL: ~$55K-$80K/month         │ │
│  │                                       │                                   │ │
│  └───────────────────────────────────────┴───────────────────────────────────┘ │
│                                                                                 │
│  MIGRATION PATH: Start with MVP, gradually upgrade components as traffic grows  │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

## Slide 8: CONVERSATIONAL MEMORY (CART AS CANONICAL STATE)

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                 CART/WORKFLOW AS CANONICAL STATE (NO DRIFT)                     │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│  PRINCIPLE: The draft cart/order IS the memory, not the chat transcript        │
│                                                                                 │
│  ┌───────────────────────────────────────────────────────────────────────┐     │
│  │ TRADITIONAL APPROACH (BAD - LEADS TO DRIFT)                           │     │
│  ├───────────────────────────────────────────────────────────────────────┤     │
│  │                                                                       │     │
│  │ Turn 1:  "Add 2 MacBook Pros to cart"                                │     │
│  │          [Agent updates internal state: cart = {macbook: 2}]          │     │
│  │                                                                       │     │
│  │ Turn 5:  "Actually, make it 3"                                       │     │
│  │          [Agent updates internal state: cart = {macbook: 3}]          │     │
│  │                                                                       │     │
│  │ Turn 10: "What's in my cart?"                                        │     │
│  │          [Agent hallucinates: "2 MacBook Pros" - forgot update!]     │     │
│  │                                                                       │     │
│  │ WHY IT FAILS: State lives only in chat context, which gets pruned     │     │
│  │                                                                       │     │
│  └───────────────────────────────────────────────────────────────────────┘     │
│                                                                                 │
│  ┌───────────────────────────────────────────────────────────────────────┐     │
│  │ AGENTLUMEN APPROACH (GOOD - CART IS SOURCE OF TRUTH)                 │     │
│  ├───────────────────────────────────────────────────────────────────────┤     │
│  │                                                                       │     │
│  │ Turn 1:  "Add 2 MacBook Pros to cart"                                │     │
│  │          [Create Draft Order in DB]                                   │     │
│  │          PostgreSQL INSERT:                                           │     │
│  │          {                                                            │     │
│  │            "draft_order_id": "draft_abc123",                          │     │
│  │            "user_id": "user_456",                                     │     │
│  │            "line_items": [                                            │     │
│  │              {"sku": "MACBOOK_PRO_16", "quantity": 2, "price": 2499}  │     │
│  │            ],                                                         │     │
│  │            "status": "draft",                                         │     │
│  │            "created_at": "2025-01-19 15:00:00"                        │     │
│  │          }                                                            │     │
│  │                                                                       │     │
│  │          Redis SET session:{user_id}:kv_state                         │     │
│  │          {"draft_cart_id": "draft_abc123"}                            │     │
│  │                                                                       │     │
│  │ Turn 5:  "Actually, make it 3"                                       │     │
│  │          [Update Draft Order in DB]                                   │     │
│  │          PostgreSQL UPDATE:                                           │     │
│  │          SET line_items[0].quantity = 3                               │     │
│  │          WHERE draft_order_id = 'draft_abc123'                        │     │
│  │                                                                       │     │
│  │ Turn 10: "What's in my cart?"                                        │     │
│  │          [Query Draft Order from DB - ALWAYS CORRECT]                 │     │
│  │          PostgreSQL SELECT:                                           │     │
│  │          FROM draft_orders WHERE draft_order_id = 'draft_abc123'      │     │
│  │                                                                       │     │
│  │          Result: "3 MacBook Pro 16-inch ($2,499 each) = $7,497"       │     │
│  │                                                                       │     │
│  │ WHY IT WORKS: Draft order is canonical, chat is just interface        │     │
│  │                                                                       │     │
│  └───────────────────────────────────────────────────────────────────────┘     │
│                                                                                 │
│  ──────────────────────────────────────────────────────────────────────────    │
│                                                                                 │
│  AGENT ALWAYS ANSWERS FROM: draft_order + live_catalog + user_constraints      │
│                                                                                 │
│  ┌─────────────────────────────────────────────────────────────┐               │
│  │ Query Pattern (Every Turn):                                │               │
│  ├─────────────────────────────────────────────────────────────┤               │
│  │                                                             │               │
│  │ 1. Redis GET session:{user_id}:kv_state                     │               │
│  │    → {"draft_cart_id": "draft_abc123", "budget": 10000}     │               │
│  │                                                             │               │
│  │ 2. PostgreSQL SELECT FROM draft_orders                      │               │
│  │    WHERE draft_order_id = 'draft_abc123'                    │               │
│  │    → Current cart contents (canonical state)                │               │
│  │                                                             │               │
│  │ 3. PostgreSQL SELECT FROM products                          │               │
│  │    WHERE sku IN (cart_skus)                                 │               │
│  │    → Live prices, stock, specs (verify against catalog)     │               │
│  │                                                             │               │
│  │ 4. LLM Call with grounded data:                             │               │
│  │    Prompt: "User has 3 MacBook Pros ($7,497 total).         │               │
│  │             Budget: $10,000. Stock: 15 units available.     │               │
│  │             Respond to: [user query]"                       │               │
│  │                                                             │               │
│  │ Result: Agent can NEVER hallucinate cart contents           │               │
│  │                                                             │               │
│  └─────────────────────────────────────────────────────────────┘               │
│                                                                                 │
│  ──────────────────────────────────────────────────────────────────────────    │
│                                                                                 │
│  INTEGRATION WITH TRANSACTION FIREWALL                                          │
│  ────────────────────────────────────────────────────────────────────           │
│                                                                                 │
│  When agent proposes "Place order":                                             │
│                                                                                 │
│  1. Agent: "User wants to checkout draft_abc123"                                │
│  2. Firewall: Query draft order, check policies                                 │
│     - Total < $10,000? ✓ (within budget)                                        │
│     - Stock available? ✓ (15 units > 3 requested)                               │
│     - Fraud signals? ✗ (clean)                                                  │
│     - Requires approval? → Check threshold                                      │
│       - If total < $250: Auto-approve                                           │
│       - If total >= $250: Human review                                          │
│                                                                                 │
│  3a. If auto-approved: Convert draft → real order                               │
│      PostgreSQL UPDATE: SET status = 'pending_payment'                          │
│      Trigger Stripe payment intent                                              │
│                                                                                 │
│  3b. If human review: Queue for approval                                        │
│      Slack notification: "Order $7,497 needs approval"                          │
│      Draft stays in DB until approved                                           │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

**CRITICAL**: Cart/draft order is the ONLY source of truth, not chat memory

---

## Slide 9: LEVERAGING JANUSEC + CHATBOT PATTERNS

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│              HOW YOUR EXISTING PROJECTS MAP TO AGENTLUMEN                       │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│  ┌───────────────────────────────────────────────────────────────────────┐     │
│  │ FROM JANUSEC (AI-Powered XDR Platform)                               │     │
│  ├───────────────────────────────────────────────────────────────────────┤     │
│  │                                                                       │     │
│  │  JanuSec Component         →  agentLUMEN Equivalent                  │     │
│  │  ────────────────────────────────────────────────────────────────     │     │
│  │                                                                       │     │
│  │  21-stage detection pipeline → 5-stage decision pipeline             │     │
│  │  ┌─────────────────────────┐   ┌─────────────────────────┐           │     │
│  │  │ 1. Alert ingestion      │   │ 1. Input validation     │           │     │
│  │  │ 2. Normalization        │   │ 2. Context retrieval    │           │     │
│  │  │ 3. Enrichment           │   │ 3. Agent reasoning      │           │     │
│  │  │ 4-19. [Complex logic]   │   │ 4. Policy check         │           │     │
│  │  │ 20. Analyst assignment  │   │ 5. Execute/escalate     │           │     │
│  │  │ 21. Resolution          │   │                         │           │     │
│  │  └─────────────────────────┘   └─────────────────────────┘           │     │
│  │                                                                       │     │
│  │  SAME PATTERN: Multi-stage processing with validation gates          │     │
│  │                                                                       │     │
│  │  ──────────────────────────────────────────────────────────────      │     │
│  │                                                                       │     │
│  │  Alert triage + routing    → Human approval queue                    │     │
│  │  ┌─────────────────────────┐   ┌─────────────────────────┐           │     │
│  │  │ High severity → P1      │   │ >$250 → Manager review  │           │     │
│  │  │ Medium → P2 queue       │   │ <$250 → Auto-approve    │           │     │
│  │  │ Low → Auto-close        │   │ Edge case → Escalate    │           │     │
│  │  └─────────────────────────┘   └─────────────────────────┘           │     │
│  │                                                                       │     │
│  │  SAME PATTERN: Risk-based routing to human reviewers                 │     │
│  │                                                                       │     │
│  │  ──────────────────────────────────────────────────────────────      │     │
│  │                                                                       │     │
│  │  SIEM integration          → DataDog/PowerBI setup                   │     │
│  │  ┌─────────────────────────┐   ┌─────────────────────────┐           │     │
│  │  │ Log aggregation         │   │ Decision log export     │           │     │
│  │  │ Alert correlation       │   │ Agent performance       │           │     │
│  │  │ Threat dashboards       │   │ Business KPI dashboards │           │     │
│  │  └─────────────────────────┘   └─────────────────────────┘           │     │
│  │                                                                       │     │
│  │  SAME PATTERN: Centralized monitoring + alerting                     │     │
│  │                                                                       │     │
│  │  ──────────────────────────────────────────────────────────────      │     │
│  │                                                                       │     │
│  │  Threat detection          → Security Observer                       │     │
│  │  ┌─────────────────────────┐   ┌─────────────────────────┐           │     │
│  │  │ MITRE ATT&CK tagging    │   │ MITRE ATLAS tagging     │           │     │
│  │  │ Anomaly detection       │   │ Prompt injection detect │           │     │
│  │  │ IOC extraction          │   │ Supply chain anomaly    │           │     │
│  │  └─────────────────────────┘   └─────────────────────────┘           │     │
│  │                                                                       │     │
│  │  SAME PATTERN: Watch-only observer, zero write privileges            │     │
│  │                                                                       │     │
│  │  ──────────────────────────────────────────────────────────────      │     │
│  │                                                                       │     │
│  │  Multi-domain correlation  → Bi-temporal decision trace              │     │
│  │  ┌─────────────────────────┐   ┌─────────────────────────┐           │     │
│  │  │ Temporal attack chains  │   │ Temporal decision chains│           │     │
│  │  │ "What happened when?"   │   │ "What did AI know when?"│           │     │
│  │  │ Event reconstruction    │   │ Decision reconstruction │           │     │
│  │  └─────────────────────────┘   └─────────────────────────┘           │     │
│  │                                                                       │     │
│  │  SAME PATTERN: Temporal analysis for forensics/compliance            │     │
│  │                                                                       │     │
│  └───────────────────────────────────────────────────────────────────────┘     │
│                                                                                 │
│  ┌───────────────────────────────────────────────────────────────────────┐     │
│  │ FROM AGENTIC CHATBOT (Educational NLP)                               │     │
│  ├───────────────────────────────────────────────────────────────────────┤     │
│  │                                                                       │     │
│  │  Chatbot Component         →  agentLUMEN Equivalent                  │     │
│  │  ────────────────────────────────────────────────────────────────     │     │
│  │                                                                       │     │
│  │  NLP (83.3% accuracy)      → Pricing/support agents                  │     │
│  │  ┌─────────────────────────┐   ┌─────────────────────────┐           │     │
│  │  │ Student query           │   │ User intent (buy/info)  │           │     │
│  │  │ Intent: "homework help" │   │ Intent: "pricing query" │           │     │
│  │  │ Entity: "calculus"      │   │ Entity: "MacBook Pro"   │           │     │
│  │  │ Response: [tutorial]    │   │ Response: [price + spec]│           │     │
│  │  └─────────────────────────┘   └─────────────────────────┘           │     │
│  │                                                                       │     │
│  │  SAME PATTERN: Intent classification + entity extraction             │     │
│  │                                                                       │     │
│  │  ──────────────────────────────────────────────────────────────      │     │
│  │                                                                       │     │
│  │  Redis conversation cache  → Session cache (3h TTL)                  │     │
│  │  ┌─────────────────────────┐   ┌─────────────────────────┐           │     │
│  │  │ chat:{student_id}       │   │ session:{user_id}       │           │     │
│  │  │ • Last 10 messages      │   │ • Rolling summary       │           │     │
│  │  │ • Course context        │   │ • KV state (budget, etc)│           │     │
│  │  │ • TTL: session end      │   │ • TTL: 3 hours          │           │     │
│  │  └─────────────────────────┘   └─────────────────────────┘           │     │
│  │                                                                       │     │
│  │  SAME PATTERN: Short-term memory in Redis, not in prompt             │     │
│  │                                                                       │     │
│  │  ──────────────────────────────────────────────────────────────      │     │
│  │                                                                       │     │
│  │  RAG retrieval             → Context Graph queries                   │     │
│  │  ┌─────────────────────────┐   ┌─────────────────────────┐           │     │
│  │  │ Course materials DB     │   │ Product catalog DB      │           │     │
│  │  │ Semantic search         │   │ Semantic search         │           │     │
│  │  │ "Find related concepts" │   │ "Find similar products" │           │     │
│  │  └─────────────────────────┘   └─────────────────────────┘           │     │
│  │                                                                       │     │
│  │  SAME PATTERN: Vector similarity search for retrieval                │     │
│  │                                                                       │     │
│  │  ──────────────────────────────────────────────────────────────      │     │
│  │                                                                       │     │
│  │  Multi-turn context        → Three-tier memory (Tier 0-1-2)          │     │
│  │  ┌─────────────────────────┐   ┌─────────────────────────┐           │     │
│  │  │ Q1: "What's calculus?"  │   │ Q1: "Show me laptops"   │           │     │
│  │  │ Q2: "Give me example"   │   │ Q2: "Under $800"        │           │     │
│  │  │ Q3: "Harder one please" │   │ Q3: "With 16GB RAM"     │           │     │
│  │  │                         │   │                         │           │     │
│  │  │ Agent: builds context   │   │ Agent: builds criteria  │           │     │
│  │  │        from Q1-Q3       │   │        from Q1-Q3       │           │     │
│  │  └─────────────────────────┘   └─────────────────────────┘           │     │
│  │                                                                       │     │
│  │  SAME PATTERN: Progressive refinement over multiple turns            │     │
│  │                                                                       │     │
│  └───────────────────────────────────────────────────────────────────────┘     │
│                                                                                 │
│  ──────────────────────────────────────────────────────────────────────────    │
│                                                                                 │
│  KEY INSIGHT: You're not building new patterns - you're COMBINING patterns     │
│               you've already mastered in production systems.                    │
│                                                                                 │
│  JanuSec patterns       → Orchestration, firewall, observability               │
│  Chatbot patterns       → NLP, memory, RAG, conversation flow                  │
│  agentLUMEN = JanuSec + Chatbot + E-commerce domain logic                      │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

## Slide 10: END-STATE ARCHITECTURE (ASCII DIAGRAM)

```
┌───────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                    AGENTLUMEN END-STATE ARCHITECTURE                                  │
│                                  (Production-Grade, Multi-Agent System)                               │
├───────────────────────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                                       │
│                                        ┌─────────────────┐                                            │
│                                        │   INTERNET      │                                            │
│                                        │   (Customers)   │                                            │
│                                        └────────┬────────┘                                            │
│                                                 │                                                     │
│                                                 │ HTTPS                                               │
│                                                 ▼                                                     │
│                                   ┌──────────────────────────┐                                        │
│                                   │ CDN + WAF (Cloudflare)   │                                        │
│                                   │ • DDoS protection        │                                        │
│                                   │ • Edge caching           │                                        │
│                                   │ • Rate limiting          │                                        │
│                                   └──────────┬───────────────┘                                        │
│                                              │                                                        │
│  ┌───────────────────────────────────────────┼──────────────────────────────────────────┐            │
│  │                                           │                                          │            │
│  │  VPC: PUBLIC (CLOUD - Azure/AWS)          │                                          │            │
│  │  ────────────────────────────────────────────────────────────────────────────        │            │
│  │                                           │                                          │            │
│  │                                           ▼                                          │            │
│  │                          ┌────────────────────────────────┐                          │            │
│  │                          │ API Gateway + Load Balancer    │                          │            │
│  │                          │ • Route: /api → Control Plane  │                          │            │
│  │                          │ • Route: /chat → Storefront    │                          │            │
│  │                          │ • Autoscale (5-50 instances)   │                          │            │
│  │                          └────────────┬───────────────────┘                          │            │
│  │                                       │                                              │            │
│  │                                       │ 30% Traffic (Stateless)                      │            │
│  │                                       │                                              │            │
│  │                          ┌────────────┴───────────────┐                              │            │
│  │                          │ Storefront (React SPA)     │                              │            │
│  │                          │ • User interface           │                              │            │
│  │                          │ • Chat widget              │                              │            │
│  │                          │ • Product catalog browsing │                              │            │
│  │                          └────────────────────────────┘                              │            │
│  │                                                                                      │            │
│  └──────────────────────────────────────────────────────────────────────────────────────┘            │
│                                              │                                                        │
│                                              │ Private Link / ExpressRoute (<10ms)                    │
│                                              ▼                                                        │
│  ┌─────────────────────────────────────────────────────────────────────────────────────────────┐     │
│  │                                                                                             │     │
│  │  VPC: CONTROL PLANE (COLOCATION - Low Latency + GPU)                                       │     │
│  │  ──────────────────────────────────────────────────────────────────────────────────────     │     │
│  │                                                                                             │     │
│  │                                70% Traffic (Stateful)                                       │     │
│  │                                                                                             │     │
│  │  ┌───────────────────────────────────────────────────────────────────────────────────┐     │     │
│  │  │ ORCHESTRATOR (RLM - Reasoning Loop Manager)                                       │     │     │
│  │  │ ┌─────────────────┬─────────────────┬──────────────────┬────────────────────┐    │     │     │
│  │  │ │ State Machine   │ Event Router    │ Policy Engine    │ Approval Queue     │    │     │     │
│  │  │ │ • Workflow logic│ • Agent dispatch│ • Firewall rules │ • Human-in-loop    │    │     │     │
│  │  │ │ • Multi-agent   │ • Load balancing│ • ABAC policies  │ • Slack/email      │    │     │     │
│  │  │ └─────────────────┴─────────────────┴──────────────────┴────────────────────┘    │     │     │
│  │  └───────────────────────────────────────────────────────────────────────────────────┘     │     │
│  │                                         │                                                   │     │
│  │                                         │ Dispatches to agents                              │     │
│  │                                         ▼                                                   │     │
│  │  ┌──────────────────────────────────────────────────────────────────────────────────┐      │     │
│  │  │ DOMAIN AGENTS (GPU-Accelerated Runtime)                                          │      │     │
│  │  │ ┌──────────────┬──────────────┬──────────────┬──────────────┬──────────────┐    │      │     │
│  │  │ │ Pricing      │ Inventory    │ Support      │ Fraud        │ Recommender  │    │      │     │
│  │  │ │ Agent        │ Agent        │ Agent        │ Detector     │ Agent        │    │      │     │
│  │  │ │              │              │              │              │              │    │      │     │
│  │  │ │ • Dynamic    │ • Reorder    │ • Ticket     │ • Risk       │ • Product    │    │      │     │
│  │  │ │   discounts  │ • Stock opt  │   triage     │   scoring    │   discovery  │    │      │     │
│  │  │ │ • A/B test   │ • Lead time  │ • Refund     │ • Account    │ • Cross-sell │    │      │     │
│  │  │ │ • Promo      │   prediction │   approval   │   takeover   │ • Upsell     │    │      │     │
│  │  │ └──────────────┴──────────────┴──────────────┴──────────────┴──────────────┘    │      │     │
│  │  │                                                                                  │      │     │
│  │  │ All agents: Propose actions → Orchestrator validates → Firewall approves        │      │     │
│  │  │                                                                                  │      │     │
│  │  └──────────────────────────────────────────────────────────────────────────────────┘      │     │
│  │                                         │                                                   │     │
│  │                                         │ Queries/updates                                   │     │
│  │                                         ▼                                                   │     │
│  │  ┌──────────────────────────────────────────────────────────────────────────────────┐      │     │
│  │  │ TRANSACTION FIREWALL (Policy Enforcement)                                        │      │     │
│  │  │ ┌────────────────────────────────────────────────────────────────────────────┐   │      │     │
│  │  │ │ • ABAC Rules (Open Policy Agent)                                           │   │      │     │
│  │  │ │ • Idempotency validation (prevent duplicate charges)                       │   │      │     │
│  │  │ │ • Approval routing (>$250 → human, <$250 → auto)                           │   │      │     │
│  │  │ │ • Policy versioning (track which rules applied)                            │   │      │     │
│  │  │ │ • Circuit breaker (rate limit per hour: max $10K discounts)                │   │      │     │
│  │  │ └────────────────────────────────────────────────────────────────────────────┘   │      │     │
│  │  └──────────────────────────────────────────────────────────────────────────────────┘      │     │
│  │                                                                                             │     │
│  │  ┌──────────────────────────────────────────────────────────────────────────────────┐      │     │
│  │  │ SECURITY OBSERVER (Read-Only Monitoring)                                         │      │     │
│  │  │ ┌────────────────────────────────────────────────────────────────────────────┐   │      │     │
│  │  │ │ • Watches ALL agent tool calls (zero write privileges)                     │   │      │     │
│  │  │ │ • MITRE ATLAS threat taxonomy (ML-specific attacks)                        │   │      │     │
│  │  │ │ • Prompt injection detection (ML classifier)                               │   │      │     │
│  │  │ │ • Anomaly detection (agent behavior drift)                                 │   │      │     │
│  │  │ │ • Supply chain validation (API response tampering)                         │   │      │     │
│  │  │ │ • Alerts → Ops team (Slack/PagerDuty)                                      │   │      │     │
│  │  │ └────────────────────────────────────────────────────────────────────────────┘   │      │     │
│  │  └──────────────────────────────────────────────────────────────────────────────────┘      │     │
│  │                                                                                             │     │
│  │  ┌──────────────────────────────────────────────────────────────────────────────────┐      │     │
│  │  │ MEMORY LAYER (Redis Cluster - 3 Shards, 48GB Total)                             │      │     │
│  │  │ ┌────────────────────────────────────────────────────────────────────────────┐   │      │     │
│  │  │ │ • session:{user_id}:summary (rolling narrative, 3h TTL)                    │   │      │     │
│  │  │ │ • session:{user_id}:kv_state (budget, constraints, draft_cart_id)          │   │      │     │
│  │  │ │ • session:{user_id}:recent_retrieval (cached product docs, 5min TTL)       │   │      │     │
│  │  │ │ • CacheRAG results (frequently accessed catalog data)                      │   │      │     │
│  │  │ └────────────────────────────────────────────────────────────────────────────┘   │      │     │
│  │  │ Capacity: 100K+ concurrent sessions                                              │      │     │
│  │  └──────────────────────────────────────────────────────────────────────────────────┘      │     │
│  │                                                                                             │     │
│  └─────────────────────────────────────────────────────────────────────────────────────────────┘     │
│                                              │                                                        │
│                                              │ Private Link (No Internet)                             │
│                                              ▼                                                        │
│  ┌─────────────────────────────────────────────────────────────────────────────────────────────┐     │
│  │                                                                                             │     │
│  │  VPC: DATA PLANE (COLOCATION - PII Never Leaves)                                           │     │
│  │  ──────────────────────────────────────────────────────────────────────────────────────     │     │
│  │                                                                                             │     │
│  │  ┌──────────────────────────────────────────────────────────────────────────────────┐      │     │
│  │  │ PostgreSQL OLTP (Primary + Replica)                                              │      │     │
│  │  │ ┌────────────────────────────────────────────────────────────────────────────┐   │      │     │
│  │  │ │ Tables:                                                                    │   │      │     │
│  │  │ │ • customers (PII: email, name, address, phone)                             │   │      │     │
│  │  │ │ • orders (order history, payment tokens)                                   │   │      │     │
│  │  │ │ • draft_orders (canonical cart state)                                      │   │      │     │
│  │  │ │ • inventory (stock levels, warehouses)                                     │   │      │     │
│  │  │ │ • products (catalog, specs, pricing)                                       │   │      │     │
│  │  │ │ • decision_logs_hot (last 7 days, high-performance queries)                │   │      │     │
│  │  │ └────────────────────────────────────────────────────────────────────────────┘   │      │     │
│  │  │                                                                                  │      │     │
│  │  │ HA Setup: Primary + Streaming Replica (failover < 30s)                          │      │     │
│  │  │ Backups: Continuous WAL archiving + nightly snapshots                            │      │     │
│  │  └──────────────────────────────────────────────────────────────────────────────────┘      │     │
│  │                                                                                             │     │
│  │  ┌──────────────────────────────────────────────────────────────────────────────────┐      │     │
│  │  │ BI-TEMPORAL CONTEXT GRAPH (PostgreSQL with Temporal Columns)                     │      │     │
│  │  │ ┌────────────────────────────────────────────────────────────────────────────┐   │      │     │
│  │  │ │ decision_logs (bi-temporal schema):                                        │   │      │     │
│  │  │ │                                                                            │   │      │     │
│  │  │ │ • valid_from, valid_to (business time: when decision was valid)            │   │      │     │
│  │  │ │ • system_from, system_to (system time: when we knew about it)              │   │      │     │
│  │  │ │ • input_data, retrieved_context (what AI saw)                              │   │      │     │
│  │  │ │ • agent_reasoning (chain-of-thought)                                       │   │      │     │
│  │  │ │ • proposed_action, execution_status (what happened)                        │   │      │     │
│  │  │ │ • policy_version (which rules applied)                                     │   │      │     │
│  │  │ │                                                                            │   │      │     │
│  │  │ │ Query: "What did AI know at 10:42 AM on March 3rd?"                        │   │      │     │
│  │  │ │ → Temporal WHERE clause returns exact state                                │   │      │     │
│  │  │ └────────────────────────────────────────────────────────────────────────────┘   │      │     │
│  │  │                                                                                  │      │     │
│  │  │ Purpose: ISO 42001, EU AI Act Article 17, NIST AI RMF compliance                 │      │     │
│  │  └──────────────────────────────────────────────────────────────────────────────────┘      │     │
│  │                                                                                             │     │
│  │  ┌──────────────────────────────────────────────────────────────────────────────────┐      │     │
│  │  │ VECTOR DB (QDrant/Pinecone - Semantic Search)                                   │      │     │
│  │  │ ┌────────────────────────────────────────────────────────────────────────────┐   │      │     │
│  │  │ │ Collections:                                                               │   │      │     │
│  │  │ │ • product_embeddings (semantic product search)                             │   │      │     │
│  │  │ │ • support_kb (FAQ, policies, troubleshooting)                              │   │      │     │
│  │  │ │ • compatibility_matrix (product cross-references)                          │   │      │     │
│  │  │ │                                                                            │   │      │     │
│  │  │ │ CacheRAG Strategy:                                                         │   │      │     │
│  │  │ │ • Cache retrieval results (not raw embeddings)                             │   │      │     │
│  │  │ │ • TTL: 5min for volatile data, 1h for static                               │   │      │     │
│  │  │ │ • Store in Redis (session cache)                                           │   │      │     │
│  │  │ └────────────────────────────────────────────────────────────────────────────┘   │      │     │
│  │  │                                                                                  │      │     │
│  │  │ Purpose: "Find laptops similar to this" semantic queries                         │      │     │
│  │  └──────────────────────────────────────────────────────────────────────────────────┘      │     │
│  │                                                                                             │     │
│  │  ┌──────────────────────────────────────────────────────────────────────────────────┐      │     │
│  │  │ ARCHIVE STORAGE (Warm/Cold Tiers)                                                │      │     │
│  │  │ ┌────────────────────────────────────────────────────────────────────────────┐   │      │     │
│  │  │ │ BigQuery (Warm - 8-90 days):                                               │   │      │     │
│  │  │ │ • Partitioned by date (fast analytics)                                     │   │      │     │
│  │  │ │ • Aggregated metrics (RAGAS eval, approval rates)                          │   │      │     │
│  │  │ │ • No PII (anonymized for analytics)                                        │   │      │     │
│  │  │ │                                                                            │   │      │     │
│  │  │ │ S3 Glacier (Cold - 90+ days):                                              │   │      │     │
│  │  │ │ • Parquet files (compressed)                                               │   │      │     │
│  │  │ │ • 7-year retention (regulatory)                                            │   │      │     │
│  │  │ │ • Retrieval: 12-48h (audit only)                                           │   │      │     │
│  │  │ └────────────────────────────────────────────────────────────────────────────┘   │      │     │
│  │  └──────────────────────────────────────────────────────────────────────────────────┘      │     │
│  │                                                                                             │     │
│  │  SECURITY: Isolated subnet, no direct internet, private link only                          │     │
│  │  COMPLIANCE: PII never leaves this VPC (GDPR Article 44 compliant)                         │     │
│  │                                                                                             │     │
│  └─────────────────────────────────────────────────────────────────────────────────────────────┘     │
│                                                                                                       │
│  ┌─────────────────────────────────────────────────────────────────────────────────────────────┐     │
│  │                                                                                             │     │
│  │  CLOUD (AZURE/AWS) - ANALYTICS + MONITORING                                                │     │
│  │  ────────────────────────────────────────────────────────────────────────────────────       │     │
│  │                                                                                             │     │
│  │  ┌──────────────────────────────────────────────────────────────────────────────────┐      │     │
│  │  │ DataDog (SIEM + APM)                                                             │      │     │
│  │  │ • Redacted logs (no PII)                                                         │      │     │
│  │  │ • Distributed tracing (OpenTelemetry)                                            │      │     │
│  │  │ • Alert rules (error rate, latency, cost)                                        │      │     │
│  │  │ • Dashboards (agent performance, business KPIs)                                  │      │     │
│  │  └──────────────────────────────────────────────────────────────────────────────────┘      │     │
│  │                                                                                             │     │
│  │  ┌──────────────────────────────────────────────────────────────────────────────────┐      │     │
│  │  │ PowerBI (Business Dashboards)                                                    │      │     │
│  │  │ • Revenue metrics (orders, conversions, AOV)                                     │      │     │
│  │  │ • Agent performance (approval rate, accuracy, confidence)                        │      │     │
│  │  │ • Compliance metrics (audit trail coverage, policy violations)                   │      │     │
│  │  │ • No customer PII (aggregated only)                                              │      │     │
│  │  └──────────────────────────────────────────────────────────────────────────────────┘      │     │
│  │                                                                                             │     │
│  └─────────────────────────────────────────────────────────────────────────────────────────────┘     │
│                                                                                                       │
│  ┌─────────────────────────────────────────────────────────────────────────────────────────────┐     │
│  │                                                                                             │     │
│  │  EXTERNAL SAAS (COMMODITY SERVICES)                                                         │     │
│  │  ────────────────────────────────────────────────────────────────────────────────────       │     │
│  │                                                                                             │     │
│  │  • Stripe/Revolut (Payments - PCI handled)                                                  │     │
│  │  • ShipStation (Fulfillment - webhook integration)                                          │     │
│  │  • Zendesk (Support - ticket sync)                                                          │     │
│  │  • Xero (Accounting - transaction export)                                                   │     │
│  │  • Intercom (Customer comms - chat widget)                                                  │     │
│  │                                                                                             │     │
│  │  All SaaS integrated via webhooks/APIs, no direct agent access                              │     │
│  │  Transaction Firewall mediates all external calls                                           │     │
│  │                                                                                             │     │
│  └─────────────────────────────────────────────────────────────────────────────────────────────┘     │
│                                                                                                       │
│  ───────────────────────────────────────────────────────────────────────────────────────────────     │
│                                                                                                       │
│  KEY ARCHITECTURE PRINCIPLES:                                                                        │
│  1. Zero-Trust: Agents assumed compromised → all actions validated by Firewall                       │
│  2. PII Isolation: Customer data never leaves colo VPC (GDPR compliant)                              │
│  3. Hybrid Deployment: 30% cloud (stateless), 70% colo (stateful + GPU)                              │
│  4. Memory Hygiene: Cart/order is truth, not chat transcript                                         │
│  5. Forced Retrieval: Price/stock/specs always verified live                                         │
│  6. Bi-Temporal Logging: "What did AI know when?" for compliance                                     │
│  7. Graceful Degradation: AI → Rules → Human queue (never fail)                                      │
│  8. Scalability: Redis cluster (100K+ sessions), PostgreSQL HA, autoscaling agents                   │
│                                                                                                       │
└───────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## Slide 11: 6-WEEK MVP ARCHITECTURE (SIMPLIFIED)

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                        6-WEEK MVP ARCHITECTURE                               │
│                   (Minimal Viable, Single Agent, Cloud-Only)                 │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│                            ┌─────────────┐                                   │
│                            │  INTERNET   │                                   │
│                            └──────┬──────┘                                   │
│                                   │                                          │
│                                   ▼                                          │
│                         ┌──────────────────┐                                 │
│                         │ Cloudflare (CDN) │                                 │
│                         └─────────┬────────┘                                 │
│                                   │                                          │
│  ┌────────────────────────────────┴─────────────────────────────────┐       │
│  │ AWS/GCP (Single Region, Single VPC)                              │       │
│  │ ────────────────────────────────────────────────────────────      │       │
│  │                                                                   │       │
│  │  ┌──────────────────┐         ┌──────────────────┐               │       │
│  │  │ API Gateway      │────────▶│ Flask/FastAPI    │               │       │
│  │  │ (Load Balancer)  │         │ Backend          │               │       │
│  │  └──────────────────┘         └────────┬─────────┘               │       │
│  │                                        │                          │       │
│  │                                        ▼                          │       │
│  │                     ┌──────────────────────────────┐              │       │
│  │                     │ ORCHESTRATOR (Simple RLM)    │              │       │
│  │                     │ • Python state machine       │              │       │
│  │                     │ • Single agent (pricing)     │              │       │
│  │                     │ • Synchronous execution      │              │       │
│  │                     └──────────┬───────────────────┘              │       │
│  │                                │                                  │       │
│  │                    ┌───────────┴───────────┐                      │       │
│  │                    │                       │                      │       │
│  │                    ▼                       ▼                      │       │
│  │         ┌──────────────────┐   ┌─────────────────────┐           │       │
│  │         │ PRICING AGENT    │   │ TRANSACTION FIREWALL│           │       │
│  │         │ • LangChain      │   │ • Python functions  │           │       │
│  │         │ • GPT-4 API      │   │ • Basic if/then     │           │       │
│  │         │ • Propose only   │   │ • >$250 → human     │           │       │
│  │         └────────┬─────────┘   └──────────┬──────────┘           │       │
│  │                  │                        │                      │       │
│  │                  └────────────┬───────────┘                      │       │
│  │                               │                                  │       │
│  │                               ▼                                  │       │
│  │              ┌────────────────────────────────┐                  │       │
│  │              │ MEMORY LAYER                   │                  │       │
│  │              │ ┌────────────────────────────┐ │                  │       │
│  │              │ │ Redis (Single Instance 4GB)│ │                  │       │
│  │              │ │ • session:* (rolling sum)  │ │                  │       │
│  │              │ │ • session:*:kv_state       │ │                  │       │
│  │              │ │ • TTL: 3h                  │ │                  │       │
│  │              │ └────────────────────────────┘ │                  │       │
│  │              └────────────────────────────────┘                  │       │
│  │                               │                                  │       │
│  │                               ▼                                  │       │
│  │              ┌────────────────────────────────┐                  │       │
│  │              │ STORAGE                        │                  │       │
│  │              │ ┌────────────────────────────┐ │                  │       │
│  │              │ │ PostgreSQL (RDS 8GB)       │ │                  │       │
│  │              │ │ • customers, orders        │ │                  │       │
│  │              │ │ • draft_orders (cart)      │ │                  │       │
│  │              │ │ • inventory, products      │ │                  │       │
│  │              │ │ • decision_logs (7 days)   │ │                  │       │
│  │              │ └────────────────────────────┘ │                  │       │
│  │              └────────────────────────────────┘                  │       │
│  │                               │                                  │       │
│  │                               ▼                                  │       │
│  │              ┌────────────────────────────────┐                  │       │
│  │              │ INTEGRATIONS                   │                  │       │
│  │              │ • Stripe (payments)            │                  │       │
│  │              │ • Shopify (webhooks)           │                  │       │
│  │              │ • Slack (approvals)            │                  │       │
│  │              └────────────────────────────────┘                  │       │
│  │                                                                  │       │
│  │  ┌──────────────────────────────────────────────────────┐       │       │
│  │  │ APPROVAL DASHBOARD (React SPA)                       │       │       │
│  │  │ • Pending decisions view                             │       │       │
│  │  │ • Approve/reject buttons                             │       │       │
│  │  │ • Decision history                                   │       │       │
│  │  └──────────────────────────────────────────────────────┘       │       │
│  │                                                                  │       │
│  └──────────────────────────────────────────────────────────────────┘       │
│                                                                              │
│  DEPLOYMENT: Docker Compose (docker-compose up)                              │
│  COST: ~$500/month infrastructure                                            │
│  CAPACITY: 5K concurrent sessions, 10K decisions/day                         │
│  AUTONOMY: 0% (Week 1-4), 20% (Week 5-6)                                     │
│                                                                              │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## Slide 12: IMPLEMENTATION ROADMAP (6-WEEK SPRINT)

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                        6-WEEK IMPLEMENTATION ROADMAP                            │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│  WEEK 1: CORE PIPELINE + MEMORY                                                 │
│  ────────────────────────────────────────────────────────────────────           │
│  Days 1-2: Infrastructure                                                       │
│  • PostgreSQL schema (orders, customers, inventory, decision_logs)              │
│  • Redis instance (4GB, single node)                                            │
│  • Flask/FastAPI backend skeleton                                               │
│  • GitHub repo + CI/CD (GitHub Actions)                                         │
│                                                                                 │
│  Days 3-4: NLP Agent (Port from Agentic Chatbot)                                │
│  • Pricing agent (LangChain + GPT-4 wrapper)                                    │
│  • Prompts: "Propose discount based on cart value, customer tier, inventory"    │
│  • Redis session cache: rolling summary + KV state                              │
│  • PostgreSQL full-text search (no vector DB yet)                               │
│                                                                                 │
│  Days 5-6: Orchestrator (Port from JanuSec Pipeline)                            │
│  • 5-stage pipeline: validate → retrieve → reason → policy → execute            │
│  • Decision logging with bi-temporal columns (valid_from/to, system_from/to)    │
│  • Basic health checks (agent response time, error rate)                        │
│                                                                                 │
│  Day 7: Human Approval Queue                                                    │
│  • Slack bot (post proposals for approval: ✅ Approve | ❌ Reject)             │
│  • Email notifications for pending approvals                                    │
│                                                                                 │
│  DELIVERABLE: Agent proposes pricing, logs decisions, human approves via Slack  │
│                                                                                 │
│  ──────────────────────────────────────────────────────────────────────────    │
│                                                                                 │
│  WEEK 2: TRANSACTION FIREWALL + STRIPE                                          │
│  ────────────────────────────────────────────────────────────────────           │
│  Days 8-10: Transaction Firewall                                                │
│  • Policy engine (Python functions, no OPA for MVP)                             │
│  • Rules:                                                                       │
│    - Max discount: 30% (hardcoded cap)                                          │
│    - Max cart total (auto-approve): $250                                        │
│    - Margin protection: Min 15% margin                                          │
│  • Idempotency keys (prevent duplicate charges)                                 │
│  • Integration with orchestrator                                                │
│                                                                                 │
│  Days 11-12: Stripe Integration                                                 │
│  • Stripe Checkout API (payment intents)                                        │
│  • Webhook handler (payment.succeeded, payment.failed)                          │
│  • Refund API (for agent mistakes)                                              │
│  • Test mode thoroughly (use Stripe test cards)                                 │
│                                                                                 │
│  Days 13-14: Approval Dashboard UI                                              │
│  • React SPA (Tailwind CSS)                                                     │
│  • Features:                                                                    │
│    - Pending decisions view (table with filters)                                │
│    - One-click approve/reject                                                   │
│    - Decision history (last 100 decisions)                                      │
│    - Agent reasoning display (show chain-of-thought)                            │
│                                                                                 │
│  DELIVERABLE: End-to-end payment flow with human gate                           │
│                                                                                 │
│  ──────────────────────────────────────────────────────────────────────────    │
│                                                                                 │
│  WEEK 3: OBSERVABILITY + SECURITY                                               │
│  ────────────────────────────────────────────────────────────────────           │
│  Days 15-16: Security Observer (Lite Version)                                   │
│  • Watch all agent tool calls (read-only)                                       │
│  • Basic prompt injection detection (regex patterns)                            │
│  • Alert on anomalies (Slack webhook)                                           │
│  • Log suspicious activity                                                      │
│                                                                                 │
│  Days 17-18: Monitoring                                                         │
│  • DataDog APM (or Grafana if budget-constrained)                               │
│  • Log aggregation (agent decisions, errors)                                    │
│  • Basic RAGAS evaluation (faithfulness, answer relevance)                      │
│  • Dashboards:                                                                  │
│    - Decision throughput (decisions/hour)                                       │
│    - Error rate (% failed decisions)                                            │
│    - Approval rate (% human-approved)                                           │
│    - Agent confidence distribution                                              │
│                                                                                 │
│  Days 19-21: Graceful Degradation                                               │
│  • Rule-based fallback (static pricing if agent fails)                          │
│  • Health checks:                                                               │
│    - Agent response time <5s or fallback                                        │
│    - Error rate >10% over 5min → disable agent                                  │
│  • Circuit breaker pattern (auto-recover after 10 successful calls)             │
│  • Manual override UI (force enable/disable agent)                              │
│                                                                                 │
│  DELIVERABLE: Monitored system that survives agent failures                     │
│                                                                                 │
│  ──────────────────────────────────────────────────────────────────────────    │
│                                                                                 │
│  WEEK 4: INTEGRATIONS + TESTING                                                 │
│  ────────────────────────────────────────────────────────────────────           │
│  Days 22-23: Inventory + ShipStation                                            │
│  • Basic inventory management (PostgreSQL)                                      │
│  • Stock level checks (before agent proposes pricing)                           │
│  • ShipStation webhook integration (order fulfillment)                          │
│  • Low stock alerts (notify ops team)                                           │
│                                                                                 │
│  Days 24-25: End-to-End Testing                                                 │
│  • Full order flow: browse → add to cart → checkout → payment → fulfill         │
│  • Agent decision quality testing:                                              │
│    - Accuracy: Does proposed discount make sense?                               │
│    - Hallucination: Does agent make up prices/stock?                            │
│    - Consistency: Same input → same output?                                     │
│  • Fallback scenario testing:                                                   │
│    - Force agent timeout → verify rule-based fallback                           │
│    - Force firewall failure → verify human queue escalation                     │
│                                                                                 │
│  Days 26-27: RAGAS Evaluation                                                   │
│  • Evaluate agent faithfulness (does it cite sources correctly?)                │
│  • Test hallucination detection (prompt with contradictory data)                │
│  • Tune confidence thresholds (what confidence = auto-approve?)                 │
│  • Document edge cases discovered                                               │
│                                                                                 │
│  Day 28: Deploy + Documentation                                                 │
│  • Deploy to staging environment                                                │
│  • Write runbooks:                                                              │
│    - "What to do if agent goes down"                                            │
│    - "How to approve decisions manually"                                        │
│    - "How to add new products to catalog"                                       │
│  • Create simple dashboards (Google Sheets if no DataDog)                       │
│                                                                                 │
│  DELIVERABLE: Functional MVP, ready for limited beta (Week 5)                   │
│                                                                                 │
│  ──────────────────────────────────────────────────────────────────────────    │
│                                                                                 │
│  WEEK 5-6: BETA LAUNCH + RAMP                                                   │
│  ────────────────────────────────────────────────────────────────────           │
│  Week 5: Limited Beta (10-50 orders/day)                                        │
│  • Shadow mode (agent proposes, logs only - 0% autonomy)                        │
│  • Collect human feedback:                                                      │
│    - Why approve? (good proposal)                                               │
│    - Why reject? (bad proposal - learn from mistakes)                           │
│  • Monitor closely (daily review of decisions)                                  │
│  • Tune prompts based on feedback                                               │
│                                                                                 │
│  Week 6: Supervised Launch (100-200 orders/day)                                 │
│  • 20% autonomy: <$100 carts, discount <15%, confidence >80%                    │
│  • 80% human review: Everything else                                            │
│  • Metrics to track:                                                            │
│    - Error rate: <5% target                                                     │
│    - Human override rate: <20% target                                           │
│    - Agent confidence: Mean >0.75                                               │
│    - Customer satisfaction: Monitor for complaints                              │
│                                                                                 │
│  DELIVERABLE: Production-ready MVP with 20% autonomy, proven <5% error rate     │
│                                                                                 │
│  ──────────────────────────────────────────────────────────────────────────    │
│                                                                                 │
│  WEEKS 7-12: POST-MVP (OPTIONAL SCOPE)                                          │
│  ────────────────────────────────────────────────────────────────────           │
│  If Week 1-6 goes smoothly, consider:                                           │
│  • Week 7-8: Add second agent (inventory OR support)                            │
│  • Week 9-10: Increase autonomy to 50% (<$250 auto-approve)                     │
│  • Week 11-12: Stress testing (1000+ orders/day simulation)                     │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

## Slide 13: NEXT STEPS

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                                NEXT STEPS                                       │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│  IMMEDIATE ACTIONS (This Week):                                                 │
│  ───────────────────────────────────────────────────────────────────            │
│                                                                                 │
│  1. Present Architecture to David                                               │
│     • Show updated slides (with memory architecture)                            │
│     • Emphasize JanuSec + Chatbot pattern reuse                                 │
│     • Explain memory hygiene > recursive learning                               │
│     • Get sign-off on 6-week MVP scope                                          │
│                                                                                 │
│  2. Finalize Stack Decisions                                                    │
│     • Confirm: PostgreSQL (not Neo4j) for bi-temporal logs                      │
│     • Confirm: Single Redis instance (not cluster) for MVP                      │
│     • Confirm: Cloud-only (not colo) for MVP                                    │
│     • Confirm: Single agent (pricing) for MVP                                   │
│                                                                                 │
│  3. Set Up Infrastructure                                                       │
│     • AWS/GCP account + billing                                                 │
│     • PostgreSQL RDS instance                                                   │
│     • Redis ElastiCache instance                                                │
│     • GitHub repo (agentLUMEN-mvp)                                              │
│     • CI/CD pipeline (GitHub Actions)                                           │
│                                                                                 │
│  4. Assemble Team                                                               │
│     • You (tech lead + architect)                                               │
│     • 1-2 contractors (backend + frontend)                                      │
│     • Part-time security advisor (JanuSec patterns)                             │
│                                                                                 │
│  ──────────────────────────────────────────────────────────────────────────    │
│                                                                                 │
│  WEEK 1 SPRINT GOALS:                                                           │
│  ───────────────────────────────────────────────────────────────────            │
│                                                                                 │
│  Sprint Objective: Core pipeline functional (agent proposes, logs decisions)    │
│                                                                                 │
│  Day 1: PostgreSQL schema + Redis setup                                         │
│  • CREATE TABLE customers, orders, draft_orders, inventory, products            │
│  • CREATE TABLE decision_logs (bi-temporal schema)                              │
│  • Redis connection (test SET/GET)                                              │
│                                                                                 │
│  Day 2-3: Port Agentic Chatbot NLP → Pricing Agent                              │
│  • Take your chatbot's NLP engine                                               │
│  • Change prompts: "student query" → "pricing decision"                         │
│  • Input: cart_total, customer_tier, inventory_level                            │
│  • Output: discount_percentage (0-30%)                                          │
│                                                                                 │
│  Day 4-5: Port JanuSec Pipeline → Orchestrator                                  │
│  • 5-stage pipeline (reduce from 21 stages)                                     │
│  • Stage 1: validate_input()                                                    │
│  • Stage 2: retrieve_context() - Redis + PostgreSQL                             │
│  • Stage 3: agent_propose() - LLM call                                          │
│  • Stage 4: firewall_check() - policy validation                                │
│  • Stage 5: execute_or_escalate() - auto or human                               │
│                                                                                 │
│  Day 6-7: Approval Queue                                                        │
│  • Slack bot (post: "Agent proposes 20% discount for Cart #123")                │
│  • Buttons: ✅ Approve | ❌ Reject                                              │
│  • On approve: Update PostgreSQL (execution_status = 'approved')                │
│  • On reject: Log reason, notify agent team                                     │
│                                                                                 │
│  Sprint Demo (Day 7):                                                           │
│  • Show live demo: User adds item → Agent proposes → Human approves → Order     │
│                                                                                 │
│  ──────────────────────────────────────────────────────────────────────────    │
│                                                                                 │
│  SUCCESS METRICS (End of Week 6):                                               │
│  ───────────────────────────────────────────────────────────────────            │
│                                                                                 │
│  ✓ Single pricing agent deployed and functional                                 │
│  ✓ Transaction Firewall enforces policies (>$250 → human)                       │
│  ✓ Decision logs capture bi-temporal audit trail                                │
│  ✓ Stripe integration works (test mode validated)                               │
│  ✓ Graceful degradation tested (agent fails → rules work)                       │
│  ✓ Security Observer monitors tool calls (basic version)                        │
│  ✓ End-to-end order flow works in staging                                       │
│  ✓ 20% autonomy proven with <5% error rate                                      │
│                                                                                 │
│  ──────────────────────────────────────────────────────────────────────────    │
│                                                                                 │
│  DECISION POINT (End of Week 6):                                                │
│  ───────────────────────────────────────────────────────────────────            │
│                                                                                 │
│  IF MVP successful (error rate <5%, autonomy working):                          │
│  → Continue to Weeks 7-12 (add agents, scale to 50% autonomy)                   │
│                                                                                 │
│  IF MVP needs work (error rate >5%, autonomy risky):                            │
│  → Iterate on prompts, tune thresholds, extend beta phase                       │
│                                                                                 │
│  IF MVP fails (fundamental issues):                                             │
│  → Pivot to consulting-only (no product), use MVP as portfolio piece            │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

**Kevin - you have the patterns, you have the experience. Now it's execution time.**

---

**END OF SLIDE DECK**

---

## METADATA

- **Version**: agentLUMEN v5 - Conversational Memory + Scale
- **Focus**: NLP memory architecture, Redis scaling, log storage, MVP vs end-state
- **Target Audience**: Technical stakeholders (David + team)
- **Presentation Time**: 45-60 minutes
- **Format**: Markdown with ASCII diagrams (16:9 optimized)
- **Author**: Kevin (AI & DevSecOps Engineer)
- **Date**: January 2025
