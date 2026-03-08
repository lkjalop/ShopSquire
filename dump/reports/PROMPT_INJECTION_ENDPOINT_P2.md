# Prompt Injection Endpoint + Adversarial Corpus (P2)

## Endpoints

- `GET /api/v1/email_security/prompt-injection/corpus`
  - Returns default adversarial prompt-injection corpus.
- `POST /api/v1/email_security/prompt-injection/run`
  - Runs corpus through `evaluate_email_security`.
  - Returns precision/recall/FPR summary and per-case outcomes.
  - Optionally writes report JSON (default on) to `dump/reports/prompt_injection_eval_report.json`.

## One-command demo

```bash
curl -X POST http://127.0.0.1:8080/api/v1/email_security/prompt-injection/run \
  -H "x-api-key: local-owner-key" \
  -H "Content-Type: application/json" \
  -d '{"persist_report":true}'
```

## Code

- Router: `src/app/routers/email_security.py`
- Corpus/eval: `src/app/security/prompt_injection_eval.py`
- Tests: `tests/security/test_prompt_injection_endpoint_corpus.py`
