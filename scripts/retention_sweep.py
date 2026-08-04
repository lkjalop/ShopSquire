#!/usr/bin/env python
"""Run the uniform data-retention sweep from the CLI (or cron).

    python -m scripts.retention_sweep            # DRY RUN — report only, mutates nothing
    python -m scripts.retention_sweep --apply    # actually soft-expire / hard-purge / set TTLs

Storage-limitation half of compliance (idle carts, stale conversation, TTL-less Redis session keys).
UNIFORM across every user — NOT IP/geo gated. On-request erasure is a separate path (DELETE /data/{uid}).
Windows are read from config/retention_policy.json.
"""
from __future__ import annotations

import argparse
import json
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description="Uniform data-retention sweep")
    parser.add_argument("--apply", action="store_true",
                        help="actually mutate (default is a dry run that only reports counts)")
    args = parser.parse_args()

    from src.app.services.retention_sweeper import sweep_now
    report = sweep_now(dry_run=not args.apply)

    print(json.dumps(report, indent=2))
    if report.get("dry_run"):
        print("\n(dry run — nothing changed. Re-run with --apply to act.)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
