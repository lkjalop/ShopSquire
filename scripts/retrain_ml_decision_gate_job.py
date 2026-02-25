#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser(description="Retrain ML decision gate in job mode (safe no-update behavior).")
    ap.add_argument("--python", default=sys.executable, help="Python executable to use.")
    ap.add_argument("--output", default="config/ml_decision_gate_model.json", help="Artifact output path.")
    ap.add_argument("--limit", type=int, default=8000)
    ap.add_argument("--min-samples", type=int, default=40)
    ap.add_argument("--min-tenant-samples", type=int, default=25)
    args = ap.parse_args()

    cmd = [
        args.python,
        "scripts/train_ml_decision_gate.py",
        "--output",
        str(args.output),
        "--activate",
        "--limit",
        str(args.limit),
        "--min-samples",
        str(args.min_samples),
        "--min-tenant-samples",
        str(args.min_tenant_samples),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    print(proc.stdout.strip())
    if proc.returncode == 0:
        return 0
    # Safe no-update path: do not fail job hard when insufficient data.
    out = (proc.stdout or "").strip()
    try:
        payload = json.loads(out) if out else {}
    except Exception:
        payload = {}
    if str(payload.get("reason") or "") == "insufficient_samples":
        print("No update applied due to insufficient samples; keeping existing active model.")
        return 0
    return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
