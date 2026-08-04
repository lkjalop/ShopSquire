# ShopSquire — Vision-Model Utilization Strategy (2026-06-15)

How to get more out of vision/VLMs across the platform — ecommerce, security, fraud,
damage/warranty, and the fusion of vision with FAQ-RAG / question-decomposition /
intent-parsing. Grounded in (a) current cross-vertical research and (b) ShopSquire's
actual modules.

---

## 0. What the latest research says (2025–2026)

**Market / direction.** VLM market ~$3.84B (2025) → ~$41.75B (2035), ~27% CAGR.
**40%+ of new VLM deployments are at the edge / on-device** (privacy + latency). 2026 is
the "seeing → doing" year (Vision-Language-Action). [Precedence/Astute, hyscaler VLA]

**Ecommerce (directly applicable):**
- Fine-tuning a VLM (SigLIP) on ~1M product image-title pairs gave **+9.1% nDCG@5,
  +50% CTR, +14% conversion** (Mercari). [arXiv 2510.13359]
- **Multimodal RAG** (embed images alongside text chunks) improves retrieval **25–40%**;
  enables "black leather jacket with asymmetric zipper" to match even when the catalog
  describes it differently. [Milvus]
- **Ground each item image into an explicit natural-language description, then embed** for
  preference retrieval (VLM4Rec). [arXiv 2603.12625] — *this is literally ShopSquire's
  grounding-ladder pattern, but applied catalog-wide.*

**Security / fraud:**
- CLIP-style VLMs generalize across unseen deepfake generators; strongest 2026 detectors
  combine **anatomy-aware cues + part-level reasoning + VLM semantics**. [InsightFace Mar-2026]
- **AI-document-forgery detection**: font inconsistencies, layout anomalies, generative
  artifacts invisible to humans (receipts, invoices, IDs). [Microblink, Incode Deepsight]
- A single fraudster can mint thousands of synthetic IDs / forged docs / deepfakes in
  minutes — detection has moved from niche forensics to a core security layer. [Protegrity]

**Efficiency / reliability (how to serve it):**
- **Small VLMs (<10B)** for edge/routing: SmolVLM (256M+), Moondream, PaliGemma, Qwen2.5-VL.
- **Schema-aware decoding guarantees valid JSON** (JSL Vision Structured-8B, 0.730 json-diff).
- Hallucination mitigation: **vision-text re-attention** (Qwen-LookAgain), image-grounded
  guidance, explicit grounding heads. Caveat: VLMs **hallucinate coordinates** in grounded
  OCR but are **strong at structured JSON extraction** — extract, don't trust pixel coords.
  [arXiv hallucination lists, John Snow Labs 2026 field guide]

**Cross-vertical patterns to borrow:** manufacturing visual inspection (superhuman defect
detection) → ShopSquire damage triage; logistics +40–60% picking / −25% errors → SKU/label
matching; healthcare "precision over speed" + on-device privacy → fraud/PII handling.

---

## 1. Three reusable primitives (everything below builds on these)

1. **Ground-to-NL-then-embed** (research consensus + your grounding ladder): turn an image
   into structured text, embed that, retrieve/reason over it. Reuse for catalog search,
   damage, forgery, FAQ.
2. **Schema-constrained extraction**: never free-parse VLM output. Force a JSON schema →
   kills the silent `_extract_json` parse-failures in `product_identity_agent`.
3. **Vision-as-evidence, not vision-as-truth**: the VLM proposes; a deterministic check
   disposes (your grounding ladder + Authorization Engine). Use re-attention / image-grounded
   guidance to cut hallucination, and always carry a confidence + residual.

---

## 2. Ecommerce — better recommendation utilization

