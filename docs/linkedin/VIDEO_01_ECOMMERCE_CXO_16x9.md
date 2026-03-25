# ShopSquire Video 1
## Agentic Ecommerce for Better Buying Decisions
Audience: Chief AI Architect, CEO/tech buyer, Creative Director, CMO

---

## Slide 1 - Business Case

```text
+--------------------------------------------------------------------------------------------------+
| SHOPSQUIRE                                                                                       |
| Agentic ecommerce that helps buyers choose faster and with more confidence                       |
+--------------------------------------------------------------------------------------------------+
| PROBLEM                     | DESIGN CHOICE                    | WHY IT MATTERS                  |
|----------------------------|----------------------------------|---------------------------------|
| Buyers give weak signals   | Parallel specialist agents       | Faster, more relevant results   |
| Budget and use case shift  | Interleaved clarify/retrieve     | Better follow-up and less drift |
| Teams need proof           | Bitemporal decision trace        | Explainability and operator trust|
+--------------------------------------------------------------------------------------------------+
| Demo now: text recommendation + live trace + accessory upsell                                    |
+--------------------------------------------------------------------------------------------------+
```

Presenter notes:
- This is not "AI chat for shopping."
- It is a decision system that combines buyer intent, catalog fit, and operator visibility.
- The architectural goal is better recommendations with less guesswork.

---

## Slide 2 - Data, Retrieval, and Storage

```text
+--------------------------------------------------------------------------------------------------+
| DATA FLOW                                                                                        |
+--------------------------------------------------------------------------------------------------+
| Query / image / cart -> retrieval -> rerank -> trace -> action                                  |
+--------------------------------------------------------------------------------------------------+
| Retrieval modes used                                                                            |
| - semantic retrieval for product and FAQ grounding                                               |
| - visual and OCR-assisted retrieval for image-led shopping                                       |
| - cart/context retrieval for add-ons and bundle logic                                            |
+--------------------------------------------------------------------------------------------------+
| Storage story                                                                                   |
| - demo runtime can run on SQLite                                                                 |
| - production source of truth is PostgreSQL                                                       |
| - TimescaleDB is valuable when telemetry and decision history need time-series performance        |
| - cache/Redis improves repeat lookups and session speed                                          |
+--------------------------------------------------------------------------------------------------+
| Business reason: lower latency, better replayability, cleaner operator evidence                  |
+--------------------------------------------------------------------------------------------------+
```

Presenter notes:
- Be precise: in this demo, show what is active now.
- Describe Postgres and Timescale as the production architecture path, not a fake current dependency.
- If asked "why not one DB for everything?": because transaction integrity and time-series analytics have different access patterns.

---

## Slide 3 - Multimodal Demo

```text
+--------------------------------------------------------------------------------------------------+
| MULTIMODAL SHOPPING DEMO                                                                         |
+--------------------------------------------------------------------------------------------------+
| 1. Dell image            -> in-domain -> similar corporate-work laptops                          |
| 2. MacBook image         -> in-domain -> compare portability / price / work fit                  |
| 3. apple-red.jpg         -> off-domain -> soft warning, no fake Apple laptop jump                |
+--------------------------------------------------------------------------------------------------+
| Then close with:                                                                                 |
| - Why Recommended tab                                                                            |
| - Complexity tab with timing                                                                     |
| - Cart upsell with relevant accessories                                                          |
+--------------------------------------------------------------------------------------------------+
```

Presenter notes:
- This proves the platform is product-agnostic.
- Relevant images should retrieve products.
- Off-domain images should be flagged relative to the merchant catalog, not force a misleading result.

---

## Live Demo Click Path

1. Open `http://127.0.0.1:5173`
2. Ask: `show me laptops for corporate work between 1300 and 1600`
3. Open `Decision Trace`
4. Click `Why Recommended`
5. Click `Complexity`
6. Add the top Dell result to cart
7. Open cart and show `Recommended Add-Ons`
8. Explain that upsell is now accessory-led, not more laptops
9. Go back and upload:
   - `Dell 15 DC15255.webp`
   - `apple-mac - Copy.jpg`
   - `apple-red.jpg`
10. Show:
   - valid product matches for the laptop images
   - soft warning / unsupported behavior for `apple-red.jpg`

---

## 90-Second Script

`ShopSquire is built for one hard problem: buyers rarely describe what they need cleanly.`

`So instead of one monolithic model call, I use parallel specialist agents for intent, retrieval, ranking, and safety. That improves speed and lets the system combine budget, persona, use case, and stock availability in one pass.`

`The second architectural choice is interleaved thinking. The system can clarify and refine before it commits, which reduces context drift when the buyer changes budget, brand, or use case mid-session.`

`The third choice is a bitemporal decision trace. Every recommendation can be replayed and explained, which matters for operator trust, tuning, and governance.`

`In the live demo, I start with a text query for corporate work, open the trace so you can see why the system ranked these products, then move into cart upsell to show relevant accessories rather than random laptop spam.`

`Then I switch to multimodal search. Two laptop images are valid and produce relevant options. The apple image is intentionally off-domain for a laptop-heavy merchant, so ShopSquire warns instead of fabricating a match.`

`That is the point of the platform: grounded recommendations, visible reasoning, and safer multimodal commerce.`

---

## Honest Positioning

This does help you with hiring managers if you present it correctly.

What it demonstrates:
- systems design
- applied AI architecture
- multimodal retrieval thinking
- security-aware product design
- traceability and observability
- UX judgment, especially around misleading AI output

What would hurt you:
- overclaiming production scale
- pretending every storage mode is active in the demo
- using jargon without tying it to business outcomes

The strongest posture is:
- show the product
- show the trace
- show one limitation honestly
- explain the tradeoff you chose and why
