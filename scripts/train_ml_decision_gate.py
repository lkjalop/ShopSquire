#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.app.services.ml_decision_gate_training import save_gate_artifact, train_gate_from_db


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Train the shared email-security ML decision gate from incident decision traces/outcomes."
    )
    ap.add_argument("--tenant-id", default=None, help="Optional tenant scope; default trains across all tenants.")
    ap.add_argument("--limit", type=int, default=8000, help="Max incident rows to read.")
    ap.add_argument("--min-samples", type=int, default=40, help="Minimum labeled samples required.")
    ap.add_argument("--min-tenant-samples", type=int, default=25, help="Minimum samples for tenant calibration.")
    ap.add_argument(
        "--output",
        default=os.getenv("ML_DECISION_GATE_MODEL_PATH", "config/ml_decision_gate_model.json"),
        help="Artifact output path.",
    )
    ap.add_argument("--activate", action="store_true", help="Update active pointer with artifact + checksum.")
    ap.add_argument("--pointer-path", default="config/ml_decision_gate_active.json", help="Active pointer file path.")
    args = ap.parse_args()

    result = train_gate_from_db(
        tenant_id=args.tenant_id,
        limit=max(200, int(args.limit)),
        min_samples=max(10, int(args.min_samples)),
        min_tenant_samples=max(10, int(args.min_tenant_samples)),
    )
    if not bool(result.get("updated")):
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1

    artifact = result.get("artifact")
    if not isinstance(artifact, dict):
        print(json.dumps({"updated": False, "reason": "artifact_missing"}, ensure_ascii=False, indent=2))
        return 1

    path = save_gate_artifact(artifact, output_path=str(args.output))
    checksum = ""
    try:
        with open(path, "rb") as f:
            checksum = hashlib.sha256(f.read()).hexdigest()
    except Exception:
        checksum = ""
    if args.activate:
        previous = None
        try:
            if os.path.exists(args.pointer_path):
                with open(args.pointer_path, "r", encoding="utf-8") as f:
                    old = json.load(f)
                if isinstance(old, dict):
                    previous = old.get("active_path")
        except Exception:
            previous = None
        pointer = {
            "active_path": path,
            "active_checksum_sha256": checksum,
            "previous_path": previous,
        }
        with open(args.pointer_path, "w", encoding="utf-8") as f:
            json.dump(pointer, f, ensure_ascii=False, indent=2)
    summary = {
        "updated": True,
        "output_path": path,
        "checksum_sha256": checksum,
        "sample_size": result.get("sample_size"),
        "feature_count": result.get("feature_count"),
        "tenant_calibrations": len(
            (((artifact.get("domains") or {}).get("email_security") or {}).get("tenant_calibration") or {})
        ),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
