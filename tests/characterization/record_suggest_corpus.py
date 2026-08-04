"""Golden-corpus recorder (V2 Phase 0) — characterize the LIVE legacy suggest() so the V2
rebuild has an oracle to diff against (docs/SHOPSQUIRE_V2_GREENFIELD_ROADMAP_2026-07-10.md §2).

Records, per battery case: request → full response → async-narration outcome → contract
violations, into tests/golden/suggest_corpus/{case_id}.json. Multi-turn cases share a uid so
session memory carries forward (the thing the old parity net could never cover).

KNOWN_WRONG discipline: battery entries may carry "known_wrong" describing where v1's
recorded behavior is a BUG and what the desired behavior is. The recorder copies it into the
snapshot verbatim — V2 must match the corpus EXCEPT where known_wrong says otherwise.

Usage (API must be up, run from repo root):
    python tests/characterization/record_suggest_corpus.py                      # full battery
    python tests/characterization/record_suggest_corpus.py --only offcatalog_a100
    python tests/characterization/record_suggest_corpus.py --no-narration       # skip prose poll

Auth: x-api-key from MERCHANT_API_KEY (env, falling back to .env). Never logged.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from src.app.contracts.suggest_contract import validate_response  # noqa: E402

BASE_URL = os.getenv("SHOPSQUIRE_BASE_URL", "http://127.0.0.1:8080")
SUGGEST_PATH = "/api/v1/recommend/suggest"
NARRATION_PATH = "/api/v1/recommend/narration/{job_id}"
CORPUS_DIR = REPO_ROOT / "tests" / "golden" / "suggest_corpus"
BATTERY_PATH = Path(__file__).parent / "batteries" / "starter_battery.json"
NARRATION_BUDGET_S = float(os.getenv("CORPUS_NARRATION_BUDGET_S", "20"))
REQUEST_TIMEOUT_S = float(os.getenv("CORPUS_REQUEST_TIMEOUT_S", "120"))


def _api_key() -> str:
    key = os.getenv("MERCHANT_API_KEY", "").strip()
    if not key:
        env_file = REPO_ROOT / ".env"
        if env_file.exists():
            for line in env_file.read_text(encoding="utf-8", errors="ignore").splitlines():
                if line.startswith("MERCHANT_API_KEY="):
                    key = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break
    if not key:
        sys.exit("MERCHANT_API_KEY not found in env or .env — cannot authenticate")
    return key


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=REPO_ROOT, text=True
        ).strip()
    except Exception:
        return "unknown"


def _poll_narration(client: httpx.Client, job_id: str) -> dict:
    """The async prose swap IS contract behavior (the swap-rate battery pins it) — record
    its outcome, bounded so a stuck job can't stall the whole recording run."""
    deadline = time.monotonic() + NARRATION_BUDGET_S
    last: dict = {"status": "pending"}
    while time.monotonic() < deadline:
        try:
            r = client.get(NARRATION_PATH.format(job_id=job_id))
            if r.status_code == 200:
                last = r.json()
                if last.get("status") not in (None, "pending"):
                    break
            else:
                last = {"status": f"http_{r.status_code}"}
                break
        except Exception as exc:  # narration poll must never kill the recorder
            last = {"status": "poll_error", "error": str(exc)[:200]}
            break
        time.sleep(1.5)
    # job record shape (recommend_narration_jobs.put_narration): {status, assistant_message,
    # storage_backend, ...redacted meta (guard categories etc.)}
    prose = str(last.get("assistant_message") or "")
    meta = {k: v for k, v in last.items() if k not in ("status", "assistant_message")}
    return {"job_id": job_id, "final_status": last.get("status"),
            "meta": meta, "prose_len": len(prose), "prose": prose[:400]}


def record_case(client: httpx.Client, case: dict, *, narration: bool, run_tag: str) -> dict:
    # run_tag keeps each recording run's session memory ISOLATED: a stable uid would inherit
    # the previous run's Redis session (shortlist/kv), silently polluting multi-turn cases.
    uid = f"corpus-{case['id']}-{run_tag}"
    turns_out = []
    for i, turn in enumerate(case["turns"]):
        params = {"query": turn["query"], "uid": uid, **(turn.get("params") or {})}
        t0 = time.monotonic()
        resp = client.get(SUGGEST_PATH, params=params)
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        body = resp.json() if resp.status_code == 200 else {"_http_error": resp.status_code}
        narration_out = None
        job_id = body.get("llm_summary_job_id") if isinstance(body, dict) else None
        if narration and job_id:
            narration_out = _poll_narration(client, job_id)
        turns_out.append({
            "turn": i,
            "request": {"path": SUGGEST_PATH, "params": params},
            "status_code": resp.status_code,
            "elapsed_ms": elapsed_ms,
            "response": body,
            "narration": narration_out,
            "contract_violations": validate_response(body) if isinstance(body, dict) else ["non_dict_body"],
        })
        print(f"  turn {i}: {resp.status_code} {elapsed_ms}ms "
              f"products={len((body or {}).get('products') or []) if isinstance(body, dict) else '-'} "
              f"class_hint={'off_catalog' if isinstance(body, dict) and body.get('off_catalog') else '-'}")
    return {
        "id": case["id"],
        "lane": case.get("lane", "unlabeled"),
        "notes": case.get("notes"),
        "known_wrong": case.get("known_wrong"),
        "meta": {
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "git_sha": _git_sha(),
            "base_url": BASE_URL,
            "uid": uid,
        },
        "turns": turns_out,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--battery", default=str(BATTERY_PATH))
    ap.add_argument("--only", help="record a single case id")
    ap.add_argument("--no-narration", action="store_true")
    args = ap.parse_args()

    battery = json.loads(Path(args.battery).read_text(encoding="utf-8"))
    cases = [c for c in battery if not args.only or c["id"] == args.only]
    if not cases:
        sys.exit(f"no case matched --only {args.only}")
    CORPUS_DIR.mkdir(parents=True, exist_ok=True)

    headers = {"x-api-key": _api_key()}
    run_tag = datetime.now(timezone.utc).strftime("%m%d%H%M%S")
    ok = fail = 0
    with httpx.Client(base_url=BASE_URL, headers=headers, timeout=REQUEST_TIMEOUT_S) as client:
        for case in cases:
            print(f"[{case['id']}] lane={case.get('lane')}")
            try:
                snapshot = record_case(client, case, narration=not args.no_narration, run_tag=run_tag)
                out = CORPUS_DIR / f"{case['id']}.json"
                out.write_text(json.dumps(snapshot, indent=1, ensure_ascii=False), encoding="utf-8")
                ok += 1
            except Exception as exc:
                print(f"  RECORD FAILED: {exc}")
                fail += 1
    print(f"\nrecorded={ok} failed={fail} -> {CORPUS_DIR}")


if __name__ == "__main__":
    main()
