"""Run and seal the held-out live-router intake certificate."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.app.models.db import db_session  # noqa: E402
from src.app.services.live_router_intake_certificate import (  # noqa: E402
    run_live_router_intake_certificate,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output", default="tmp/live_router_intake_certificate.json",
    )
    parser.add_argument("--timeout", type=float, default=60.0)
    args = parser.parse_args()
    output = Path(args.output)
    with db_session() as db:
        artifact = run_live_router_intake_certificate(db, timeout_s=args.timeout)
    output.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(artifact, indent=2, sort_keys=True) + "\n"
    output.write_text(rendered, encoding="utf-8")
    output.with_suffix(output.suffix + ".sha256").write_text(
        hashlib.sha256(output.read_bytes()).hexdigest() + "\n",
        encoding="ascii",
    )
    print(json.dumps({
        "status": artifact["certification_status"],
        "failures": artifact["gate_failures"],
        "output": str(output),
        "seal_sha256": artifact["seal_sha256"],
    }, indent=2))
    return 0 if artifact["certification_status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
