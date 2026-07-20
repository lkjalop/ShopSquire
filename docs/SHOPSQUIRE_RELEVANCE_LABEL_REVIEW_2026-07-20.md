# ShopSquire relevance-label human review

Regenerated against the authoritative AUD demo catalog on 2026-07-21. The evaluated Qwen model
did not create the existing labels. They remain an independent draft until a named human reviews
the candidate universe and grades. Grades are `2 = highly relevant`, `1 = acceptable/stretch`,
and `0 = irrelevant or violates a hard constraint`.

## Review policy

Confirm these rules before signing:

1. The primary slate must use the tenant settlement currency. A USD product is ineligible without
   approved, fresh FX evidence; its numeric price must not be compared with AUD.
2. An explicit maximum budget is hard for the primary slate. Out-of-budget products may score `1`
   only in a separately labeled stretch tier. A minimum is a preference unless stated as "at least".
3. A product with unknown minimum-capability evidence cannot score `2` for a named workload.
4. Brand exclusions are hard. A malformed SKU/category identity is `0` until corrected.
5. For a generic use case, value, portability, battery and build quality matter; raw performance
   alone does not make a product highly relevant.
6. Labels cover the plausible candidate slate, not merely products V2 happened to show.

## Eight decisions

### 1. `brand_negation:0`

Query: `a good laptop but not Apple`

Current AUD slate: `HDD-A9AE2F06`, `LAP-031E526F`, `LAP-04C4955F`, `LAP-10BFA3F6`,
`LAP-1886C355`, `LAP-234E845E`, `LAP-29EA2785`, `LAP-343A37BC`, `LAP-37144522`,
`LAP-38C5278D`.

Decision: confirm `HDD-A9AE2F06 = 0` because its identity is malformed. Decide whether premium
HP/ASUS products are acceptable (`1`) without a stated budget and which balanced Dell/Lenovo/MSI
systems deserve `2`. No Apple SKU may receive a non-zero grade.

### 2. `budget_band:0`

Query: `laptop between $1200 and $1800`

Current AUD slate, all inside the band: Dell DB16255 $1,399; MSI Modern Ultra 7 $1,499;
Lenovo IdeaPad Slim 3i $1,599; MacBook Air M5 $1,799; ASUS Vivobook S16 $1,278;
Lenovo IdeaPad 5 2-in-1 $1,274; HP Envy x360 $1,299; HP Laptop Ultra 5 $1,499;
MSI Modern Ultra 9 $1,499.

Decision: the old draft is stale because it graded seven in-band products `0`. Grade balanced
general-purpose products `2` and defensible niche/form-factor alternatives `1`; use `0` only for
an actual relevance or evidence defect.

### 3. `persona_creator:0`

Query: `laptop for video editing and streaming on twitch`

Current AUD slate: ASUS ProArt RTX 5070; Alienware RTX 5060; ASUS TUF RTX 5060; ASUS TUF RTX
4050; Alienware 16X RTX 5060; Lenovo Legion RTX 5090; HP OMEN RTX 5080. All satisfy the current
minimum capability evaluator.

Decision: confirm simultaneous 1080p editing/streaming as the baseline. Grade creator displays,
encoding capability, RAM/storage and workflow balance, not GPU tier alone. Professional 4K
headroom may distinguish `2` from `1` but must not be silently assumed as a minimum.

### 4. `search_budget:0`

Query: `gaming laptop under $2000`

Current eligible AUD slate: only `LAP-69763798`, ASUS TUF RTX 4050 at AUD $1,919. The seven old
`GAM-*` labels refer to USD rows and cannot be used in an AUD budget evaluation without FX.

Decision: grade the ASUS against generic current gaming capability. Also confirm that one honest
match is preferable to mixing currencies or silently widening the cap.

### 5. `search_university:0`

Query: `recommend a laptop for university`

Current slate: MacBook Neo 512GB/8GB at $1,099; MacBook Neo 256GB/8GB at $899; MacBook Air M5
512GB/16GB at $1,799.

Decision: general study is the baseline and named degree software is a refinement. The Apple-only
slate is a data-coverage warning: non-Apple systems with unknown battery evidence are currently
excluded from the meeting tier. Do not label them `0` solely because evidence is missing; record
the missing evidence and decide whether the UI should show them as `unknown/acceptable`, not
`meets`.

### 6. `workload_ai_finetune:0`

Query: `laptop for fine-tuning small language models locally`

Current AUD slate: ASUS ProArt RTX 5070; Alienware RTX 5060; Lenovo Legion RTX 5090; HP OMEN
RTX 5080.

Decision: review actual VRAM, RAM, CUDA/framework compatibility and thermal evidence. Use a
quantized 7B inference/small-LoRA baseline. Full fine-tuning of large models requires a clearly
labeled workstation/cloud path; family names alone cannot earn `2`.

### 7. `workload_cyberpunk:0`

Query: `laptop that can run cyberpunk 2077`

Current AUD slate: ASUS TUF RTX 5060; Alienware 16X RTX 5060; Lenovo Legion RTX 5090; HP OMEN
RTX 5080.

Decision: use current vendor/official evidence for a recommended 1080p/60 target. Treat the
5090/5080 systems as headroom, not automatically more relevant than balanced 5060 systems.

### 8. `workload_valorant_fps:0`

Query: `i want to play valorant at 144fps`

Current AUD slate: ASUS TUF RTX 5060; ASUS TUF RTX 4050; Alienware 16X RTX 5060; Lenovo Legion
RTX 5090; HP OMEN RTX 5080.

Decision: confirm sustained native-1080p 144 FPS. Refresh rate alone is insufficient without
CPU/GPU evidence. Expensive high-end systems may be acceptable headroom (`1`) while balanced
systems that meet the target may be more relevant (`2`).

## Sign-off

After checking the catalog specifications and recording grade changes in
`tests/golden/relevance_labels.json`, set:

```json
"review_status": "human_sealed",
"human_reviewed_by": "<your name or stable reviewer identifier>"
```

One named human review is sufficient for a controlled demo canary. Require an independent second
review before production 100% rollout. After sign-off, run three sealed replays; do not tune on the
test split between passes.
