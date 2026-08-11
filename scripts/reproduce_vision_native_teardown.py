"""Repeat one vision contract in fresh processes and report native teardown health.

This is a diagnostic/certification tool, not a product benchmark. Fresh process
isolation makes a native CV/OCR crash attributable and prevents one failed run
from corrupting the remaining sample.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time


NODE = (
    "tests/services/test_vision_runtime_budget.py::"
    "test_provider_capacity_is_pending_not_security_risk"
)


def _child() -> int:
    import pytest

    before = sorted(thread.name for thread in threading.enumerate())
    started = time.perf_counter()
    code = int(pytest.main([NODE, "-q", "--disable-warnings"]))
    after = sorted(thread.name for thread in threading.enumerate())
    print(json.dumps({
        "event": "vision_native_child",
        "provider": os.getenv("CV_OCR_PROVIDER", "unset"),
        "pytest_exit": code,
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
        "threads_before": before,
        "threads_after": after,
    }, sort_keys=True))
    return code


def _parent(repeats: int) -> int:
    records = []
    for provider in ("none", "tesseract"):
        for iteration in range(repeats):
            env = dict(os.environ)
            env.update({
                "PYTHONFAULTHANDLER": "1",
                "CV_OCR_PROVIDER": provider,
                "CV_DUAL_OCR_ENABLED": "0",
            })
            proc = subprocess.run(
                [sys.executable, "-X", "faulthandler", __file__, "--child"],
                cwd=os.getcwd(), env=env, capture_output=True, text=True, timeout=120,
            )
            record = {
                "provider": provider,
                "iteration": iteration + 1,
                "returncode": proc.returncode,
                "native_crash": proc.returncode < 0 or proc.returncode in {0xC0000005, -1073741819},
                "stdout_tail": proc.stdout[-2000:],
                "stderr_tail": proc.stderr[-4000:],
            }
            records.append(record)
            print(json.dumps(record, sort_keys=True))
    summary = {
        "runs": len(records),
        "passed": sum(row["returncode"] == 0 for row in records),
        "native_crashes": sum(bool(row["native_crash"]) for row in records),
        "failed": sum(row["returncode"] != 0 for row in records),
    }
    print(json.dumps({"summary": summary}, sort_keys=True))
    return 0 if summary["failed"] == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--child", action="store_true")
    parser.add_argument("--repeats", type=int, default=5)
    args = parser.parse_args()
    return _child() if args.child else _parent(max(1, min(args.repeats, 50)))


if __name__ == "__main__":
    raise SystemExit(main())
