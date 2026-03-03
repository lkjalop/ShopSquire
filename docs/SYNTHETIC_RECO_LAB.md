# Synthetic Recommendation Lab (Multi-Category)

This lab seeds synthetic product permutations for:
- `laptops` (from `docs/laptop-products-exp.txt` + fallback templates)
- `fashion` (apparel/footwear style/size/color variants)
- `homewares` (Target/Kmart-like room + utility variants)

It then:
1. Seeds interactions/orders/sales metrics.
2. Runs ALS training for collaborative filtering scores.
3. Evaluates recommendation behavior across category scenarios.
4. Verifies bi-temporal decision logging (`valid_*` + `system_*`).

## Run

```powershell
python scripts/run_multicategory_synthetic_lab.py `
  --categories laptops,fashion,homewares `
  --per-category 80 `
  --users 45 `
  --interactions-per-user 35 `
  --days-back 90 `
  --output docs/synthetic_reco_lab_report.json
```

## Output

- JSON report: `docs/synthetic_reco_lab_report.json`
- Key sections:
  - `seed_catalog`
  - `seed_interactions`
  - `als_training`
  - `evaluation.category_precision`
  - `evaluation.overall_precision`
  - `evaluation.bitemporal_trace_ok_ratio`
  - `evaluation.recommended_training_actions`

## How To Read Results

- If `fashion` or `homewares` precision is low:
  - Expand synonyms and slot extraction for that domain in NLP/Intent.
  - Add domain examples into recommendation retrieval/rerank tests.
- If overall precision is low:
  - Increase interaction quality and retrain ALS nightly.
  - Tune bandit arm weights per category.
- If `bitemporal_trace_ok_ratio < 1.0`:
  - Investigate decision log persistence and enforce CI checks on `valid_from/system_from`.

