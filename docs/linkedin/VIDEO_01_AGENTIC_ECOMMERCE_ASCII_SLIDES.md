# ShopSquire Video 1 - Agentic AI for Ecommerce (ASCII 16:9)

Purpose: LinkedIn video focused on architecture decisions and product relevance quality.
Target length: 4 to 6 minutes.
Flow direction: left -> right on every slide.

---

## Slide 1 - What ShopSquire Is

```text
+--------------------------------------------------------------------------------------------------+
| SHOPPER INPUTS                  | AGENTIC CORE                         | COMMERCE OUTCOME         |
| text + image + budget + intent  | parallel specialist teams + policy   | ranked products + why    |
|                                  | + evidence trace                     | + next best action       |
+--------------------------------------------------------------------------------------------------+
```

Talk track:
- ShopSquire is an agentic ecommerce decision system, not just a chatbot.
- It turns noisy shopper signals into explainable recommendations and safe actions.

Visual:
- Insert `where-macbook-msi.png`

---

## Slide 2 - Why Parallel Agentic Teams

```text
+--------------------------------------------------------------------------------------------------+
| SINGLE AGENT BOTTLENECK          | PARALLEL SWARM                       | BENEFIT                  |
| serial reasoning                 | NLP + retrieval + ranking + security | lower latency, better    |
| one context window, one lane     | run together, merge with policy      | coverage, less blindspot |
+--------------------------------------------------------------------------------------------------+
```

Talk track:
- In ecommerce, constraints conflict: budget, stock, persona, specs, risk.
- Parallel teams let each specialty reason independently before merge.

Visual:
- Insert `msi-shownearest.png`

---

## Slide 3 - Interleaved Thinking and Context Rot Control

```text
+--------------------------------------------------------------------------------------------------+
| PASS 1: detect intent/persona      -> PASS 2: retrieve candidates      -> PASS 3: rank + verify |
| PASS 4: security triage            -> PASS 5: explain + clarify next   -> PASS 6: memory update |
+--------------------------------------------------------------------------------------------------+
```

Talk track:
- Interleaving avoids stale assumptions from early turns.
- Persona and use-case are refreshed each pass, so recommendations stay relevant.

Visual:
- Insert `why-no-prod-intent.png`

---

## Slide 4 - Bitemporal Decision Trace (Why It Matters)

```text
+--------------------------------------------------------------------------------------------------+
| VALID_TIME (business truth then)   | TX_TIME (what system knew when)    | AUDIT VALUE              |
| what was true for user/catalog      | what model/policy saw at runtime    | reproducible postmortems |
+--------------------------------------------------------------------------------------------------+
```

Talk track:
- If a recommendation is questioned later, you can replay truth vs knowledge state.
- This is critical for governance, incident response, and model change safety.

Visual:
- Insert `no-laptops.png`

---

## Slide 5 - RAG Layers (Not One RAG)

```text
+--------------------------------------------------------------------------------------------------+
| CACHE RAG                    | TIMESCALE/SQL RAG                  | DOMAIN RAG                |
| fast short-horizon recall    | temporal history + trend context   | catalog/spec/policy docs  |
| session + hot query reuse    | behavior and drift over time       | deterministic grounding   |
+--------------------------------------------------------------------------------------------------+
```

Talk track:
- Different retrieval layers solve different time horizons.
- Cache RAG handles speed; temporal DB handles history; domain RAG handles truth.

---

## Slide 6 - CV + OCR + Visual Similarity Pipeline

```text
+--------------------------------------------------------------------------------------------------+
| IMAGE INGEST            -> OCR/Tesseract      -> CV embedding/OVR similarity -> rank fusion     |
| object/scene cues          text overlays          nearest candidates             with persona/use |
+--------------------------------------------------------------------------------------------------+
```

Talk track:
- CV finds visual neighbors; OCR extracts hidden textual constraints/signals.
- Final ranking is fused with persona and use-case, not image alone.

Visual:
- Insert `no-price-textoverlay.png`

---

## Slide 7 - Failure Handling as Product UX

```text
+--------------------------------------------------------------------------------------------------+
| NO MATCH IN BUDGET           -> SHOW NEAREST             -> ASK ONE CLARIFIER                    |
| do not hallucinate products     widen options safely        keep user in control                  |
+--------------------------------------------------------------------------------------------------+
```

Talk track:
- Honest failure handling is a trust feature.
- "No result" transitions into guided recovery, not dead-end output.

Visual:
- Insert `no-macbook.png`

---

## Slide 8 - What Makes This Different in Market

```text
+--------------------------------------------------------------------------------------------------+
| MANY TOOLS HAVE AI CHAT        | FEWER SHOW TRACEABLE MULTI-AGENT + SECURITY + TEMPORAL MEMORY |
| discovery/help/content          | with explicit "why" and evidence tags                           |
+--------------------------------------------------------------------------------------------------+
```

Talk track:
- This is positioned as governable agentic commerce, not only assistant UX.
- The moat is architecture: parallel reasoning + policy + auditable evidence.

---

## Slide 9 - Close: Proof and Credibility

```text
+--------------------------------------------------------------------------------------------------+
| CLAIM                        | PROOF ARTIFACT                                                |
| architecture quality         | decision trace screenshots + failure cases + nearest fallback  |
| safety and threat awareness  | security matrix + flagged OCR/QR/steg examples                |
| systems thinking             | tradeoff explanations and build-vs-buy rationale              |
+--------------------------------------------------------------------------------------------------+
```

Talk track:
- You are not proving perfection; you are proving engineering judgment under constraints.
- Show one success path and one failure path with trace evidence.

Visual:
- Insert `sec-matrix.png`

---

## Suggested Image Pack (2 to 4 images for this video)
- `where-macbook-msi.png` (multimodal input -> recommendations)
- `no-laptops.png` (transparent no-result handling)
- `msi-shownearest.png` (fallback UX and nearest alternatives)
- `sec-matrix.png` (governance and trust)

## Delivery Tips (LinkedIn)
- Keep architecture names, but define each in one plain-English sentence.
- Use one concrete user story: "student or worker with budget constraints".
- End with one design tradeoff you made and why.
