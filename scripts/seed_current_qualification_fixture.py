"""Create a new, explicitly fictional current observation in an owned demo DB.

The fixed portfolio replay is preserved. These invented observations do not
refresh manufacturer evidence or change freshness policy.
"""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import uuid

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from src.app.models.orm import ProductConfiguration, ProductEvidenceObservation, ProductAvailabilityObservation
from src.app.services.commerce_catalog import upsert_inventory
from src.app.services.requirement_contract import load_requirement_contract
from src.app.services.recommendation_core.requirement_scope import resolve_requirement_scope
from src.app.services.taxonomy_registry import upsert_classification, add_sold_node

ROOT = Path(__file__).resolve().parents[1]
TENANT = "synthetic-electronics"
SOURCE = "simulation:current-qualification-v1"


def research_fixture(now, instance):
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("timezone_aware_fixture_clock_required")
    contract = load_requirement_contract(ROOT / "config/requirement_contracts/fictional-memory-lab.json")
    scope = resolve_requirement_scope(tenant_id=TENANT, profile_id="electronics", product_type="el-6-6",
                                      relationship="RUN_SUBJECT_ON_PRODUCT")
    excerpt = "Fictional Memory Lab v1 requires 32 GB RAM; fixture only."
    claim = dict(claim_id=instance + ":requirement", attribute="ram_gb", operator=">=", value=32,
        unit="GB", attribute_key="ram_gb", status="accepted", authority="official_requirements", confidence=1,
        source_record_id=instance, lineage_root="simulation:memory-lab-publisher", requirement_class="minimum",
        authority_status="verified_official", source_id="simulation:memory-lab-publisher",
        source_revision=contract.revision, source_excerpt=excerpt, observed_at=now.isoformat(),
        expires_at=(now + timedelta(hours=24)).isoformat(), applicability=contract.context.model_dump(),
        artefact_name=contract.context.subject, artefact_version=contract.context.version,
        compilation_scope=scope.model_dump(), simulation_only=True)
    evidence = dict(concept=contract.context.subject, status="resolved", claim=excerpt,
        claim_type="minimum_requirements", source_id=claim["source_id"], source_record_id=instance,
        source_revision=contract.revision, observed_at=now.isoformat(), citation_id=instance,
        source_policy=dict(policy_version="semantic-source-v1", review_status="simulation_contract",
            reviewer_type="deterministic_fixture", reviewed_by="versioned-test-contract",
            licence="synthetic-demonstration-only", trust_tier="simulation",
            allowed_claim_types=["minimum_requirements"], freshness_status="fresh", simulation_only=True))
    return dict(fixture_version="fictional-memory-runtime-v1", fixture_instance_id=instance,
        generated_at=now.isoformat(), simulation_only=True, tenant_ids=[TENANT], requires_explicit_consent=True,
        concept_triggers=["fictional memory lab"], result_authority="simulation_contract_only",
        sources=[dict(title="Fictional Memory Lab bounded specification", url="fixture://memory-lab-v1",
                      snippet=excerpt, fetched_ts=now.isoformat())], claims=[claim], normalized_evidence=[evidence])


