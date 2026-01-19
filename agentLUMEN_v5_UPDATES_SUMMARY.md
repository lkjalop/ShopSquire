# agentLUMEN v5 - KEY UPDATES SUMMARY

## What Changed from v4 → v5

### **1. ADDRESSED THE "RECURSIVE LEARNING" QUESTION**

**Your Original Question**: How to apply recursive learning models to user chat history?

**The Answer (from ChatGPT + Me)**: You don't need "recursive learning" - you need **memory hygiene + retrieval discipline**.

#### **Why "Recursive Learning" Isn't The Solution**

- **What you actually want**: Agent remembers user's budget, preferences, shortlist, constraints across 20+ turns without hallucinating
- **What "recursive learning" implies**: Fine-tuning models on user-specific data (weight updates)
- **Why that's overkill**: 
  - Training/fine-tuning per user = expensive ($$$)
  - Updates are slow (hours/days, not real-time)
  - Doesn't solve hallucination (model still makes up facts)
  - Over-engineering for the problem

#### **The Right Solution: Three-Tier Memory**

```
TIER 0: In-Prompt (Last 6-12 turns)
├─ Natural conversation flow
├─ Pruned to recent exchanges
└─ Doesn't grow unbounded

TIER 1: Redis Session Cache (3h TTL)
├─ Rolling summary (tight narrative)
├─ KV state (budget, constraints, draft_cart_id)
└─ Recent retrieval results (cached 5min)

TIER 2: Vector Store (Semantic Memory)
├─ Product catalog (specs, descriptions)
├─ Policies (returns, shipping, warranty)
└─ FAQs + support knowledge

TIER 3: Bi-Temporal Decision Log
├─ What AI knew at decision time
├─ What evidence was retrieved
└─ What action was taken
```

