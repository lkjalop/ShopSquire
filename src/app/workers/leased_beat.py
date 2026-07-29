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


def _terminate_child(
    child: subprocess.Popen,
    *,
    grace_seconds: float,
) -> bool:
    if child.poll() is not None:
        return True
    child.terminate()
    try:
        child.wait(timeout=max(0.1, grace_seconds))
    except subprocess.TimeoutExpired:
        logger.error("scheduler_child_terminate_timeout; escalating_to_kill")
        child.kill()
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            logger.critical("scheduler_child_survived_kill")
            return False
    return child.poll() is not None


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

    child: subprocess.Popen | None = None
    child_stopped = True

    def stop_child(_signum=None, _frame=None) -> None:
        nonlocal child_stopped
        stopped.set()
        if child is not None:
            grace = float(os.getenv("SCHEDULER_CHILD_GRACE_SEC", "10") or 10)
            child_stopped = _terminate_child(child, grace_seconds=grace)

    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, stop_child)
    renewer = threading.Thread(target=renew, name="scheduler-lease-renew", daemon=True)
    try:
        child = subprocess.Popen(_beat_command())
        child_stopped = False
        renewer.start()
        while child.poll() is None:
            if lease_lost.wait(1):
                logger.error("scheduler_lease_lost key=%s", lease.key)
                stop_child()
                break
        if child.poll() is None:
            stop_child()
        return_code = child.wait(timeout=5)
        child_stopped = True
        return 1 if lease_lost.is_set() else int(return_code)
    finally:
        stopped.set()
        if renewer.is_alive():
            renewer.join(timeout=2)
        if child is not None and child.poll() is None:
            stop_child()
        if child_stopped:
            try:
                lease.release()
            except Exception:
                logger.exception("scheduler_lease_release_failed")
        else:
            # Do not release while a scheduler child might still be running.
            # Renewal has stopped, so Redis expiry provides the safe handover.
            logger.critical("scheduler_lease_left_to_expire child_still_running")


if __name__ == "__main__":
    raise SystemExit(main())
