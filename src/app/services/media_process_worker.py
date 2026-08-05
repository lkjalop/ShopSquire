from __future__ import annotations

import importlib
import json
import os
import sys
from typing import Any


def _apply_posix_limits() -> None:
    if os.name == "nt":
        return
    try:
        import resource

        memory_mb = max(64, int(os.getenv("MEDIA_ISOLATE_MEMORY_MB", "512")))
        cpu_seconds = max(1, int(os.getenv("MEDIA_ISOLATE_CPU_SECONDS", "10")))
        memory_bytes = memory_mb * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds + 1))
    except (ImportError, OSError, ValueError):
        # The parent still enforces a hard wall-clock timeout. Unsupported host
        # limits are observable through deployment readiness rather than making
        # every local Windows analysis fail.
        return


def _execute(payload: dict[str, Any]) -> dict[str, Any]:
    _apply_posix_limits()
    try:
        function = getattr(
            importlib.import_module(str(payload["module_name"])),
            str(payload["function_name"]),
        )
        value = function(**dict(payload.get("kwargs") or {}))
        return {"status": "completed", "value": value}
    except BaseException as exc:  # serialize failures across the trust boundary
        return {
            "status": "failed",
            "error": f"{type(exc).__name__}: {str(exc)[:500]}",
        }


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read())
        result = _execute(payload)
    except BaseException as exc:
        result = {
            "status": "failed",
            "error": f"worker_protocol_error:{type(exc).__name__}:{str(exc)[:300]}",
        }
    sys.stdout.write(json.dumps(result, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
