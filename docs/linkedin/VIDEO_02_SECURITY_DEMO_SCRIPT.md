# ShopSquire Video 2
## Security Demo Runbook

Audience: security leaders, AI architects, technical buyers

---

## Goal

Show that ShopSquire does not treat multimodal ecommerce as only a recommendation problem.
It also treats it as a security and trust problem.

---

## Click Path

1. Open `http://127.0.0.1:5173`
2. Open a fresh chat session
3. Upload one clean laptop image first
4. Show the image lane is treated as benign
5. Open `Decision Trace`
6. Click `Security Matrix`
7. Explain that benign images should not create false positives
8. Upload a suspicious image with QR/OCR or hidden instruction content
9. Show:
   - flagged status
   - OCR or QR evidence
   - security tags
   - matrix/trace correlation
10. Upload `apple-red.jpg`
11. Explain:
   - this is not a threat by itself
   - it is off-domain for the merchant catalog
   - ShopSquire soft-warns instead of fabricating product matches

---

## 60-Second Script

`In multimodal ecommerce, the hard problem is not only finding similar products. It is deciding what to trust.`

`So the platform inspects image-driven queries for relevance and safety at the same time. A clean laptop image should pass quickly and produce recommendations. A suspicious image with QR or OCR signals should be surfaced with evidence. And an off-domain image should not be forced into a misleading product result.`

`That is why the Security Matrix exists inside the same decision trace. It lets the operator see what was detected, why it was flagged, and how that affected the recommendation path.`

`The value is practical: fewer bad recommendations, better analyst visibility, and safer multimodal commerce workflows.`

---

## What To Emphasize

- benign should stay benign
- suspicious should show evidence, not just a red label
- off-domain should warn cleanly, not hallucinate a match
- security logic should support commerce, not fight it
