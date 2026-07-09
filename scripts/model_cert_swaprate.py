#!/usr/bin/env python
"""Post-W model certification — guard-pass-rate under PRODUCTION flags (2026-07-09).

The earlier A/B rounds (docs/MODEL_AB_FINAL_VERDICT_2026-07-08.md) measured raw prose with the
guard OFF. Post-W the preamble changed materially (knowledge pool + workload-fit facts + Steam
publisher facts) and the production posture is async + guard ON — so the certification metric
is now: FOR EACH MODEL, how often does its prose actually REACH THE BUYER (swap-rate) vs get
guard-rejected? A model that writes beautiful ungrounded prose certifies WORSE than a plain one
that cites the evidence.

    PYTHONIOENCODING=utf-8 CERT_MODELS="qwen3:14b,gemma3:12b" python -m scripts.model_cert_swaprate

Restarts uvicorn per model with PRODUCTION flags (no guard/narration overrides — feature_flags.json
drives async+force), warms the model, runs the prose battery, polls each job to terminal state.
Leaves the backend DOWN at the end. Report -> <scratchpad>/model_cert_swaprate.md
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time

import httpx

from tests.utils import default_headers

BASE = "http://127.0.0.1:8080"
H = {**default_headers(), "Content-Type": "application/json"}
MODELS = [m.strip() for m in os.getenv("CERT_MODELS", "qwen3:14b,gemma3:12b").split(",") if m.strip()]
SCRATCH = os.getenv("SCRATCHPAD_DIR", ".")

# The prose battery: queries that MUST produce guarded prose (from the frozen swap-rate golden).
PROSE_QUERIES = [
    ("fit_conflict", "i need something for training llm models, is 3500 enough? if i go higher what then?"),
    ("knowledge", "what's the real difference between an 8gb and 16gb gpu for AI work?"),
    ("game_fit", "gaming laptop for valorant under 1900"),
    ("ai_honesty", "i want to fine tune a 7b model locally under 2500"),
    ("payment", "i want to spend around 25000 on machines for my team — do you offer payment plans?"),
    ("budget_yn", "is 1800 enough for gaming?"),
    ("game_steam", "gaming laptop for cyberpunk 2077 and valorant under 1900"),
]

BASE_ENV = {
    "OLLAMA_KEEP_ALIVE": "30m", "PYTHONIOENCODING": "utf-8",
    "MULTI_INTENT_PLANNER_ENABLED": "1", "MULTI_INTENT_LLM_BINDING_ENABLED": "1",
    "LLM_PLANNER_ENABLED": "1", "FULFILLMENT_DEMO_ENABLED": "1", "COMMERCE_CATALOG_ENABLED": "1",
    "FULFILLMENT_SUPPLIER_TRANSPORT": "sandbox", "FULFILLMENT_AUTONOMOUS_RFQ": "0",
    # NO narration/guard overrides: production feature_flags.json drives async + force + guard ON.
}


def kill_8080() -> None:
    import psutil
    for p in psutil.process_iter(["cmdline"]):
        try:
            cmd = " ".join(p.info["cmdline"] or [])
            if "uvicorn" in cmd and "8080" in cmd:
                p.kill()
        except Exception:
            pass
    time.sleep(2)


def warm(model: str) -> None:
    try:
        t0 = time.time()
        httpx.post("http://127.0.0.1:11434/api/generate",
                   json={"model": model, "prompt": "ok", "stream": False, "keep_alive": "30m"}, timeout=240)
        print(f"[info] warmed {model} in {time.time()-t0:.0f}s")
    except Exception as exc:
        print(f"[warn] warm {model} failed: {str(exc)[:80]}")


def launch(model: str) -> subprocess.Popen:
    env = {**os.environ, **BASE_ENV}
    for k in ("OLLAMA_SMALL_MODEL", "OLLAMA_MEDIUM_MODEL", "OLLAMA_BIG_MODEL", "OLLAMA_EXPERT_MODEL",
              "OLLAMA_SUMMARY_MODEL", "OLLAMA_DEFAULT_MODEL", "MULTI_INTENT_LLM_MODEL", "LLM_PLANNER_MODEL"):
        env[k] = model
    for k in ("RECOMMEND_NARRATION_FORCE", "RECOMMEND_NARRATION_MODE", "RECOMMEND_NARRATION_TIMEOUT_SEC",
              "OLLAMA_SUMMARY_TIMEOUT_S", "OLLAMA_SUMMARY_THINK", "COMMERCE_NARRATION_GUARD"):
        env.pop(k, None)
    return subprocess.Popen([sys.executable, "-m", "uvicorn", "src.app.main:app",
                             "--host", "127.0.0.1", "--port", "8080"],
                            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def wait_health(timeout: int = 150) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            if httpx.get(f"{BASE}/healthz", timeout=3).status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(3)
    return False


def run_query(model: str, name: str, q: str) -> dict:
    c = httpx.Client(timeout=120)
    t0 = time.time()
    try:
        b = c.post(f"{BASE}/api/v1/chat/query", headers=H,
                   json={"uid": f"cert-{model.replace(':','_')}-{name}", "query": q}).json()
    except Exception as exc:
        return {"outcome": "request_error", "detail": str(exc)[:80]}
    job = b.get("llm_summary_job_id")
    if not job:
        return {"outcome": "no_job", "latency_s": round(time.time() - t0, 1)}
    for _ in range(32):
        time.sleep(1.25)
        try:
            nd = c.get(f"{BASE}/api/v1/recommend/narration/{job}", headers=H).json()
        except Exception:
            continue
        if nd.get("status") in ("done", "error"):
            out = {"latency_s": round(time.time() - t0, 1), "prose": (nd.get("assistant_message") or "")[:220]}
            if nd.get("assistant_message"):
                out["outcome"] = "prose_swap"
            elif nd.get("guard") == "rejected":
                out["outcome"] = "guard_rejected"
                out["violations"] = nd.get("violations")
            elif nd.get("guard") == "error":
                out["outcome"] = "guard_error"
            else:
                out["outcome"] = nd.get("status")
            return out
    return {"outcome": "pending_timeout"}


def main() -> int:
    results: dict = {}
    for model in MODELS:
        print(f"\n[info] === {model}: restart + warm ===")
        kill_8080()
        warm(model)
        proc = launch(model)
        if not wait_health():
            print(f"[error] {model} backend never came up")
            proc.kill()
            results[model] = {"_error": "backend_down"}
            continue
        results[model] = {}
        for name, q in PROSE_QUERIES:
            r = run_query(model, name, q)
            results[model][name] = r
            print(f"    {name:14} {r.get('outcome'):16} {r.get('latency_s','')}s {r.get('violations') or ''}")
        proc.kill()
        kill_8080()

    lines = ["# Post-W model certification — guard-pass-rate under production flags", ""]
    for model, res in results.items():
        if "_error" in res:
            lines.append(f"## {model}: {res['_error']}")
            continue
        n = len(res)
        swaps = sum(1 for r in res.values() if r.get("outcome") == "prose_swap")
        rejects = sum(1 for r in res.values() if r.get("outcome") == "guard_rejected")
        lines.append(f"## {model}: swap {swaps}/{n} | rejected {rejects} | "
                     f"other {n - swaps - rejects}")
        for name, r in res.items():
            lines.append(f"- {name}: **{r.get('outcome')}** ({r.get('latency_s','?')}s)"
                         + (f" viol={r.get('violations')}" if r.get("violations") else ""))
            if r.get("prose"):
                lines.append(f"  > {r['prose']}")
        lines.append("")
    out = os.path.join(SCRATCH, "model_cert_swaprate.md")
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    with open(os.path.join(SCRATCH, "model_cert_swaprate.json"), "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\n[done] {out}\n[note] backend is DOWN — relaunch when ready.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
