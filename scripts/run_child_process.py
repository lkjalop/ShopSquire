"""Run a child command and persist its exit code for the parent process.

PowerShell Start-Process can lose ExitCode when the target is a .cmd shim.
The production-shaped browser harness therefore uses a child-written status
artifact instead of relying on the PowerShell process wrapper.
"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


def _write_exit_code(exit_code: int) -> None:
    target = os.getenv("SHOPSQUIRE_CHILD_EXIT_FILE", "").strip()
    if not target:
        return
    path = Path(target)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(f"{exit_code}\n", encoding="utf-8")
    temporary.replace(path)


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: run_child_process.py COMMAND [ARG ...]", file=sys.stderr)
        return 2
    try:
        exit_code = int(subprocess.run(sys.argv[1:], check=False).returncode)
    except BaseException:
        _write_exit_code(1)
        raise
    _write_exit_code(exit_code)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
