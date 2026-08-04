"""Import a tenant-authorized canonical location-ATP CSV into shadow allocation."""
from __future__ import annotations

import argparse
import json

from src.app.services.tenant_atp_import import import_tenant_location_atp_csv


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("path")
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--source", required=True)
    args = parser.parse_args()
    result = import_tenant_location_atp_csv(
        args.path, tenant_id=args.tenant, source=args.source,
    )
    print(json.dumps(result, indent=2, default=str))
    return 0 if result["status"] not in {"rejected", "insufficient"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
