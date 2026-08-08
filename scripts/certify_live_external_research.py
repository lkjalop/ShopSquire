"""Certify real discovery -> official-origin retrieval without accepting snippets.

Run a local SearXNG first:
  docker compose -f docker-compose.searxng.yml up -d
  python scripts/certify_live_external_research.py

The JSON artifact contains hashes and receipts, never downloaded page content.
"""
from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.app.adapters.external_research_httpx import HttpxResearchFetcher  # noqa: E402
from src.app.adapters.official_origin_httpx import GovernedOfficialOriginFetcher  # noqa: E402
from src.app.services.recommendation_core.research_contracts import (  # noqa: E402
    ProviderExecutionReceipt,
)


OFFICIAL_DOMAINS = [
    "csrc.nist.gov", "nvlpubs.nist.gov", "attack.mitre.org",
    "learn.microsoft.com", "docs.factoryio.com",
    "docs.isaacsim.omniverse.nvidia.com", "docs.omniverse.nvidia.com",
]


def _canonical_receipt(
    raw: dict[str, object], *, run_id: str, execution_id: str,
    receipt_id: str, capability: str, selected_urls: list[str] | None = None,
    content_type: str | None = None,
) -> ProviderExecutionReceipt:
    return ProviderExecutionReceipt(
        receipt_id=receipt_id,
        execution_id=execution_id,
        provider_capability=capability,
        provider_id=str(raw.get("provider_id") or "unknown"),
        certification_run_id=run_id,
        provider_endpoint_host=raw.get("provider_endpoint_host"),
        query_hash=raw.get("query_hash"),
        obligation_ids=["ambiguous-workload-research"],
        execution_status=raw.get("execution_status", "failed"),
        fixture=False,
        network_execution=bool(raw.get("network_execution")),
        external_call_dispatched=bool(raw.get("external_call_dispatched")),
        cache_status=raw.get("cache_status", "miss"),
        billing_class=raw.get("billing_class", "unknown"),
        started_at=raw.get("started_at"),
        completed_at=raw.get("completed_at"),
        http_status=raw.get("http_status"),
        result_count=raw.get("result_count"),
        allowlisted_result_count=raw.get("allowlisted_result_count"),
        response_body_hash=raw.get("response_body_hash"),
        selected_origin_urls=selected_urls or [],
        origin_content_type=content_type,
        origin_observed_at=raw.get("observed_at"),
        rejection_reason=raw.get("error"),
    )


def certify(search_url: str, query: str, output: Path) -> dict[str, object]:
    run_id = f"live-{uuid.uuid4().hex[:12]}"
    discovery = HttpxResearchFetcher(
        search_url_template=search_url, allow_private=True,
    )
    results = discovery.fetch(query, allowlist=OFFICIAL_DOMAINS, timeout_s=12)
    discovery.last_receipt.update({
        "result_count": len(results), "allowlisted_result_count": len(results),
    })
    if not results:
        raise RuntimeError("live discovery returned no allowlisted official origin")

    selected_url = str(results[0]["url"])
    origin = GovernedOfficialOriginFetcher(max_bytes=8 * 1024 * 1024).fetch(
        selected_url, allowlist=OFFICIAL_DOMAINS, timeout_s=12,
        certification_run_id=run_id,
    )
    if origin["status"] != "completed":
        raise RuntimeError(f"official origin fetch failed: {origin.get('error')}")

    discovery_receipt = _canonical_receipt(
        discovery.last_receipt, run_id=run_id,
        execution_id=f"{run_id}:discovery", receipt_id=f"{run_id}:d",
        capability="WEB_DISCOVERY", selected_urls=[selected_url],
    )
    origin_receipt = _canonical_receipt(
        origin["receipt"], run_id=run_id,
        execution_id=f"{run_id}:origin", receipt_id=f"{run_id}:o",
        capability="OFFICIAL_ORIGIN_FETCH", selected_urls=[selected_url],
        content_type=str(origin["content_type"]),
    )
    artifact = {
        "certification_run_id": run_id,
        "execution_mode": "live_network",
        "query": query,
        "selected_origin_domain": urlparse(selected_url).hostname,
        "selected_origin_url": selected_url,
        "discovery_receipt": discovery_receipt.model_dump(mode="json"),
        "official_origin_receipt": origin_receipt.model_dump(mode="json"),
        "external_calls": 2,
        "paid_calls": 0,
        "authority_rule": "discovery finds; accepted claims require official-origin compilation",
        "claims_accepted": 0,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(artifact, indent=2), encoding="utf-8")
    return artifact


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--search-url",
        default="http://127.0.0.1:8888/search?q={query}&format=json",
    )
    parser.add_argument(
        "--query",
        default="site:docs.factoryio.com Factory I/O system requirements",
    )
    parser.add_argument(
        "--output", default="tmp/live_external_research_certification.json",
    )
    args = parser.parse_args()
    artifact = certify(args.search_url, args.query, Path(args.output))
    print(json.dumps(artifact, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
