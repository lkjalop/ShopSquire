from __future__ import annotations

import os
import time
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.app.security.vendor_connectors import pull_crowdstrike_and_ingest


def _bool_env(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return str(v).strip().lower() in ("1", "true", "yes", "on")


def main() -> int:
    if not _bool_env("SECURITY_CROWDSTRIKE_POLL_ENABLED", True):
        print({"status": "disabled"})
        return 0
    interval_sec = max(30, min(3600, int(float(os.getenv("SECURITY_CROWDSTRIKE_POLL_INTERVAL_SEC", "300") or 300))))
    tenant_id = str(os.getenv("SECURITY_CROWDSTRIKE_POLL_TENANT_ID", "default") or "default")
    limit = max(1, min(500, int(float(os.getenv("SECURITY_CROWDSTRIKE_POLL_LIMIT", "100") or 100))))
    lookback_minutes = max(1, min(24 * 60, int(float(os.getenv("SECURITY_CROWDSTRIKE_POLL_LOOKBACK_MINUTES", "30") or 30))))
    startup_delay = max(0, min(300, int(float(os.getenv("SECURITY_CROWDSTRIKE_POLL_STARTUP_DELAY_SEC", "10") or 10))))
    if startup_delay:
        time.sleep(startup_delay)

    while True:
        try:
            out = pull_crowdstrike_and_ingest(
                tenant_id=tenant_id,
                limit=limit,
                lookback_minutes=lookback_minutes,
            )
            print({"worker": "crowdstrike_poll", **out})
        except Exception as exc:
            print({"worker": "crowdstrike_poll", "ok": False, "error": str(exc)})
        time.sleep(interval_sec)


if __name__ == "__main__":
    raise SystemExit(main())
