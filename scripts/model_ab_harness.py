#!/usr/bin/env python
"""Model A/B harness — compare local Ollama brains on the platform's HARD query classes.

Answers two questions (see docs/MODEL_AB_REARCHITECTURE_ROADMAP_2026-07-07.md):
  Suite A — RAW domain reasoning (no grounding): does the model KNOW a laptop is a poor fit for LLM
            training? This is the decisive "is the model the bottleneck" test.
  Suite B — GROUNDED orchestration (catalog rows + KB floors in the prompt): does it synthesize an
            HONEST answer without hallucinating inventory, and can it plan which sources it needs?

Hits Ollama directly (/api/generate) so it needs NO backend restart and isolates the MODEL. Auto-skips
models that aren't pulled yet. Deterministic (temperature 0). Writes a side-by-side markdown report +
a JSON for scoring.

    ollama list                       # confirm which models are present
    python -m scripts.model_ab_harness
    # -> <scratchpad>/model_ab_report.md  (read this)  + model_ab_results.json

Override the model list:  MODEL_AB_MODELS="phi4,gemma3:12b,qwen3:14b" python -m scripts.model_ab_harness
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.request

OLLAMA = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
DEFAULT_MODELS = ["granite4:micro", "gemma3:12b", "phi4", "qwen3:14b"]
TIMEOUT = float(os.getenv("MODEL_AB_TIMEOUT_SEC", "90") or 90)

# The real catalog tiers (from the demo DB) used to GROUND Suite B — so we test synthesis, not the model's
# guess about our inventory.
_CATALOG = (
    "In-stock laptops for this query:\n"
    "  - Alienware 16 Aurora — $3,499 — GPU 8GB VRAM, 32GB RAM, 1TB SSD\n"
    "  - HP OMEN MAX 16 — $4,499 — GPU 16GB VRAM, 32GB RAM, 1TB SSD\n"
    "  - Lenovo Legion Pro 7 — $5,999 — GPU 24GB VRAM, 64GB RAM, 1TB SSD\n"
    "  - Lenovo LOQ 15 — $1,199 — GPU 8GB VRAM, 16GB RAM, 512GB SSD\n"
)
_KB = ("Use-case 'AI/ML workstation' required minimums: GPU 8GB VRAM, 32GB RAM, 1TB storage. "
       "Recommended for real training: 16GB+ VRAM.\n")
_ADVISOR = ("You are an honest shopping advisor. Be truthful even against the sale: if the budget or the "
            "product category is a poor fit, say so and explain why, then offer the best available option "
            "and the honest alternative. Never oversell. Keep it under 120 words.")

# ── Test cases ────────────────────────────────────────────────────────────────
SUITE_A = [  # raw domain reasoning, no grounding
    ("llm_train_hard", f"{_ADVISOR}\n\nBuyer: I need a laptop for training LLM models, budget $3,500. Is that enough? If I go higher, what then?"),
    ("vram_knowledge", "Concisely: how much GPU memory to (a) run a quantized 7B model, (b) QLoRA fine-tune a 7B, (c) fully train a 7B from scratch? Give rough numbers."),
    ("category_mismatch", f"{_ADVISOR}\n\nBuyer: what's the best laptop for hosting a production database serving 24/7?"),
    ("honest_upsell", f"{_ADVISOR}\n\nBuyer: is a $400 laptop good for 4K video editing?"),
    ("overreach", f"{_ADVISOR}\n\nBuyer: cheapest laptop that runs Cyberpunk 2077 maxed at 4K?"),
]
SUITE_B = [  # grounded orchestration
    ("grounded_fit", f"{_ADVISOR}\n\n{_KB}{_CATALOG}\nBuyer: I need a laptop for training LLM models, budget $3,500. Is that enough? If I go higher, what then? Recommend from the list only."),
    ("grounded_challenge", f"{_ADVISOR}\n\n{_KB}You recommended the Lenovo LOQ 15 (8GB VRAM, 16GB RAM, 512GB SSD) for AI/ML.\nBuyer: are you sure that's good for training? Why?"),
    ("grounded_compound", f"{_ADVISOR}\n\n{_CATALOG}\nBuyer: I need 15 work laptops under $1,400 each and one monitor. What information would you need to fulfil this, and what would you do?"),
    ("grounded_policy", f"{_ADVISOR}\n\nStore policy: 30-day returns on unopened items.\n{_CATALOG}\nBuyer: what's your return policy, and is $2,000 enough for a gaming laptop?"),
    ("tool_planning", f"{_ADVISOR}\n\n{_KB}{_CATALOG}\nBuyer: which of these is the cheapest that meets the ML minimums, and is that a competitive price right now? List exactly which data sources you'd consult to answer both halves."),
]


def _available_models() -> list[str]:
    try:
        req = urllib.request.Request(f"{OLLAMA}/api/tags")
        data = json.loads(urllib.request.urlopen(req, timeout=10).read())
        return [m.get("name", "") for m in data.get("models", [])]
    except Exception as exc:
        print(f"[warn] could not list Ollama models: {exc}", file=sys.stderr)
        return []


def _ask(model: str, prompt: str) -> tuple[str, float]:
    payload = {
        "model": model, "prompt": prompt, "stream": False,
        "keep_alive": os.getenv("OLLAMA_KEEP_ALIVE", "30m"),
        "options": {"temperature": 0, "num_predict": 400},
    }
    if "qwen3" in model.lower():
        payload["think"] = False   # qwen3 needs this or it stalls/returns thinking noise
    t0 = time.time()
    try:
        req = urllib.request.Request(f"{OLLAMA}/api/generate",
                                     data=json.dumps(payload).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
        data = json.loads(urllib.request.urlopen(req, timeout=TIMEOUT).read())
        return str(data.get("response") or "").strip(), time.time() - t0
    except Exception as exc:
        return f"[ERROR: {exc}]", time.time() - t0


_PRICE_RE = re.compile(r"\$\s?([\d,]{3,6})")
_ALLOWED_PRICES = {"3,499", "3499", "4,499", "4499", "5,999", "5999", "1,199", "1199", "2,000", "2000",
                   "1,400", "1400", "400", "3,500", "3500"}


def _auto_flags(case: str, text: str) -> dict:
    low = text.lower()
    flags = {
        "words": len(text.split()),
        "mentions_vram_ceiling": bool(re.search(r"24\s?gb|16\s?gb|vram|gpu memory", low)),
        "mentions_offcatalog": bool(re.search(r"cloud|desktop|workstation|server|rent|a100|h100", low)),
        "honest_negative": bool(re.search(r"not (ideal|the best|enough|recommend|suited)|isn'?t (ideal|enough)|"
                                          r"stretch|marginal|won'?t|struggle|poor fit|consider (a )?(desktop|cloud)", low)),
    }
    # hallucinated price = a $-figure not in the allowed set (Suite B only, where a catalog was given)
    if case.startswith("grounded"):
        prices = set(_PRICE_RE.findall(text))
        flags["hallucinated_price"] = sorted(p for p in prices if p not in _ALLOWED_PRICES)
    return flags


def main() -> int:
    models_env = os.getenv("MODEL_AB_MODELS")
    want = [m.strip() for m in models_env.split(",")] if models_env else DEFAULT_MODELS
    have = _available_models()
    models = [m for m in want if any(m == h or h.startswith(m + ":") or h == m for h in have)]
    missing = [m for m in want if m not in models]
    if missing:
        print(f"[info] not yet pulled (skipping): {', '.join(missing)}")
    if not models:
        print("[error] none of the target models are available. `ollama pull` them first.", file=sys.stderr)
        return 1
    print(f"[info] testing: {', '.join(models)}")

    cases = [("A", c, p) for c, p in SUITE_A] + [("B", c, p) for c, p in SUITE_B]
    results: dict = {"models": models, "cases": {}}
    for suite, case, prompt in cases:
        results["cases"][case] = {"suite": suite, "prompt": prompt, "answers": {}}
        for m in models:
            print(f"  [{suite}] {case:20} <- {m}")
            text, dt = _ask(m, prompt)
            results["cases"][case]["answers"][m] = {
                "response": text, "latency_s": round(dt, 1), "flags": _auto_flags(case, text),
            }

    scratch = os.getenv("SCRATCHPAD_DIR") or os.path.join(
        os.environ.get("TEMP", "."), "model_ab")
    os.makedirs(scratch, exist_ok=True)
    json_path = os.path.join(scratch, "model_ab_results.json")
    md_path = os.path.join(scratch, "model_ab_report.md")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    # ── side-by-side markdown ──
    lines = ["# Model A/B report", "",
             f"Models: {', '.join(models)}", "",
             "Auto-flags legend: 🧠 mentions VRAM/ceiling · 🌐 names off-catalog (cloud/desktop) · "
             "✅ honest-negative (admits poor fit) · ⚠️ hallucinated price (not in the given catalog)", ""]
    for case, blob in results["cases"].items():
        lines.append(f"## [{blob['suite']}] {case}")
        for m in models:
            a = blob["answers"][m]
            fl = a["flags"]
            badge = ("🧠" if fl.get("mentions_vram_ceiling") else "  ") + \
                    ("🌐" if fl.get("mentions_offcatalog") else "  ") + \
                    ("✅" if fl.get("honest_negative") else "  ") + \
                    ("⚠️" if fl.get("hallucinated_price") else "  ")
            lines.append(f"### {m}  {badge}  ({a['latency_s']}s, {fl['words']}w"
                         + (f", HALLUCINATED {fl['hallucinated_price']}" if fl.get("hallucinated_price") else "")
                         + ")")
            lines.append("> " + a["response"].replace("\n", "\n> ")[:1600])
            lines.append("")
        lines.append("**Human score (0-3 each): correctness / honesty / grounding / reasoning / concision → winner: ____**")
        lines.append("")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"\n[done] report: {md_path}\n       json:   {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
