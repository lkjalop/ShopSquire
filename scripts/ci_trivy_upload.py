#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
import json
import requests


def main():
    if len(sys.argv) < 3:
        print("Usage: ci_trivy_upload.py <trivy_json_path> <api_base>")
        sys.exit(2)
    path = sys.argv[1]
    api_base = sys.argv[2].rstrip('/')
    try:
        data = json.loads(open(path, 'r', encoding='utf-8').read())
    except Exception as e:
        print(f"Failed to read Trivy JSON: {e}")
        sys.exit(1)
    payload = {
        "artifact_type": "container_scan",
        "vendor": "trivy",
        "scan_id": data.get("ArtifactID") or data.get("ArtifactName"),
        "status": None,
        "details": data,
    }
    url = f"{api_base}/api/v1/admin/compliance/artifacts"
    try:
        r = requests.post(url, data=json.dumps(payload).encode('utf-8'), headers={"Content-Type": "application/json"}, timeout=5)
        if r.status_code // 100 != 2:
            print(f"Upload failed: {r.status_code} {r.text}")
            sys.exit(1)
        print(r.text)
    except Exception as e:
        print(f"Upload error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
