from __future__ import annotations

import logging
import os
import signal
import subprocess
import sys
import threading
from collections.abc import Sequence

from src.app.services.scheduler_lease import scheduler_lease_from_env

logger = logging.getLogger(__name__)


def _beat_command(extra_args: Sequence[str] = ()) -> list[str]:
    loglevel = os.getenv("CELERY_BEAT_LOGLEVEL", "INFO")
    return [
        sys.executable,
        "-m",
        "celery",
        "-A",
        "src.app.workers.celery_app:celery_app",
        "beat",
        f"--loglevel={loglevel}",
        *extra_args,
    ]


def main() -> int:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    lease = scheduler_lease_from_env()
    if not lease.acquire():
        logger.info("scheduler_lease_not_acquired key=%s", lease.key)
        return 0

    stopped = threading.Event()
    lease_lost = threading.Event()

    def renew() -> None:
        interval = max(1.0, lease.ttl_seconds / 3)
        while not stopped.wait(interval):
            try:
                if not lease.renew():
                    lease_lost.set()
                    return
            except Exception:
                logger.exception("scheduler_lease_renew_failed")
                lease_lost.set()
                return

    child = subprocess.Popen(_beat_command())

    def stop_child(_signum=None, _frame=None) -> None:
        stopped.set()
        if child.poll() is None:
            child.terminate()

    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, stop_child)
    renewer = threading.Thread(target=renew, name="scheduler-lease-renew", daemon=True)
    renewer.start()
    try:
        while child.poll() is None:
            if lease_lost.wait(1):
                logger.error("scheduler_lease_lost key=%s", lease.key)
                stop_child()
                break
        return_code = child.wait(timeout=30)
        return 1 if lease_lost.is_set() else int(return_code)
    finally:
        stopped.set()
        try:
            lease.release()
        except Exception:
            logger.exception("scheduler_lease_release_failed")


if __name__ == "__main__":
    raise SystemExit(main())
