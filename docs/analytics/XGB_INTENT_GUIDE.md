# XGBoost Intent Classifier Guide

This guide covers dataset format, training, and inference for the intent classifier.

## Dataset
- Columns: `text,label`
- Labels: choose a small, stable set (e.g., `price_filter`, `spec_filter`, `fraud_concern`, `inventory_check`).
- Example: see [data/xgb_intent_dataset.sample.csv](data/xgb_intent_dataset.sample.csv).

## Train
- Ensure the virtual environment is active and deps installed.
- Command:

  - Windows PowerShell:
    `D:/AI/agentLumen/ShopSquire/.venv/Scripts/python.exe scripts/train_xgb_intent.py --input data/xgb_intent_dataset.csv --output models/xgb_intent.pkl`

- Notes:
  - Input: path to CSV with `text,label`.
  - Output: model artifact at `models/xgb_intent.pkl`.

## Inference API
- Endpoint: `POST /api/v1/intent/infer`
- Body: `{ "text": "Find laptops under 1000" }`
- Curl (PowerShell quoting):
  `curl -X POST http://127.0.0.1:8080/api/v1/intent/infer -H "Content-Type: application/json" -d '{"text":"Find laptops under 1000"}'`

## Orchestrator Integration
- `xgb_intent` and `xgb_proba` are attached within `intent_result` by the orchestrator when a trained model is available.
- Fallback: heuristic/sklearn baseline if model is missing.

## Tips
- Balance classes to reduce bias; consider text normalization.
- Keep label taxonomy stable; version datasets and models.
- Add `tenant_id` as a feature only if governance permits and leakage is controlled.