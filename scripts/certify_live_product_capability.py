"""Certify and optionally persist one live exact-SKU OEM observation."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

from sqlalchemy import select

REPO_ROOT = str(Path(__file__).resolve().parents[1])
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from src.app.models.db import db_session  # noqa: E402
from src.app.models.orm import ProductConfiguration  # noqa: E402
from src.app.services.connectors.product_capability_evidence import (  # noqa: E402
    AsusOfficialHtmlProductProvider,
    ProductCapabilityEvidenceRegistry,
    ProductIdentity,
    ProductSourcePolicy,
)
from src.app.services.product_capability_refresh import (  # noqa: E402
    refresh_exact_configuration_capabilities,
)


DEFAULT_URL = "https://rog.asus.com/au/laptops/rog-zephyrus/rog-zephyrus-duo-2026/spec/"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sku", default="SCORP-125638")
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--persist", action="store_true")
    parser.add_argument("--output", default="tmp/live_product_capability_certification.json")
    args = parser.parse_args()
    with db_session() as db:
        configuration = db.execute(select(ProductConfiguration).where(
            ProductConfiguration.tenant_id == "default",
            ProductConfiguration.sku == args.sku,
            ProductConfiguration.active.is_(True),
        )).scalar_one_or_none()
        if configuration is None:
            print(json.dumps({"passed": False, "error": "exact_configuration_not_found"}))
            return 2
        provider = AsusOfficialHtmlProductProvider(
            "asus_official_specs", endpoint=args.url,
        )
        registry = ProductCapabilityEvidenceRegistry(
            providers=(provider,),
            policies=(ProductSourcePolicy(
                "asus_official_specs", ("ASUS", "Republic of Gamers"),
                ("asus.com", "rog.asus.com"),
                allowed_identity_types=("manufacturer_part_number",),
            ),),
            allowed_tenants=("default",),
        )
        if args.persist:
            report = refresh_exact_configuration_capabilities(
                db, configuration, registry=registry, allow_live=True,
            )
        else:
            result = registry.resolve(
                identity=ProductIdentity(
                    configuration.sku, "manufacturer_part_number", str(configuration.mpn or ""),
                    configuration.configuration_hash, "laptop",
                ),
                claim_keys=(
                    "operating_system", "cpu_model", "gpu_class", "gpu_vram_gb",
                    "ram_gb", "ram_ceiling_gb", "ram_upgradeable", "storage_gb",
                ),
                allow_live=True,
                tenant_id="default",
            )
            report = result.to_dict()
    claims = list(report.get("observed_values") or report.get("accepted_claims") or [])
    passed = report.get("status") == "accepted" and len(claims) >= 6
    artifact = {
        "schema_version": "live-product-capability-cert-v1",
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "fixture": False,
        "network_execution": True,
        "paid_calls": 0,
        "source_url": args.url,
        "persisted": bool(args.persist),
        "report": report,
        "passed": passed,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(artifact, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"passed": passed, "claims": len(claims), "persisted": bool(args.persist), "output": str(output)}, indent=2))
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
