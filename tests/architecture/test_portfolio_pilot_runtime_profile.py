from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_pilot_uses_persistent_postgres_redis_and_one_migration_job() -> None:
    values = (ROOT / "helm/shopsquire/values-portfolio-pilot.yaml").read_text(encoding="utf-8")
    assert "migrationJob:\n  enabled: true" in values
    assert "migrations:\n  enabled: false" in values
    assert "persistence:\n    enabled: true" in values
    assert "postgresql+psycopg2://" in values
    assert "REDIS_URL:" in values
    assert "OPERATOR_TENANT_MEMBERSHIP_MODE: strict" in values
    assert "FULFILLMENT_SUPPLIER_TRANSPORT: sandbox" in values
    assert 'FULFILLMENT_AUTONOMOUS_RFQ: "0"' in values


def test_pilot_deployment_waits_for_migration_before_api_rollout() -> None:
    script = (ROOT / "scripts/deploy_portfolio_pilot_kind.ps1").read_text(encoding="utf-8")
    assert "--set replicaCount=0" in script
    assert "kubectl wait --for=condition=complete" in script
    assert "--set migrationJob.enabled=false --set replicaCount=1" in script
    assert script.index("kubectl wait --for=condition=complete") < script.index("kubectl rollout status")


def test_local_runtime_has_services_and_optional_durable_volumes() -> None:
    template = (ROOT / "helm/shopsquire/templates/local-runtime-dependencies.yaml").read_text(
        encoding="utf-8"
    )
    assert "name: shopsquire-postgresql-data" in template
    assert "name: shopsquire-redis-data" in template
    assert "name: shopsquire-redis-master" in template
    assert 'args: ["redis-server", "--appendonly", "yes"' in template
