from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
from typing import Any, Dict, List

import requests


def _iter_images(folder: pathlib.Path) -> List[pathlib.Path]:
    exts = {".png", ".jpg", ".jpeg", ".webp"}
    out: List[pathlib.Path] = []
    for p in sorted(folder.glob("*")):
        if p.is_file() and p.suffix.lower() in exts:
            out.append(p)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Batch-run ShopSquire CV upload pipeline and emit a short report.")
    ap.add_argument("--folder", default="dump/test-cv", help="Folder containing test images")
    ap.add_argument("--api", default=os.getenv("API_BASE_URL", "http://127.0.0.1:8080").rstrip("/"), help="API base URL")
    ap.add_argument("--api-key", default=os.getenv("MERCHANT_API_KEY", "local-merchant-key"), help="x-api-key for API")
    ap.add_argument("--order-id", default="jk-01234987-syd", help="Order id context (optional)")
    ap.add_argument("--issue-type", default="return", help="Issue type context (optional)")
    ap.add_argument("--description", default="CV triage demo", help="Description context (optional)")
    ap.add_argument("--expected-label", default="laptop", help="Expected label context (optional)")
    ap.add_argument("--sku", default=None, help="SKU context (optional)")
    ap.add_argument("--out", default=None, help="Write JSON report to this path")
    args = ap.parse_args()

    folder = pathlib.Path(args.folder)
    if not folder.exists() or not folder.is_dir():
        print(f"folder not found: {folder}", file=sys.stderr)
        return 2

    files = _iter_images(folder)
    if not files:
        print(f"no images found in: {folder}", file=sys.stderr)
        return 2

    s = requests.Session()
    s.headers.update({"x-api-key": args.api_key})

    results: List[Dict[str, Any]] = []
    for p in files:
        nonce = ""
        try:
            nonce = (s.get(f"{args.api}/api/v1/cv/nonce", timeout=5).json() or {}).get("nonce") or ""
        except Exception:
            nonce = ""

        params = {
            "nonce": nonce or None,
            "order_id": args.order_id or None,
            "issue_type": args.issue_type or None,
            "description": args.description or None,
            "expected_label": args.expected_label or None,
            "sku": args.sku or None,
        }
        # Drop Nones for cleaner URLs.
        params = {k: v for k, v in params.items() if v}

        with p.open("rb") as f:
            up = s.post(
                f"{args.api}/api/v1/cv/upload",
                params=params,
                files={"image": (p.name, f, "application/octet-stream")},
                timeout=30,
            )
        try:
            upj = up.json()
        except Exception:
            upj = {"status": "error", "http": up.status_code, "text": up.text[:2000]}

        case_id = upj.get("case_id") or (upj.get("cv_tier2") or {}).get("case_id")
        t2 = upj.get("cv_tier2") or {}
        verdict = (t2.get("verdict") or {}).get("verdict")
        actions = (t2.get("verdict") or {}).get("required_actions") or []
        tags = t2.get("evidence_tags") or []

        trace = None
        if case_id:
            try:
                trace = s.get(f"{args.api}/api/v1/decisions/{case_id}", timeout=10).json()
            except Exception:
                trace = None

        results.append(
            {
                "file": str(p),
                "case_id": case_id,
                "verdict": verdict,
                "required_actions": actions,
                "evidence_tags": tags,
                "robustness": (t2.get("robustness") or {}),
                "security": (t2.get("security_analysis") or {}),
                "decision_trace_available": bool(trace and isinstance(trace, dict) and trace.get("decision_id")),
                "decision_trace": trace,
            }
        )

    report = {
        "api": args.api,
        "folder": str(folder),
        "count": len(results),
        "items": results,
    }

    out_path = args.out
    if not out_path:
        out_dir = pathlib.Path("dump") / "reports"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = str(out_dir / "cv_folder_report.json")
    pathlib.Path(out_path).write_text(json.dumps(report, indent=2), encoding="utf-8")

    # Print concise summary for terminals.
    for r in results:
        print(f"{pathlib.Path(r['file']).name}: case_id={r.get('case_id')} verdict={r.get('verdict')} tags={len(r.get('evidence_tags') or [])} actions={r.get('required_actions')}")
    print(f"wrote: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

