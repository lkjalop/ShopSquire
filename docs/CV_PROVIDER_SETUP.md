# CV Provider Setup & Configuration

This doc explains optional CV providers and configuration flags used by `ManagedCVProvider`.

## Providers
- `ollama` (default for local demos)
  - Env: `CV_PROVIDER=ollama`, `CV_MODEL=llava`
  - Requires Ollama running locally (127.0.0.1:11434) with a vision model (`llava`, `qwen2.5-vl`, `minicpm-v`).
  - The provider calls `/api/generate` and expects JSON or uses heuristic token extraction.
- `google`
  - Env: `CV_PROVIDER=google`
  - Requires Google Cloud Vision credentials/environment; code path uses `google.cloud.vision.ImageAnnotatorClient`.
- `none`
  - No CV calls; returns empty labels/text (tests may skip or proceed with fallbacks).

## Environment Variables
- `CV_PROVIDER`: `ollama` | `google` | `none`
- `CV_MODEL`: Model name for Ollama vision (e.g., `llava`, `qwen2.5-vl`, `minicpm-v`).
- `LLM_PROVIDER` / `LLM_MODEL`: Text LLM provider/model for rerank (e.g., `ollama`, `llama3:8b`).

## Local Demo Tips
- Validate models via the tags API:

```
Invoke-RestMethod -Method Get -Uri http://127.0.0.1:11434/api/tags
```

- Run presence tests that skip gracefully when models are missing:

```
& ".venv/Scripts/python.exe" -m pytest -q tests/cv/test_vision_models_presence.py
```

## Test Behavior
- Presence tests include timeouts and skip logic to avoid hangs when a model is slow/unavailable.
- E2E complaints tests mock the CV provider via `monkeypatch` and require `python-multipart` for file uploads.
