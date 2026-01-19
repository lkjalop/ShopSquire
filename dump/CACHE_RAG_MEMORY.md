# CacheRAG & Memory Hygiene (Per‑User, Per‑Turn)

Principles
- Truth lives in authoritative stores; chat history is not a source of truth.
- Cache retrieval results (objects + provenance), not generated text.
- Keep memory bounded with rolling summaries and KV state.

Redis Keys (examples)
- session:{uid}:summary  (3h TTL) → rolling narrative for LLM friendliness
- session:{uid}:kv_state (3h TTL) → {budget_max, locale, draft_cart_id, …}
- session:{uid}:recent_retrieval (5–10 min TTL) → [{sku, price, stock, source_ts}, …]

Forced Retrieval Triggers
- Any claim about price, stock, specs, delivery, policy, or order status
- Low confidence (<threshold) → Corrective RAG (query expansion → keyword fallback)

Prompt Budgeting
- Last 6–12 turns only + compressed summary; rest in Redis

Pseudocode
```python
class Memory:
    def get_context(self, uid, user_input):
        summary = redis.get(f"session:{uid}:summary")
        kv = redis.get(f"session:{uid}:kv_state")
        need_live = requires_live_data(user_input)
        live = query_live_sources(kv) if need_live else {}
        cache = cache_lookup(user_input, kv)
        return {"summary": summary, "kv": kv, "live": live or cache}

    def update(self, uid, user_input, agent_output, facts):
        new_summary = compress(summary, user_input, agent_output)
        redis.setex(f"session:{uid}:summary", ttl3h, new_summary)
        kv_update = extract_kv(agent_output)
        redis.setex(f"session:{uid}:kv_state", ttl3h, kv_update)
        if facts:
            redis.setex(f"session:{uid}:recent_retrieval", ttl5m, facts)
```

Notes
- Do not persist full transcripts; export on demand for audits if needed.
- TTLs tuneable per tenant; store volatility determines cache TTL.
