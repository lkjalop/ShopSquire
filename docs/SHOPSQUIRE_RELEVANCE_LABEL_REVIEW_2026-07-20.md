# ShopSquire relevance-label human review

The evaluated Qwen model did not create these labels. They are an independent draft, but they are
not production ground truth until a named human reviews them. Grades are `2 = highly relevant`,
`1 = acceptable/stretch`, and `0 = irrelevant or violates a hard constraint`.

## Review policy

Confirm these rules before signing:

1. An explicit maximum budget is hard for the primary slate. Out-of-budget products may only score
   `1` when they appear in a separately labeled stretch tier; otherwise they score `0`.
2. A minimum budget is a preference unless the buyer says "at least".
3. A product with unknown minimum-capability evidence cannot score `2` for a named workload.
4. Brand exclusions are hard.
5. Currency must be normalized before comparing against a budget. A USD product is not automatically
   in an AUD budget because the numeric amount is lower.
6. A malformed SKU/category identity is `0` until catalog identity is corrected.

## Eight decisions

### 1. `brand_negation:0`

Query: `a good laptop but not Apple`

Draft: Dell DB16255, Lenovo IdeaPad Slim 3x, and Lenovo IdeaPad Slim 3i are grade 2; the
remaining non-Apple laptops are grade 1. Confirm whether the $3,699 HP OmniBook and $4,894 ASUS
ProArt are genuinely acceptable without a stated budget, or should be 0/held out as unbounded
stretch products.

### 2. `budget_band:0`

Query: `laptop between $1200 and $1800`

Draft: only Dell DB16255 ($1,399 AUD) and MSI Modern 15 ($1,499 AUD) are grade 2. Every product
outside the range is grade 0. This directly implements the hard maximum and preferred minimum.

### 3. `persona_creator:0`

Query: `laptop for video editing and streaming on twitch`

Draft: ASUS ProArt, MSI Katana RTX 4070, and Dell G16 RTX 4070 are grade 2; other discrete-GPU
options are grade 1. Confirm the intended default is simultaneous 1080p work. Also confirm that the
USD gaming SKUs may be compared only after currency normalization.

### 4. `search_budget:0`

Query: `gaming laptop under $2000`

Draft: all seven `GAM-*` products priced $1,199-$1,699 USD are grade 2, the $1,919 AUD ASUS TUF is
grade 1, and products above $2,000 are grade 0. This slate is not sealable until the evaluator
normalizes USD and AUD to one buyer currency.

### 5. `search_university:0`

Query: `recommend a laptop for university`

Draft: balanced 16 GB/general-study systems are grade 2; entry-level or expensive systems are
grade 1. `HDD-A9AE2F06` is grade 0 despite a laptop title because its SKU/category identity is
malformed. Confirm general study is the baseline and degree-specific software remains a follow-up.

### 6. `workload_ai_finetune:0`

Query: `laptop for fine-tuning small language models locally`

Draft: Lenovo Legion Pro 7 and HP OMEN MAX are grade 2; lower-tier discrete-GPU products are grade
1; products without suitable GPU evidence are 0. Review the actual `gpu_vram_gb`, RAM, CUDA/platform,
and thermal evidence for every grade 1/2. Product family names alone are insufficient.

### 7. `workload_cyberpunk:0`

Query: `laptop that can run cyberpunk 2077`

Draft: RTX 4060/4070 `GAM-*` products are grade 2 and expensive catalog alternatives are grade 1.
Confirm the target is current recommended requirements at 1080p/60 FPS, not merely minimum launch.
Currency normalization still applies.

### 8. `workload_valorant_fps:0`

Query: `i want to play valorant at 144fps`

Draft: all seven `GAM-*` systems and the $1,919 AUD ASUS TUF are grade 2; expensive alternatives
are grade 1. Confirm sustained native-1080p 144 FPS is the target and that display refresh rate
without CPU/GPU evidence cannot earn grade 2.

## Sign-off

After reviewing the candidate specifications and the six policy rules, update
`tests/golden/relevance_labels.json`:

```json
"review_status": "human_sealed",
"human_reviewed_by": "<reviewer name or stable identifier>"
```

Record any grade changes in the same commit. A second reviewer remains required before a production
100% rollout; one named review is sufficient for a controlled demo canary.
