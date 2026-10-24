"""Exit nonzero unless a tenant has fresh measurements and an approved baseline.

Run with DATABASE_URL pointing at a migrated evaluation database. This command
does not approve a baseline, synthesize scores, or invoke a paid evaluator.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> int:
    from src.app.platform.tenant_context import set_active_tenant_id, reset_active_tenant_id
    from src.app.services.ragas_eval import ci_guard_check
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tenant', required=True)
    parser.add_argument('--window', type=int, default=200)
    args = parser.parse_args()
    if not args.tenant.strip():
        parser.error('--tenant must be nonempty')
    token = set_active_tenant_id(args.tenant)
    try:
        try:
            result = ci_guard_check(window=args.window)
        except Exception as exc:
            result = {'ok': False, 'reason': 'gate_execution_failed', 'error_type': type(exc).__name__}
        print(json.dumps(result, sort_keys=True))
        return 0 if result.get('ok') is True else 1
    finally:
        reset_active_tenant_id(token)


if __name__ == '__main__':
    raise SystemExit(main())
