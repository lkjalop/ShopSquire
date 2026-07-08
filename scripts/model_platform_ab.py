#!/usr/bin/env python
"""Platform-INTEGRATED model A/B: run each candidate model THROUGH the live backend on the LLM-dependent
flows (narration + multi-intent planning), not isolated prompts. Restarts uvicorn per model with the
model wired into every text path, probes /chat/query, captures the buyer-visible answer, compares.

    python -m scripts.model_platform_ab
    # -> <scratchpad>/model_platform_ab_report.md

Leaves the backend DOWN at the end (relaunch qwen3 yourself, or the caller does). ~4 restarts, ~10-15 min.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time

import httpx
import psutil

from tests.utils import default_headers

BASE = "http://127.0.0.1:8080"
H = {**default_headers(), "Content-Type": "application/json"}
MODELS = os.getenv("PLAT_AB_MODELS", "qwen3:14b,gemma3:12b,phi4,granite4:micro").split(",")
SCRATCH = os.getenv("SCRATCHPAD_DIR", os.path.join(os.environ.get("TEMP", "."), "model_ab"))

# LLM-dependent flows the user named. Two-turn flows carry recent_messages so the amendment planner sees prior context.
FLOWS = [
    ("fit_honest", [{"q": "i need something for training llm models, is 3500 enough? if i go higher what then?"}]),
    ("payment_plan_honesty", [{"q": "i want to spend around 25000 on machines for my team — do you offer payment plans or financing?"}]),
    ("deficit_reorder", [{"q": "i need 50 dell laptops but I think you only have a few in stock — am i ok waiting for a reorder?"}]),
    ("compound_multi", [{"q": "i need 15 work laptops under 1400 and a 27 inch monitor"}]),
    ("spec_deep", [{"q": "what's the real difference between an 8gb and 16gb gpu for AI work?"}]),
    ("return_warranty", [{"q": "my laptop screen cracked — what are my repair or warranty options?"}]),
    ("qty_change", [
        {"q": "add 15 dell laptops to my cart"},
        {"q": "actually make it 20"},
    ]),
    ("product_swap", [
        {"q": "i want 10 dell laptops"},
        {"q": "swap the dell for a lenovo instead"},
    ]),
    ("challenge", [
        {"q": "recommend a laptop for training llm models under 3500"},
        {"q": "are you sure? why would that be good for training?"},
    ]),
]

DEMO_ENV = {
    "OLLAMA_EMBED_KEEP_ALIVE": "60m", "OLLAMA_KEEP_ALIVE": "30m",
    "FULFILLMENT_DEMO_ENABLED": "1", "FULFILLMENT_AUTO_DRAFT_ON_COMMIT": "1",
    "HIPPOGRAPH_FEEDBACK_ENABLED": "shadow", "MARKET_PIPELINE_ENABLED": "1", "COMMERCE_CATALOG_ENABLED": "1",
    "MULTI_INTENT_PLANNER_ENABLED": "1", "MULTI_INTENT_LLM_BINDING_ENABLED": "1", "MULTI_INTENT_LLM_TIMEOUT_SEC": "30",
    "LLM_PLANNER_ENABLED": "1", "LLM_PLANNER_TIMEOUT_SEC": "25",
    "EVIDENCE_ORCHESTRATOR_ENABLED": "1", "EVIDENCE_LEG_BUDGET_SEC": "2.5",
    "RECOMMEND_NARRATION_FORCE": "1",   # brain ON — the whole point of this A/B
    "RECOMMEND_NARRATION_MODE": "blocking",  # MASTER SWITCH: flags file says "skip" (global mute!) — env wins
    "RECOMMEND_NARRATION_TIMEOUT_SEC": "100", # layer-3 mute: default 8s < model 12-30s -> prose ALWAYS timed out
    "OLLAMA_SUMMARY_TIMEOUT_S": "45",         # layer-6 mute: inner resilience timeout 25s+retry killed think-mode runs
    "OLLAMA_SUMMARY_THINK": "off",            # think auto-fires on "enough/why/compare" -> 30-60s; off = latency-fair A/B
    "COMMERCE_NARRATION_GUARD": "0",          # layer-7 mute: guard rejects prose citing the PREAMBLE'S own step-up facts (scope mismatch) — off for raw-prose A/B
    "FULFILLMENT_SUPPLIER_TRANSPORT": "sandbox", "FULFILLMENT_AUTONOMOUS_RFQ": "0", "PYTHONIOENCODING": "utf-8",
}


def kill_8080():
    for p in psutil.process_iter(["cmdline"]):
        try:
            cmd = " ".join(p.info["cmdline"] or [])
            if "uvicorn" in cmd and "8080" in cmd:
                p.kill()
        except Exception:
            pass
    for _ in range(30):
        try:
            httpx.get(f"{BASE}/healthz", timeout=2)
            time.sleep(1)
        except Exception:
            return True
    return False


def launch(model: str) -> subprocess.Popen:
    env = {**os.environ, **DEMO_ENV}
    for k in ("OLLAMA_SMALL_MODEL", "OLLAMA_MEDIUM_MODEL", "OLLAMA_BIG_MODEL", "OLLAMA_EXPERT_MODEL",
              "OLLAMA_SUMMARY_MODEL", "OLLAMA_DEFAULT_MODEL", "MULTI_INTENT_LLM_MODEL", "LLM_PLANNER_MODEL"):
        env[k] = model
    return subprocess.Popen([sys.executable, "-m", "uvicorn", "src.app.main:app", "--host", "127.0.0.1", "--port", "8080"],
                            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def wait_health(timeout=120) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            if httpx.get(f"{BASE}/healthz", timeout=3).status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(3)
    return False


def run_flow(uid: str, turns: list) -> dict:
    c = httpx.Client(timeout=180)
    recent = []
    last = {}
    for t in turns:
        body = {"uid": uid, "query": t["q"], "recent_messages": recent[-6:]}
        t0 = time.time()
        try:
            r = c.post(f"{BASE}/api/v1/chat/query", headers=H, json=body)
            last = r.json() if r.status_code == 200 else {"_status": r.status_code}
        except Exception as exc:
            last = {"_error": str(exc)[:120]}
        last["_latency_s"] = round(time.time() - t0, 1)
        recent.append({"role": "user", "content": t["q"]})
        recent.append({"role": "assistant", "content": (last.get("assistant_message") or "")[:300]})
    return last


def main() -> int:
    os.makedirs(SCRATCH, exist_ok=True)
    results = {}
    have = []
    try:
        tags = httpx.get("http://127.0.0.1:11434/api/tags", timeout=10).json()
        have = [m["name"] for m in tags.get("models", [])]
    except Exception:
        pass
    models = [m for m in MODELS if any(m == h or h.startswith(m + ":") for h in have)]
    print(f"[info] models to test through platform: {models}")

    for model in models:
        print(f"\n[info] === {model}: restarting backend ===")
        kill_8080()
        proc = launch(model)
        if not wait_health():
            print(f"[error] {model} backend did not come up; skipping")
            proc.kill()
            continue
        print(f"[info] {model} up — running {len(FLOWS)} flows")
        results[model] = {}
        for name, turns in FLOWS:
            out = run_flow(f"ab-{model.replace(':','_')}-{name}", turns)
            results[model][name] = {
                "msg": (out.get("assistant_message") or out.get("_error") or f"[{out.get('_status')}]")[:900],
                "latency_s": out.get("_latency_s"),
                "products": len(out.get("products") or []),
            }
            print(f"    {name:22} {results[model][name]['latency_s']}s  {results[model][name]['products']}p")
        proc.kill()
        kill_8080()

    with open(os.path.join(SCRATCH, "model_platform_ab_results.json"), "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    # side-by-side report
    lines = ["# Platform-integrated model A/B", "", f"Models: {', '.join(results.keys())}", ""]
    for name, _ in FLOWS:
        lines.append(f"## {name}")
        for m in results:
            a = results[m].get(name, {})
            lines.append(f"### {m}  ({a.get('latency_s')}s, {a.get('products')}p)")
            lines.append("> " + str(a.get("msg", "")).replace("\n", "\n> "))
            lines.append("")
        lines.append("**Winner: ____  (honesty / correctness / grounding / concision)**\n")
    with open(os.path.join(SCRATCH, "model_platform_ab_report.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"\n[done] report: {os.path.join(SCRATCH, 'model_platform_ab_report.md')}")
    print("[note] backend is DOWN — relaunch qwen3:14b when ready.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