**Key Principle**: Chat history ≠ source of truth. Truth lives in:
- **KV state** (user's budget, constraints)
- **Catalog DB** (product prices, stock)
- **Draft cart** (canonical order state)

---

### **2. THE MEMORY PATTERN (NO HALLUCINATIONS)**

#### **The Problem You're Solving**

```
Turn 1:  "Show me laptops under $800"
Turn 2:  Agent retrieves 15 models (prices verified: Dell XPS = $849)
...
Turn 15: "What was the Dell price again?"
Turn 16: Agent hallucinates "$799" (sale ended, now $899 - stale data in context)
```

#### **Why Traditional Chatbots Fail**

❌ **WRONG**: Stuff entire transcript into prompt
- Context window fills up (8K → 16K → 32K tokens)
- Model sees stale data from Turn 2
- No forced re-verification of facts that change (price, stock)
- Hallucinations increase after Turn 10+

✅ **RIGHT**: Memory hygiene + forced retrieval
- Chat history is just conversation (not facts)
- Facts anchored to authoritative stores (DB, not transcript)
- Force "retrieve-then-answer" for anything that can change
- Rolling summary (not full transcript) for context

#### **The agentLUMEN Pattern (Per Turn)**

```
User: "What's the price of that Dell laptop?"

Step 1: RETRIEVE SESSION STATE
├─ Redis GET session:{user_id}:summary
│  → "User shortlisted Dell XPS 13, Lenovo ThinkPad"
│
└─ Redis GET session:{user_id}:kv_state
   → {"budget_max": 800, "draft_cart_id": "cart_abc123"}

Step 2: IDENTIFY INTENT + ENTITY
├─ Intent: price_inquiry
├─ Entity: "Dell laptop" → likely "Dell XPS 13" (from summary)
└─ Decision: Need LIVE PRICE (must retrieve, not use cached)

Step 3: FORCED RETRIEVAL (NEVER TRUST MEMORY FOR PRICE)
├─ Query: SELECT price, stock FROM products
│         WHERE name LIKE '%Dell XPS 13%' AND active=true
│
└─ Result: {"price": 899, "stock": 12, "last_updated": "now"}
   
   WHY THIS MATTERS: Price changed from $849 (session start)
                     to $899 (sale ended 30 min ago)

Step 4: GENERATE RESPONSE (WITH EVIDENCE)
├─ Prompt to LLM:
│  "User asked about Dell laptop price.
│   Context: {summary}
│   Current price: $899 (verified live from DB)
│   Stock: 12 units available
│   User's budget: $800 (from KV state)
│   
│   Respond naturally but mention price exceeds budget."
│
└─ LLM Output:
   "The Dell XPS 13 is currently $899 (I just checked).
    That's $99 over your $800 budget. Would you like me to
    find alternatives, or shall I check if there's a coupon?"

Step 5: UPDATE SESSION STATE (ROLLING SUMMARY)
└─ Redis SET session:{user_id}:summary (update)
   → "User wants laptop <$800. Dell XPS 13 is $899 (over budget).
      Considering alternatives or coupon."

Step 6: LOG DECISION (BI-TEMPORAL)
└─ PostgreSQL INSERT INTO decision_logs:
   {
     "agent_name": "conversation_agent",
     "input_data": {"user_query": "What's the price..."},
     "retrieved_context": {"price": 899, "source": "DB"},
     "agent_reasoning": "Price exceeds budget, offered alternatives",
     "policy_version": "v1.2",
     "valid_from": "2025-01-19 15:42:00"
   }
```

**RESULT**: User gets ACCURATE price ($899) not HALLUCINATED ($849)

---

### **3. CART AS CANONICAL STATE (CRITICAL PATTERN)**

#### **Why This Matters**

The draft cart/order IS the memory, not the chat transcript.

**Traditional Approach (Bad - Drift Happens)**:
```
Turn 1:  "Add 2 MacBook Pros to cart"
         [Agent updates internal state: cart = {macbook: 2}]

Turn 5:  "Actually, make it 3"
         [Agent updates internal state: cart = {macbook: 3}]

Turn 10: "What's in my cart?"
         [Agent hallucinates: "2 MacBook Pros" - forgot update!]
```

**agentLUMEN Approach (Good - No Drift)**:
```
Turn 1:  "Add 2 MacBook Pros to cart"
         PostgreSQL INSERT INTO draft_orders:
         {
           "draft_order_id": "draft_abc123",
           "line_items": [{"sku": "MACBOOK_PRO_16", "quantity": 2}]
         }
         
         Redis SET session:{user_id}:kv_state
         {"draft_cart_id": "draft_abc123"}

Turn 5:  "Actually, make it 3"
         PostgreSQL UPDATE draft_orders
         SET line_items[0].quantity = 3
         WHERE draft_order_id = 'draft_abc123'

Turn 10: "What's in my cart?"
         PostgreSQL SELECT FROM draft_orders
         WHERE draft_order_id = 'draft_abc123'
         
         Result: "3 MacBook Pro 16-inch ($2,499 each) = $7,497"
         (ALWAYS CORRECT - cart is canonical source)
```

**Agent Always Answers From**: `draft_order + live_catalog + user_constraints`

---

### **4. REDIS SCALING FOR 100K+ USERS**

#### **The Challenge**

100,000 concurrent sessions × 3h TTL × 50KB/session = 5GB active memory
+ retrieval cache + embeddings = **10GB+ total**

#### **The Solution: Redis Cluster (3 Shards + 3 Replicas)**

```
SHARD 1 (Master + Replica)         Hash Slots: 0-5461
┌─────────────────────────┐         ┌─────────────────────────┐
│ Master 1 (16GB)         │────────▶│ Replica 1 (16GB)        │
│ • session:user_0000-4999│         │ • Read-only failover    │
│ • 33% of sessions       │         │ • Automatic promotion   │
└─────────────────────────┘         └─────────────────────────┘

SHARD 2 (Master + Replica)         Hash Slots: 5462-10922
┌─────────────────────────┐         ┌─────────────────────────┐
│ Master 2 (16GB)         │────────▶│ Replica 2 (16GB)        │
│ • session:user_5000-9999│         │ • Read-only failover    │
│ • 33% of sessions       │         │ • Automatic promotion   │
└─────────────────────────┘         └─────────────────────────┘

SHARD 3 (Master + Replica)         Hash Slots: 10923-16383
┌─────────────────────────┐         ┌─────────────────────────┐
│ Master 3 (16GB)         │────────▶│ Replica 3 (16GB)        │
│ • session:user_10000+   │         │ • Read-only failover    │
│ • 34% of sessions       │         │ • Automatic promotion   │
└─────────────────────────┘         └─────────────────────────┘

CAPACITY: 3 × 16GB = 48GB total
REDUNDANCY: Each shard has replica for failover
SCALABILITY: Add more shards horizontally as traffic grows
```

#### **Memory Eviction Policy**

```
# redis.conf
maxmemory 16gb
maxmemory-policy allkeys-lru  # Evict least recently used keys

# What to cache (by priority):
Priority 1: Session KV state (critical, 3h TTL)
Priority 2: Rolling summary (important, 3h TTL)
Priority 3: Recent retrieval results (nice-to-have, 5min TTL)

# What NOT to cache in Redis:
❌ Full conversation transcripts (use Tier 0 in-memory)
❌ Product catalog (use PostgreSQL + vector DB)
❌ Decision logs (use PostgreSQL bi-temporal table)
```

#### **Cost Analysis**

```
AWS ElastiCache (cache.r7g.xlarge):
• 3 Masters × $0.302/hour = $0.906/hour
• 3 Replicas × $0.302/hour = $0.906/hour
• Total: ~$1.81/hour = $1,300/month

Capacity: 100K-150K concurrent sessions
Cost per session: $0.01/month
```

#### **Autoscaling Triggers**

```
Scale Out (Add Shard):
• Memory usage >80% across all masters
• Connection count >10K per shard
• Latency p99 >5ms

Scale In (Remove Shard):
• Memory usage <40% across all masters
• Sustained for >30 minutes
```

---

### **5. LOG STORAGE AT SCALE (HOT/WARM/COLD TIERS)**

#### **The Problem**

1M decisions/day × 1KB/log = 1GB/day = 365GB/year

#### **The Solution: Tiered Storage**

```
HOT TIER (Last 7 Days - PostgreSQL)
├─ Location: Colocation (low latency <10ms)
├─ Retention: 7 days
├─ Query: Real-time decision lookups, debugging
├─ Size: ~7GB (1M × 1KB × 7 days)
└─ Cost: $50/month (PostgreSQL RDS)

WARM TIER (8-90 Days - BigQuery)
├─ Location: Cloud (GCP/AWS)
├─ Retention: 90 days
├─ Query: Analytics, RAGAS evaluation, compliance audits
├─ Size: ~90GB (compressed columnar)
└─ Cost: $25/month (storage + query)

COLD TIER (90+ Days - S3 Glacier)
├─ Location: Cloud (multi-region)
├─ Retention: 7 years (regulatory)
├─ Query: Rare - only for audits, litigation
├─ Size: ~3TB (7 years × 365 days × 1GB compressed)
├─ Cost: $10/month (Glacier Deep Archive)
└─ Retrieval: 12-48 hours

TOTAL COST: $85/month for complete audit trail
Cost per decision: $0.000085 (~$0.0001)
```

#### **ETL Pipeline**

```
Nightly Job (2 AM):
1. Archive logs older than 7 days from PostgreSQL
2. Compress and upload to BigQuery (warm tier)
3. Delete from hot tier (free up space)

Monthly Job (1st of month):
1. Archive logs older than 90 days from BigQuery
2. Convert to Parquet format (compression)
3. Upload to S3 Glacier (cold tier)
4. Delete from warm tier
```

---

### **6. KEY ARCHITECTURAL CHANGES (v4 → v5)**

#### **New Slides Added**

1. **Slide 2: The Memory Problem** - Why chatbots hallucinate (context rot)
2. **Slide 3: Three-Tier Memory Architecture** - The solution pattern
3. **Slide 4: Memory Pattern (Per Turn)** - Detailed flow showing forced retrieval
4. **Slide 5: Redis Scaling Strategy** - Cluster + sharding for 100K+ users
5. **Slide 6: Log Storage Architecture** - Hot/warm/cold tiers
6. **Slide 7: 6-Week MVP vs End-State** - Clearer comparison
7. **Slide 8: Cart as Canonical State** - No drift pattern
8. **Slide 9: Leveraging JanuSec + Chatbot** - Pattern mapping
9. **Slide 10: End-State ASCII Architecture** - Full production diagram
10. **Slide 11: 6-Week MVP ASCII Architecture** - Simplified diagram

#### **Technical Decisions Clarified**

```
DECISION 1: PostgreSQL (not Neo4j) for bi-temporal logs
WHY: 80% as good, 20% the complexity, can migrate later

DECISION 2: Redis Cluster (not single instance) for production
WHY: 100K+ sessions require sharding, but MVP starts with single instance

DECISION 3: Cart as canonical state (not chat memory)
WHY: Prevents drift - cart in DB is always correct

DECISION 4: Forced retrieval for price/stock (not cached answers)
WHY: Prevents hallucination - always verify facts that can change

DECISION 5: Rolling summary (not full transcript) in Redis
WHY: Bounded memory - summary is compact, transcript grows unbounded
```

---

### **7. HOW JANUSEC + CHATBOT PATTERNS APPLY**

#### **From JanuSec (80% of Hard Problems Solved)**

```
JanuSec Pattern              agentLUMEN Equivalent
─────────────────────────────────────────────────────────
21-stage detection pipeline  → 5-stage decision pipeline (simpler)
Alert triage + routing       → Human approval queue (same logic)
SIEM integration             → DataDog/PowerBI setup (same tools)
Threat detection             → Security Observer (same pattern)
Multi-domain correlation     → Bi-temporal decision trace (temporal analysis)
```

**Translation**: You've already built sophisticated detection pipelines. This is easier.

#### **From Agentic Chatbot (NLP Foundation Exists)**

```
Chatbot Pattern              agentLUMEN Equivalent
─────────────────────────────────────────────────────────
NLP (83.3% accuracy)         → Pricing/support agents (change prompts)
Redis conversation cache     → Session cache (3h TTL - reuse code)
RAG retrieval                → Context Graph queries (same pattern)
Intent classification        → Agent routing (expand classes)
Multi-turn context           → Three-tier memory (Tier 0-1-2)
```

**Translation**: Your chatbot is 90% of a customer support agent already.

---

### **8. 6-WEEK MVP (WHAT YOU'RE BUILDING)**

#### **Scope**

```
✅ INCLUDED (MVP)
├─ Single pricing agent (discount recommendations)
├─ Transaction firewall (basic policies: >$250 → human)
├─ Bi-temporal logging (PostgreSQL with temporal columns)
├─ Redis session cache (single instance, 4GB)
├─ Stripe integration (payments)
├─ Shopify webhook (order sync)
├─ Slack approval queue (human-in-loop)
├─ Basic monitoring (DataDog or Grafana)
├─ Rule-based fallback (if agent fails)
└─ Approval dashboard (React SPA)

❌ DEFERRED (Phase 2+)
├─ Multi-agent orchestration (single agent first)
├─ Redis cluster (single instance sufficient for 5K sessions)
├─ Vector DB (PostgreSQL full-text search for MVP)
├─ Neo4j bi-temporal graph (PostgreSQL temporal columns)
├─ MITRE ATLAS detection (basic regex only)
├─ Colo deployment (cloud-only for MVP)
└─ Advanced ABAC policies (simple if/then rules)
```

#### **Timeline**

```
Week 1: Core Pipeline + Memory (port JanuSec + Chatbot patterns)
Week 2: Transaction Firewall + Stripe (policy engine + payments)
Week 3: Observability + Security (monitoring + basic observer)
Week 4: Integrations + Testing (inventory + end-to-end tests)
Week 5-6: Beta Launch + Ramp (20% autonomy, <5% error rate)
```

#### **Success Criteria**

```
End of Week 6:
✓ Agent proposes pricing decisions
✓ Transaction Firewall enforces policies
✓ Decision logs capture bi-temporal audit trail
✓ Stripe integration works (test mode)
✓ Graceful degradation tested (agent fails → rules work)
✓ 20% autonomy proven with <5% error rate
✓ Ready for limited production (100-200 orders/day)
```

---

### **9. WHAT YOU NEED TO KNOW BY HEART**

#### **For David (Executive Pitch)**

1. **"We don't need recursive learning - we need memory hygiene"**
   - Chat history ≠ facts
   - Facts live in DB, not transcript
   - Forced retrieval prevents hallucination

2. **"Cart is canonical state - no drift possible"**
   - Draft order in PostgreSQL is truth
   - Agent always queries live data
   - Can't hallucinate cart contents

3. **"We're porting proven patterns, not building from scratch"**
   - JanuSec pipeline → Orchestrator (simpler version)
   - Chatbot NLP → Pricing agent (change prompts)
   - 4-6 weeks realistic because we've solved this before

4. **"Redis scales to 100K+ users with sharding"**
   - Start with single instance (MVP)
   - Cluster when traffic hits 10K sessions
   - Cost: $0.01/session/month

5. **"Logs are compliant by design"**
   - Bi-temporal schema (PostgreSQL)
   - Hot/warm/cold tiers ($85/month for 1M decisions/day)
   - ISO 42001, EU AI Act Article 17 ready

#### **For Technical Discussions**

1. **Three-tier memory pattern**:
   - Tier 0: In-prompt (last 6-12 turns)
   - Tier 1: Redis (rolling summary + KV state, 3h TTL)
   - Tier 2: Vector store (semantic search - Phase 2)
   - Tier 3: Bi-temporal logs (immutable audit trail)

2. **Forced retrieval rule**:
   - Any claim about price, stock, specs, delivery → MUST retrieve live
   - Cache retrieval results (5min TTL), not model outputs
   - Never trust chat memory for facts that can change

3. **Cart as canonical state**:
   - CREATE TABLE draft_orders (canonical cart state)
   - Agent queries draft_order + live_catalog + user_constraints
   - Can't hallucinate because cart is in DB

4. **Redis scaling**:
   - MVP: Single instance (4GB, 5K sessions)
   - Production: Cluster (3 shards × 16GB = 48GB, 100K+ sessions)
   - Eviction policy: allkeys-lru (prioritize session KV state)

5. **Log storage tiers**:
   - Hot (7 days): PostgreSQL ($50/month)
   - Warm (90 days): BigQuery ($25/month)
   - Cold (7 years): S3 Glacier ($10/month)
   - Total: $85/month for complete audit trail

---

### **10. DECISION FRAMEWORK (WHY THESE CHOICES)**

#### **Why Not "Recursive Learning"?**

**Considered**: Fine-tune GPT on user-specific data
**Rejected**: Too expensive, too slow, doesn't solve hallucination
**Chose**: Memory hygiene + forced retrieval (cheaper, faster, accurate)

#### **Why PostgreSQL (Not Neo4j) for Bi-Temporal?**

**Considered**: Neo4j for graph queries
**Rejected**: Overkill for MVP, learning curve too steep
**Chose**: PostgreSQL with temporal columns (80% as good, 20% complexity)

#### **Why Cart as Canonical State?**

**Considered**: Store cart state in chat context
**Rejected**: Drift happens (agent forgets updates)
**Chose**: PostgreSQL draft_orders table (always correct, no drift)

#### **Why Redis Cluster (Not Single Instance)?**

**Considered**: Single Redis instance for all users
**Rejected**: Won't scale past 10K sessions
**Chose**: Start single (MVP), migrate to cluster (production)

#### **Why Hot/Warm/Cold Tiers (Not Just PostgreSQL)?**

**Considered**: Keep all logs in PostgreSQL forever
**Rejected**: 1M decisions/day × 7 years = 2.5TB (expensive)
**Chose**: Tiered storage - hot for queries, cold for compliance

---

## SUMMARY

**v5 Updates**:
1. ✅ Addressed "recursive learning" → memory hygiene + retrieval discipline
2. ✅ Added Redis scaling architecture (cluster + sharding)
3. ✅ Added log storage at scale (hot/warm/cold tiers)
4. ✅ Clarified 6-week MVP vs end-state
5. ✅ Showed JanuSec + Chatbot pattern reuse
6. ✅ Added cart-as-canonical-state pattern
7. ✅ Created comprehensive ASCII architecture diagrams

**Key Takeaway**: You don't need to learn new patterns. You're combining JanuSec (orchestration) + Chatbot (NLP) into a single e-commerce agent platform.

**Confidence Level**: HIGH - The hard problems are solved. This is execution, not R&D.

---

**Ready to present to David and start Week 1 sprint?**