| Improvement | ShopSquire hook | Expected lift (research) |
|---|---|---|
| **Catalog-wide multimodal RAG**: offline-caption every product image with a VLM, embed the caption + image, RRF-merge with text retrieval | extend `grounding_ladder` + `candidate_retriever` (RRF already exists); store in pgvector | +25–40% retrieval, +14% conversion |
| **Fine-tune/adapt CLIP/SigLIP** on the catalog for visual similarity | `visual_search` service | +9.1% nDCG@5 |
| **Schema-constrained product identity** (guaranteed JSON) | `identify_product_from_image` | fewer silent identity failures |
| **Vision identity → constraints**, intersected with budget/category (don't let similarity override hard filters) | ties to today's P0 budget fix | correctness, not just speed |

---

## 3. Security + fraud — the biggest differentiation lift

ShopSquire already has steg, adversarial, QR/SSN, phash. The research says add **generative-
artifact / forgery detection** as the next layer:

- **Return-fraud (the #1 vector): AI-generated / edited damage photos.** Add a diffusion/GAN-
  artifact + CLIP-generalization detector to `cv_tier2_pipeline` (now cached). Combine with
  **EXIF/forensic + phash reuse + C2PA provenance** to catch reused/synthetic damage images.
- **Document forgery in email security**: forged invoices/receipts/POs (font/layout/artifact
  anomalies) — extend `email_security` attachment forensics with a VLM forgery check.
- **VLM-as-judge cross-check** (anti-hallucination via re-attention): "does this damage photo
  actually depict the ordered product?" → `claim_grounding` already does claim-vs-CV; upgrade
  it with a grounded VLM verdict + confidence.
- **Disposition through the Authorization Engine**: a fraud verdict is a privileged action →
  route through `authorize_action("fraud_disposition", …)` (quarantine on compromise). Keeps
  it provable + bounded.
- **Edge/on-device** small VLM for PII-bearing images (ANZ privacy) — analyze without sending
  the image off-box.

---

## 4. Damage detection → warranty → repair (vision-grounded autonomy)

The chain the platform should run, end-to-end:

```
photo ──VLM──> {damage_type, severity, affected_part, confidence}   (cv_triage / cv_tier2)
        │
        ├─ claim_grounding: does CV match the customer's claim?  (supported|needs_evidence|contradicted)
        ├─ warranty reasoning: VLM-read warranty terms + damage → covered? (accidental vs defect)
        ├─ repair-vs-replace: severity + part + cost → bounded decision
        └─ Authorization Engine disposes: refund / reship / request_customer_evidence / reject_under_policy
```

- Use **structured severity + part localization** (manufacturing-inspection pattern), but
  **trust the JSON, not the coordinates** (research caveat).
- The damage verdict **seeds** the FAQ/repair retrieval (next section) so the answer is
  grounded in what the model actually saw.
- This is exactly your bounded-autonomy doctrine: VLM proposes, deterministic policy +
  Authorization Engine disposes, customer-evidence path instead of an employee gate.

---

## 5. Vision × FAQ-RAG / graph / question-decomposition / intent (the fusion)

The high-leverage idea: **make the vision output a first-class input to NLP**, not a side
channel. Today `query_decomposer`, `faq_bank`, and `classify_image_intent` mostly run on text.

- **Vision seeds decomposition.** Cracked-screen photo + "is this covered and what'll it cost?"
  → `query_decomposer` splits into {warranty-eligibility, repair-cost, claim-grounding}; each
  sub-question retrieves from the FAQ/repair KB **conditioned on the VLM damage verdict**.
- **Multimodal intent.** The image should change the intent prior (visual_search vs cv_triage
  vs damage_claim vs forgery_review), fused in `Image_Text_Fusion_Agent` — not inferred from
  text alone. (Today the fusion only concatenates labels into the query string.)
- **Graph RAG.** Build product → known-issues → repair-playbook → warranty-terms as a graph
  (you already have Neo4j profile-gated); the decomposed sub-questions traverse it; the VLM
  damage type picks the entry node.
- **Grounded FAQ answers (anti-hallucination).** Answer FAQ/repair questions with image-grounded
  guidance: cite the retrieved KB chunk AND the VLM evidence; abstain when ungrounded (your
  decision-log already has an abstain policy). Use re-attention (Qwen-LookAgain pattern) for
  long multimodal answers.
- **Better intent parsing generally.** A small fast VLM (Moondream) as a cheap router:
  image → coarse intent + is-product-photo + has-damage + has-document → routes to the right
  heavy pipeline. Cheap, on-device, and feeds `query_classifier` / NQE.

---

## 6. Serving / efficiency (how to make all this fast + reliable)

- **Two-tier vision**: small/fast model (Moondream/SmolVLM) for routing + triage + off-topic
  gating; large model (Qwen2.5-VL) only when deep identity/forensics is needed. Ties directly
  to today's **image-hash cache** (`vision_cache.py`) and the `CV_IDENTITY_MODEL` knob.
- **Schema-aware decoding** everywhere → valid JSON, fewer silent failures.
- **Cache + pre-warm + (next) SSE streaming** so first paint is <1s.
- **Edge/on-device** option for PII images (privacy + latency).

---

## 7. Prioritized recommendations

1. **Catalog-wide multimodal RAG** (offline VLM captions + pgvector) — biggest ecommerce lift, reuses grounding ladder + RRF. *(+conversion)*
2. **Generative-forgery / diffusion-artifact detection** in `cv_tier2` + email attachments — biggest fraud/differentiation lift. *(return-fraud + BEC)*
3. **Vision-seeds-decomposition + multimodal intent** — fuse VLM verdict into `query_decomposer`/NQE/`Image_Text_Fusion_Agent`. *(answer quality)*
4. **Damage→warranty→repair chain** disposed by the Authorization Engine — the bounded-autonomy showcase.
5. **Schema-constrained vision output + two-tier (fast/deep) models** — reliability + the rest of the latency story (after the cache shipped today).

---

## Sources
- [Improving Visual Recommendation on E-commerce Platforms Using VLMs (arXiv 2510.13359)](https://arxiv.org/abs/2510.13359)
- [VLM4Rec: Multimodal Semantic Representation for Recommendation (arXiv 2603.12625)](https://arxiv.org/abs/2603.12625)
- [What are VLMs and how are they used in multimodal search? (Milvus)](https://milvus.io/ai-quick-reference/what-are-visionlanguage-models-vlms-and-how-are-they-used-in-multimodal-search)
- [March 2026 Deepfake Detection Papers: VLM Semantics (InsightFace)](https://www.insightface.ai/blog/march-2026-deepfake-detection-papers)
- [Top Deepfake Detection Software & AI Fraud Solutions for 2026 (Microblink)](https://microblink.com/resources/blog/best-deepfake-detection-software/)
- [Deepsight — Deepfake Detection (Incode)](https://www.incode.com/platform/deepsight)
- [AI Fraud Detection in 2026 (Protegrity)](https://www.protegrity.com/blog/ai-fraud-detection-in-2026-what-leaders-must-know)
- [Vision-Language Models Market (Precedence Research)](https://www.precedenceresearch.com/vision-language-models-market)
- [VLM Market to $41.75B by 2035 (Astute Analytica / GlobeNewswire)](https://www.globenewswire.com/news-release/2026/02/11/3236048/0/en/Vision-Language-Models-VLM-Market-Projected-to-Reach-USD-41-75-Billion-by-2035.html)
- [Vision-Language-Action (VLA) Guide for 2026 (Hyscaler)](https://hyscaler.com/insights/vision-language-action-vla-guide/)
- [Top 10 Vision Language Models in 2026 (DataCamp)](https://www.datacamp.com/blog/top-vision-language-models)
- [A 2026 Field Guide to Visual Document Processing (John Snow Labs)](https://www.johnsnowlabs.com/a-2026-field-guide-to-visual-document-processing/)
- [Qwen Look Again: re-attention to reduce hallucination (arXiv 2505.23558)](https://arxiv.org/html/2505.23558v2)