def seed_current_observations(db, *, now):
    instance = SOURCE + ":" + uuid.uuid4().hex
    fixture = research_fixture(now, instance)
    if db.execute(select(ProductConfiguration.id).where(ProductConfiguration.source_url == SOURCE)).first():
        raise ValueError("current_qualification_fixture_already_exists")
    rows = db.execute(text("""SELECT DISTINCT p.id,p.sku,p.name,p.specs,p.price_cents,p.currency
        FROM products p JOIN price_book_entry b ON b.sku=p.sku
        WHERE b.tenant_id=:tenant AND b.source='simulation:electronics-shortfall-v1'
        AND p.active=1 ORDER BY p.sku"""), {"tenant": TENANT}).all()
    # SKU-only offer requests deliberately refuse ambiguous configurations.
    # Preserve the fixed replay by choosing an unconfigured snapshot identity.
    configured = set(db.execute(select(ProductConfiguration.sku).where(
        ProductConfiguration.tenant_id == TENANT, ProductConfiguration.active.is_(True))).scalars())
    laptops = []
    for row in rows:
        specs = json.loads(row[3]) if isinstance(row[3], str) else row[3] or {}
        ram = specs.get("ram_gb")
        if row[1].startswith("LAP-") and row[1] not in configured and type(ram) is int and ram >= 32:
            laptops.append((row, ram))
    drive = next((row for row in rows if row[1] == "HDD-3A5E65F1"), None)
    if not laptops or drive is None:
        raise ValueError("owned_synthetic_catalogue_prerequisites_missing")
    base, ram = laptops[0]
    configurations = []
    for label, row in (("memory", base), ("backup", drive)):
        configuration = ProductConfiguration(id=instance + ":" + label, tenant_id=TENANT,
            product_id=row[0], sku=row[1], title="FICTIONAL current qualification: " + row[2],
            manufacturer="Fictional Manufacturer", retailer="Fictional Shop", source_url=SOURCE,
            configuration_hash=hashlib.sha256((instance + label).encode()).hexdigest(),
            price_cents=row[4], currency=row[5], specification_observed_at=now,
            price_observed_at=now, availability_observed_at=now)
        if label == "memory":
            configuration.form_factor = configuration.device_class = "laptop"
            configuration.mobility = "mobile"
            configuration.ram_installed_gb = ram
        db.add(configuration)
        configurations.append(configuration)
    db.flush()
    base_config, drive_config = configurations
    db.add(ProductEvidenceObservation(configuration_id=base_config.id, attribute_key="ram_gb",
        value_json={"value": ram, "simulation_only": True}, unit="GB", claim_class="attested",
        evidence_status="observed", source_id=SOURCE, source_record_id=instance + ":memory",
        source_excerpt=f"Invented fixture observation: {ram} GB RAM; not manufacturer certification.",
        observed_at=now, expires_at=now + timedelta(hours=24)))
    benefit = "The fictional pairing provides portable backup; compatibility is invented."
    db.add(ProductEvidenceObservation(configuration_id=base_config.id, attribute_key="supported_product_relation",
        value_json=dict(target_configuration_id=drive_config.id, kind="cross_sell", need="portable_backup",
                        supported=True, benefit=benefit, simulation_only=True),
        claim_class="attested", evidence_status="observed", source_id=SOURCE,
        source_record_id=instance + ":pair", source_excerpt=benefit,
        observed_at=now, expires_at=now + timedelta(hours=24)))
    db.add(ProductAvailabilityObservation(configuration_id=base_config.id, location_id="simulation-network",
        status="in_stock", quantity=15, source_record_id=instance + ":availability",
        observed_at=now, expires_at=now + timedelta(hours=24)))
    for function, kwargs in (
        (upsert_classification, dict(sku=base[1], node_handle="el-6-6", status="approved", confidence=1)),
        (add_sold_node, dict(node_handle="el-6-6")),
    ):
        if not function(db, tenant_id=TENANT, source=SOURCE, approved_by="synthetic-fixture-only", **kwargs):
            raise ValueError("synthetic_taxonomy_initialization_failed")
    if not upsert_inventory(db, tenant_id=TENANT, sku=drive[1], location_id=instance,
                            on_hand=10, source=SOURCE):
        raise ValueError("synthetic_accessory_stock_initialization_failed")
    db.flush()
    return fixture, dict(instance=instance, configuration_ids=[c.id for c in configurations],
                        sku=base[1], observed_at=now.isoformat(), simulation_only=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", required=True, type=Path)
    args = parser.parse_args()
    directory = args.directory.resolve()
    if not directory.is_relative_to((ROOT / ".artifacts").resolve()):
        parser.error("An owned directory inside .artifacts is required")
    configuration = json.loads((directory / "runtime-private.json").read_text(encoding="utf-8"))
    database = directory / "shop.sqlite3"
    if not database.is_file() or database.resolve() != database:
        parser.error("An existing database owned by this directory is required")
    expected = "sqlite:///" + database.as_posix()
    if configuration.get("DATABASE_URL") != expected or configuration.get("APP_ENV") not in {"local", "test"}:
        parser.error("An explicitly owned local SQLite fixture is required")
    fixture_path = directory / "research.json"
    if fixture_path.exists():
        parser.error("Existing research observations must be preserved; prepare a new directory")
    from sqlalchemy import create_engine
    engine = create_engine(expected)
    try:
        with Session(engine) as db:
            fixture, receipt = seed_current_observations(db, now=datetime.now(timezone.utc))
            with fixture_path.open("x", encoding="utf-8") as stream:
                json.dump(fixture, stream, indent=2)
            db.commit()
    finally:
        engine.dispose()
    (directory / "current-qualification-receipt.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    print(json.dumps(receipt))


if __name__ == "__main__":
    main()
