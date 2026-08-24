"""Run storefront Playwright specs in fresh processes and retain every artifact.

Long Windows runs can eventually fail to initialize a new Chromium worker with
0xC0000142 even when Playwright uses one worker.  A fresh CLI process per spec
releases the Node/Chromium process tree between files while the production-
shaped backend, PostgreSQL, Redis, and Celery stack stays live.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import subprocess
import sys


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--frontend", type=Path, required=True)
    parser.add_argument("--spec", action="append", default=[])
    args = parser.parse_args()

    frontend = args.frontend.resolve()
    if args.spec:
        specs = [Path(value) for value in args.spec]
    else:
        specs = sorted((frontend / "e2e").glob("*.spec.ts"))
    if not specs:
        print("no Playwright specs found", file=sys.stderr)
        return 2

    npx = shutil.which("npx.cmd" if sys.platform == "win32" else "npx")
    if not npx:
        print("npx executable not found", file=sys.stderr)
        return 2

    failed: list[str] = []
    for index, value in enumerate(specs, start=1):
        spec = value if value.is_absolute() else frontend / value
        try:
            relative = spec.resolve().relative_to(frontend).as_posix()
        except ValueError:
            relative = str(spec.resolve())
        output = f"test-results/release-shards/{index:03d}-{spec.stem}"
        print(f"\n=== PLAYWRIGHT SHARD {index}/{len(specs)}: {relative} ===", flush=True)
        result = subprocess.run(
            [
                npx,
                "playwright",
                "test",
                "--reporter=line",
                "--workers=1",
                f"--output={output}",
                relative,
            ],
            cwd=frontend,
            check=False,
        )
        if result.returncode != 0:
            failed.append(relative)
            print(f"=== PLAYWRIGHT SHARD FAILED ({result.returncode}): {relative} ===", flush=True)
        else:
            print(f"=== PLAYWRIGHT SHARD PASSED: {relative} ===", flush=True)

    print(f"\nPLAYWRIGHT_SHARDS={len(specs)}", flush=True)
    print(f"PLAYWRIGHT_FAILED={len(failed)}", flush=True)
    for spec in failed:
        print(f"  - {spec}", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
