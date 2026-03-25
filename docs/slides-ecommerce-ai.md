# ShopSquire Ecommerce AI Demo
> 3 slides, 16:9, left-to-right flow, reduced text

---

## Slide 1 - Why This Architecture

```text
+--------------------------------------------------------------------------------------------------+
| SHOPSQUIRE: BETTER BUYING DECISIONS, NOT JUST CHAT                                                |
+--------------------------------------------------------------------------------------------------+
| Buyer problem                    | System choice                 | Business result               |
|----------------------------------|-------------------------------|-------------------------------|
| Shoppers give partial context    | Parallel agent teams          | Faster relevant products      |
| "work laptop", "high school"     | search + ranking + security   | Fewer dead-end results        |
|                                  | run together                  | Better conversion             |
|                                  |                               |                               |
| Buyers change their mind         | Interleaved thinking          | Better follow-up questions    |
| budget, brand, use case shift    | clarify -> retrieve -> rank   | Less context rot              |
|                                  |                               |                               |
| Teams need proof                 | Bitemporal decision trace     | Explainable recommendations   |
| why this item? why not that one? | what happened + when          | Easier demo, audit, tuning    |
+--------------------------------------------------------------------------------------------------+
| Demo: text query -> ranked products -> Decision Trace -> cart upsell                             |
+--------------------------------------------------------------------------------------------------+
```

Talk track:
- ShopSquire is designed to improve buying confidence, not just answer questions.
- Parallel agents help because ecommerce decisions mix intent, price, stock, persona, and safety.
- The trace matters because operators can prove why an item was recommended.

---

## Slide 2 - Data and Retrieval Pipeline

```text
+--------------------------------------------------------------------------------------------------+
| HOW THE PIPELINE WORKS                                                                           |
+--------------------------------------------------------------------------------------------------+
| Input                      -> Retrieval                    -> Ranking -> Explain                  |
|--------------------------------------------------------------------------------------------------|
| Text query                 -> semantic retrieval           -> budget fit                          |
| Persona + use case         -> catalog filters              -> use-case fit                        |
| Image + OCR                -> visual/category checks       -> stock and trust signals             |
| Cart state                 -> accessory affinity           -> upsell / bundle logic               |
+--------------------------------------------------------------------------------------------------+
| What is real today                                                                                |
| - Semantic retrieval and cache-backed retrieval paths                                             |
| - Product/category filtering, reranking, and trace logging                                        |
| - Visual search plus OCR / off-domain image handling                                              |
| - Bundle pricing and accessory upsell                                                             |
+--------------------------------------------------------------------------------------------------+
| Storage story                                                                                     |
| - Local demo: SQLite-backed app runtime                                                           |
| - Production path: PostgreSQL as system of record                                                 |
| - TimescaleDB: useful for telemetry and decision history when running Postgres                    |
| - Redis/cache: fast state and repeated-query speedups                                             |
+--------------------------------------------------------------------------------------------------+
```

Talk track:
- Do not claim every storage mode is active in the local demo.
- Say the platform supports Postgres plus optional Timescale for time-series evidence and analytics.
- The business reason is simple: faster repeat retrieval, cleaner audit, and safer operations.

---

## Slide 3 - Multimodal Demo

```text
+--------------------------------------------------------------------------------------------------+
| CV / OCR DEMO: RELEVANT IMAGE, CLEAN IMAGE, OFF-DOMAIN IMAGE                                     |
+--------------------------------------------------------------------------------------------------+
| Image 1: Dell laptop              | Image 2: MacBook image           | Image 3: apple-red.jpg     |
|-----------------------------------|----------------------------------|-----------------------------|
| Valid in-domain image             | Valid in-domain image            | Off-domain for laptop store |
| Retrieve similar products         | Retrieve similar products        | Soft warning, no fake match |
| Add corporate-work framing        | Compare portability / price      | Show Security Matrix signal |
+--------------------------------------------------------------------------------------------------+
| Demo close                                                                                         |
| - Show Decision Trace "Why Recommended" for text results                                           |
| - Show cart upsell with accessories, not more laptops                                              |
| - Show off-domain image handling as product-agnostic platform logic                                |
+--------------------------------------------------------------------------------------------------+
```

Talk track:
- If the catalog is laptop-heavy, a fruit image should not drift into Apple laptops.
- That is the correct behavior for a product-agnostic platform: relevance depends on merchant inventory.
- End with cart upsell to show the system understands the full buying journey.
