from __future__ import annotations

import os
import json
import argparse
import uuid
import sys
import requests


def main() -> int:
    parser = argparse.ArgumentParser(description="Upload a compliance artifact to the ShopSquire admin registry endpoint")
    parser.add_argument("--type", dest="artifact_type", required=True, help="Artifact type, e.g., container_scan, dependency_scan, sbom")
    parser.add_argument("--vendor", dest="vendor", required=True, help="Vendor name, e.g., trivy, snyk, syft")
    parser.add_argument("--file", dest="file_path", required=True, help="Path to JSON artifact to upload")
    parser.add_argument("--scan-id", dest="scan_id", default=None, help="External scan id or reference (optional)")
    args = parser.parse_args()

    api_base = os.getenv("API_BASE_URL", "")
    api_key = os.getenv("ADMIN_API_KEY", "")
    if not api_base or not api_key:
        print("API_BASE_URL or ADMIN_API_KEY not set; skipping upload", file=sys.stderr)
        return 0

    try:
        with open(args.file_path, "r", encoding="utf-8") as f:
            payload_raw = json.load(f)
    except Exception as e:
        print(f"Failed to read artifact file: {e}", file=sys.stderr)
        return 1

    body = {
        "artifact_type": args.artifact_type,
        "vendor": args.vendor,
        "scan_id": args.scan_id,
        "status": None,
        "details": payload_raw,
    }

    url = api_base.rstrip('/') + "/api/v1/admin/compliance/artifacts"
    headers = {
        "Content-Type": "application/json",
        "x-api-key": api_key,
    }
    try:
        resp = requests.post(url, data=json.dumps(body), headers=headers, timeout=30)
        if resp.status_code >= 200 and resp.status_code < 300:
            print(f"Uploaded compliance artifact: {resp.text}")
            return 0
        else:
            print(f"Upload failed: {resp.status_code} {resp.text}", file=sys.stderr)
            return 2
    except Exception as e:
        print(f"Upload error: {e}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
