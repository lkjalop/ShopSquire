#!/usr/bin/env python3
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.app.services.mtls_cert_monitor import check_mtls_cert_expiry


def _rotate_needed(report: dict, rotate_before_days: int) -> bool:
    for c in report.get("certs") or []:
        days = c.get("expires_in_days")
        if days is None:
            continue
        if float(days) <= float(rotate_before_days):
            return True
    return False


def _run_rotation(out_dir: str) -> int:
    # Prefer existing shell generator when bash is available.
    script = ROOT / "scripts" / "generate_mtls_certs.sh"
    bash = shutil.which("bash")
    if bash and script.exists():
        cmd = [bash, str(script), out_dir]
        p = subprocess.run(cmd, cwd=str(ROOT))
        return int(p.returncode)

    print("rotation_failed:no_bash_or_generator", file=sys.stderr)
    print("hint: install bash/openssl and run scripts/generate_mtls_certs.sh", file=sys.stderr)
    return 2


def main() -> int:
    rotate_before = int(os.getenv("MTLS_CERT_ROTATE_BEFORE_DAYS", "14") or 14)
    cert_dir = str(os.getenv("MTLS_CERT_DIR", "config/tls/certs") or "config/tls/certs")
    force = str(os.getenv("MTLS_CERT_ROTATE_FORCE", "0")).lower() in ("1", "true", "yes")

    report = check_mtls_cert_expiry()
    if not report.get("ok"):
        print(report)
        return 1

    if not force and not _rotate_needed(report, rotate_before):
        print({"status": "ok", "action": "skip", "reason": "not_due", "rotate_before_days": rotate_before})
        return 0

    rc = _run_rotation(cert_dir)
    if rc != 0:
        return rc

    post = check_mtls_cert_expiry()
    print({"status": "ok", "action": "rotated", "before": report, "after": post})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
