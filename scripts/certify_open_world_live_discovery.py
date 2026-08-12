"""Create a sealed receipt artifact for live, free open-world discovery."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.app.services.case_research_plan import build_case_research_plan  # noqa: E402
from src.app.services.open_world_research_discovery import (  # noqa: E402
    discover_open_world_publishers,
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def certify(*, inputs: Path, output: Path, search_url: str) -> dict[str, Any]:
    source = json.loads(inputs.read_text(encoding="utf-8"))
    runs: list[dict[str, Any]] = []
    failures: list[str] = []
    for item in source["prompts"]:
        plan = build_case_research_plan(item["prompt"], allow_open_world=True)
        if plan is None or plan.publisher_status != "unresolved":
            failures.append(f"{item['id']}:open_world_plan_missing")
            continue
        result = discover_open_world_publishers(plan, search_url_template=search_url)
        receipts = list(result.get("receipts") or [])
        for receipt in receipts:
            if not receipt.get("query_hash"):
                failures.append(f"{item['id']}:query_hash_missing")
            if not receipt.get("external_call_dispatched"):
                failures.append(f"{item['id']}:network_dispatch_missing")
            if receipt.get("execution_status") != "completed":
                failures.append(f"{item['id']}:discovery_not_completed")
        accounting = dict(result.get("provider_accounting") or {})
        if int(accounting.get("paid_calls") or 0) != 0:
            failures.append(f"{item['id']}:paid_call_recorded")
        if int(accounting.get("discovery_calls") or 0) < 2:
            failures.append(f"{item['id']}:insufficient_query_axes_executed")
        runs.append({
            "prompt_id": item["id"],
            "plan_id": plan.plan_id,
            "query_axes": [row.axis for row in plan.discovery_queries],
            "query_hashes": [str(row.get("query_hash") or "") for row in receipts],
            "receipts": receipts,
            "candidate_origins": [
                {
                    "url": row["url"], "domain": row["domain"],
                    "title": row["title"], "quality_score": row.get("quality_score"),
                    "authority": "candidate_only_not_accepted",
                }
                for row in (result.get("candidates") or [])[:5]
            ],
            "outcome": (
                "candidate_origins_not_accepted"
                if result.get("candidates") else "no_credible_publisher_candidate"
            ),
            "provider_accounting": accounting,
        })
    artifact = {
        "schema_version": "open-world-live-discovery-certification-v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "input_sha256": _sha(inputs),
        "execution_mode": "live_network",
        "search_provider": "local_searxng",
        "billing_class": "free",
        "certification_status": "passed" if not failures else "failed",
        "gate_failures": failures,
        "runs": runs,
        "authority_rule": (
            "Discovery returns candidates only; case approval and fetched-origin verification "
            "are separate and search snippets establish no claim."
        ),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(artifact, indent=2), encoding="utf-8")
    output.with_suffix(output.suffix + ".sha256").write_text(
        _sha(output) + "\n", encoding="ascii",
    )
    return artifact


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--inputs", default="tests/golden/open_world_live_certification_inputs_v1.json",
    )
    parser.add_argument(
        "--output", default="docs/evidence/open_world_live_discovery_20260813.json",
    )
    parser.add_argument(
        "--search-url", default="http://127.0.0.1:8888/search?q={query}&format=json",
    )
    args = parser.parse_args()
    artifact = certify(
        inputs=Path(args.inputs), output=Path(args.output), search_url=args.search_url,
    )
    print(json.dumps({
        "status": artifact["certification_status"],
        "runs": len(artifact["runs"]),
        "failures": artifact["gate_failures"],
    }, indent=2))
    return 0 if artifact["certification_status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
