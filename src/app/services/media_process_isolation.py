from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class IsolatedMediaResult:
    status: str
    value: Any = None
    error: str | None = None
    elapsed_ms: int = 0


def _terminate_process_tree(process: subprocess.Popen[str]) -> None:
    """Terminate only the disposable parser process and its descendants."""
    if process.poll() is not None:
        return
    if os.name == "nt":
        # OCR tools can create their own children. taskkill is deliberately scoped
        # to the exact spawned PID and never operates on a name or wildcard.
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    try:
        process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=1)


def run_isolated_media_call(
    *, module_name: str, function_name: str, kwargs: dict[str, Any], timeout_s: float,
) -> IsolatedMediaResult:
    """Execute a top-level callable in a disposable interpreter process.

    An interpreter subprocess is used instead of ``multiprocessing`` because
    Celery prefork children are daemonic and cannot reliably create further
    multiprocessing children. The subprocess remains independently killable.
    """
    started = time.perf_counter()
    request = json.dumps(
        {
            "module_name": str(module_name),
            "function_name": str(function_name),
            "kwargs": dict(kwargs),
        },
        separators=(",", ":"),
    )
    creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if os.name == "nt" else 0
    process = subprocess.Popen(
        [sys.executable, "-m", "src.app.services.media_process_worker"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        start_new_session=os.name != "nt",
        creationflags=creationflags,
        env=os.environ.copy(),
    )
    try:
        stdout, stderr = process.communicate(request, timeout=max(0.01, float(timeout_s)))
    except subprocess.TimeoutExpired:
        _terminate_process_tree(process)
        return IsolatedMediaResult(
            status="timed_out",
            error="isolated_media_timeout",
            elapsed_ms=int((time.perf_counter() - started) * 1000),
        )

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    if process.returncode != 0 and not stdout.strip():
        return IsolatedMediaResult(
            status="worker_lost",
            error=f"isolated_media_worker_exit:{process.returncode}:{stderr[-500:]}",
            elapsed_ms=elapsed_ms,
        )
    try:
        payload = json.loads(stdout)
    except (TypeError, ValueError):
        return IsolatedMediaResult(
            status="worker_lost",
            error=f"isolated_media_invalid_response:{stderr[-500:]}",
            elapsed_ms=elapsed_ms,
        )
    return IsolatedMediaResult(
        status=str(payload.get("status") or "failed"),
        value=payload.get("value"),
        error=payload.get("error"),
        elapsed_ms=elapsed_ms,
    )
