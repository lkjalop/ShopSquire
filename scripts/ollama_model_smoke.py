"""Quick Ollama model selection + generate smoke test.

Usage:
  - Ensure Ollama is running locally (default http://127.0.0.1:11434)
  - Optionally set OLLAMA_SMALL_MODEL / OLLAMA_BIG_MODEL envs
  - Run: python scripts/ollama_model_smoke.py

This prints model choices for sample queries, a brief complexity explanation,
and (if available) runs a short /api/generate call to verify connectivity.
"""

from __future__ import annotations

import asyncio
import os
from typing import List

from src.app.services.llm_provider import (
    select_ollama_model,
    complexity_explain,
    ollama_generate,
)


SAMPLES: List[str] = [
    "budget between $900 and $1400; gaming ultra graphics",
    "show me laptops for university between $1800 and $2100",
    "I got a bag that fits 14 inches; budget 1800",
    "compare macbook vs lenovo around $1500 with 32GB RAM",
]


async def run_query(q: str):
    model = select_ollama_model(q)
    cx = complexity_explain(q)
    print("\n=== Query ===")
    print(q)
    print("Model:", model)
    print("Complexity:", cx)
    # Only attempt generate when OLLAMA_URL is set and reachable
    if os.getenv("OLLAMA_URL"):
        try:
            resp = await ollama_generate(
                model,
                (
                    "Summarize the user's intent in one sentence and list top 2 "
                    "attributes to consider.\nUser Query: " + q
                ),
                options={"temperature": 0},
            )
            print("Response:", (resp.get("response") or "").strip()[:300])
        except Exception as e:
            print("Generate error:", e)
    else:
        print("Skipping /api/generate: OLLAMA_URL not set.")


async def main():
    print("Small model:", os.getenv("OLLAMA_SMALL_MODEL", "llama3:8b"))
    print("Big model:", os.getenv("OLLAMA_BIG_MODEL", "mixtral:8x7b"))
    print("OLLAMA_URL:", os.getenv("OLLAMA_URL", "(not set)"))
    for q in SAMPLES:
        await run_query(q)


if __name__ == "__main__":
    asyncio.run(main())
