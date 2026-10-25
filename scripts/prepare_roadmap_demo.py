"""Prepare a NEW disposable fictional shop, fresh evidence and a restore point.

No reset mutates an existing database. Use a new directory for every replay.
Secrets are generated for this local fixture, never embedded in the frontend.
"""

import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import secrets
import sqlite3
import subprocess
import sys
from scripts.roadmap_runtime import simulation_controls, local_backend_isolation

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument(
        "--fixture-clock",
        help="Timezone-aware ISO instant for reproducible market fixtures; defaults to now",
    )
    args = parser.parse_args()
    try:
        fixture_clock = (
            datetime.fromisoformat(args.fixture_clock.replace("Z", "+00:00"))
            if args.fixture_clock
            else None
        )
        if fixture_clock and fixture_clock.tzinfo is None:
            raise ValueError("Timezone required")
    except ValueError:
        parser.error("fixture-clock must be a timezone-aware ISO instant")
    directory = args.directory.resolve()
    if not directory.is_relative_to(ROOT / ".artifacts"):
        parser.error("Use a new directory inside .artifacts")
    directory.mkdir(parents=True, exist_ok=False)
    database = directory / "shop.sqlite3"
    flags = directory / "feature_flags.json"
    flags.write_bytes((ROOT / "config/feature_flags.json").read_bytes())
    configuration = {
        "APP_ENV": "local",
        "DATABASE_URL": "sqlite:///" + database.as_posix(),
        "DATABASE_URL_RO": "sqlite:///" + database.as_posix(),
        "ENABLE_DEMO_ROUTES": "1",
        "FEATURE_FLAGS_PATH": str(flags),
        "RECOMMEND_CORE_MODE": "primary",
        "SEMANTIC_RESEARCH_FIXTURES_ENABLED": "1",
        "SEMANTIC_SIMULATION_AUTHORITY_ENABLED": "1",
        "SEMANTIC_RESEARCH_FIXTURE_ID": "fictional-memory-runtime-v1",
        "SEMANTIC_RESEARCH_FIXTURE_PATH": str(directory / "research.json"),
        "VITE_STOREFRONT_TENANT_ID": "synthetic-electronics",
        "VITE_ENABLE_SIMULATED_STOCK": "1",
        "PORTFOLIO_CERTIFICATION_ENABLED": "1",
        "RECOMMEND_PROCUREMENT_ADVICE_MODE": "on",
        "CV_PROVIDER": "basic",
        "CV_VISION_ENABLED": "0",
        "FULFILLMENT_SUPPLIER_TRANSPORT": "sandbox",
        "EXTERNAL_RESEARCH_ENABLED": "0",
        "BUYER_IDENTITY_MODE": "strict",
        "OPERATOR_TENANT_MEMBERSHIP_MODE": "strict",
        "BUYER_TENANT_BINDINGS_JSON": json.dumps(
            {
                "roadmap-browser-buyer": ["synthetic-electronics"],
                "roadmap-bundle-buyer": ["synthetic-bundles"],
                "roadmap-upgrade-buyer": ["synthetic-bundles"],
            }
        ),
        "JWT_SIGNING_KEY": secrets.token_urlsafe(48),
        "OWNER_API_KEY": secrets.token_urlsafe(32),
        "MERCHANT_API_KEY": secrets.token_urlsafe(32),
        "DEVELOPER_API_KEY": secrets.token_urlsafe(32),
        "OTEL_SDK_DISABLED": "true",
        "ROUTER_PREWARM_ON_START": "0",
        "VLM_WARMUP_ON_START": "0",
        "CV_WARMUP_ON_START": "0",
        "INVENTORY_WORKER_ENABLED": "0",
        "INVENTORY_EXPIRY_SCHEDULER_ENABLED": "0",
        "PAYMENT_RECONCILE_SCHEDULER_ENABLED": "0",
        "WEBHOOK_DISPATCHER_WORKER_ENABLED": "0",
        "RETENTION_CLEANUP_ENABLED": "0",
        "INCIDENT_SLA_SCHEDULER_ENABLED": "0",
        "CHAT_REQUEST_TIMEOUT_SEC": "30",
        "CHAT_UPSTREAM_TIMEOUT_SEC": "25",
        "AUTOMATIC_RESEARCH_TIMEOUT_SEC": "20",
        "ROUTER_MODEL_ENABLED": "0",
        "OLLAMA_URL": "http://127.0.0.1:1",
    }
    configuration.update(simulation_controls())
    configuration.update(local_backend_isolation())
    env = {**os.environ, **configuration}
    (directory / "runtime-private.json").write_text(
        json.dumps(configuration, indent=2), encoding="utf-8"
    )
    commands = [
        ["scripts.seed_electronics_shop", "--database", str(database)],
        ["scripts.bootstrap_sold_taxonomy"],
        ["scripts.seed_operator_inventory_demo", "--tenant", "synthetic-electronics"],
        ["scripts.seed_operator_inventory_demo"],
        ["scripts.seed_operator_inventory_demo", "--tenant", "default", "--enroll-only"],
        ["scripts.seed_operator_inventory_demo", "--tenant", "synthetic-bundles", "--enroll-only"],
        ["scripts.seed_operator_inventory_demo", "--tenant", "synthetic-market-pilot"],
        ["scripts.seed_product_offer_demo"],
        ["scripts.seed_current_qualification_fixture", "--directory", str(directory)],
    ]
    with (directory / "seed.log").open("w", encoding="utf-8") as log:
        for command in commands:
            subprocess.run(
                [sys.executable, "-m", *command],
                cwd=ROOT,
                env=env,
                check=True,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
    qualification = json.loads(
        (directory / "current-qualification-receipt.json").read_text(encoding="utf-8")
    )
    configuration["ROADMAP_QUALIFIED_BASE_SKU"] = qualification["sku"]
    (directory / "runtime-private.json").write_text(
        json.dumps(configuration, indent=2), encoding="utf-8"
    )
    now = fixture_clock or datetime.now(timezone.utc)
    end = now.date() - timedelta(days=1)
    config = json.loads((ROOT / "config/merchant_market_pilot.json").read_text(encoding="utf-8"))
    config.update(
        start_date=(end - timedelta(days=config["days"] - 1)).isoformat(),
        as_of=end.isoformat() + "T23:59:00+00:00",
    )
    config["include_operational_lifecycle"] = True
    config["quote"].update(
        observed_at=now.isoformat(),
        expires_at=(now + timedelta(days=1)).isoformat(),
        source_id="simulation:quote:" + now.isoformat(),
    )
    # The historical snapshot is evaluated at its cutoff by the seed command.
    config["quote"]["observed_at"] = config["as_of"]
    (directory / "market-scenario.json").write_text(json.dumps(config, indent=2), encoding="utf-8")
    with (directory / "market-seed.log").open("w", encoding="utf-8") as log:
        subprocess.run(
            [
                sys.executable,
                "-m",
                "scripts.seed_merchant_market_pilot",
                "--config",
                str(directory / "market-scenario.json"),
                "--output",
                str(directory / "market-receipt.json"),
            ],
            cwd=ROOT,
            env=env,
            check=True,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
    with (
        sqlite3.connect(database) as source,
        sqlite3.connect(directory / "restore.sqlite3") as target,
    ):
        source.backup(target)
        integrity = target.execute("PRAGMA integrity_check").fetchone()[0]
    receipt = dict(
        database=str(database),
        restore=str(directory / "restore.sqlite3"),
        integrity=integrity,
        created_at=now.isoformat(),
        simulation_only=True,
        real_transport_enabled=False,
        market_fixture_clock=now.isoformat(),
        fixture_clock="market clock recorded above; fixed qualification replay preserved; current fictional observations have a separate instance receipt",
    )
    (directory / "receipt.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    print(json.dumps(receipt))


if __name__ == "__main__":
    main()
