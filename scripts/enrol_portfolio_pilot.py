from __future__ import annotations

import argparse
from pathlib import Path

from src.app.models.db import db_session
from src.app.services.portfolio_pilot_identity import (
    enrol_pilot_identities,
    load_pilot_identity_profile,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Enrol non-secret portfolio pilot identities into tenant membership storage."
    )
    parser.add_argument(
        "--profile",
        type=Path,
        default=Path("config/portfolio_pilot_identities.json"),
    )
    args = parser.parse_args()
    profile = load_pilot_identity_profile(args.profile)
    with db_session() as db:
        result = enrol_pilot_identities(db, profile)
    print(
        f"tenant={result['tenant_id']} enrolled={len(result['enrolled'])} "
        f"identity_source={result['identity_source']} supplier_mode={result['supplier_mode']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
