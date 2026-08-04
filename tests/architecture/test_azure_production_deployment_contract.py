from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PRODUCTION = ROOT / "infra" / "azure" / "production"


def _read(relative: str) -> str:
    return (PRODUCTION / relative).read_text(encoding="utf-8")


def test_production_network_separates_edge_core_and_private_data():
    network = _read("modules/network.bicep")
    compute = _read("modules/compute.bicep")

    for subnet in ("snet-edge-aca", "snet-core-aca", "snet-private-endpoints"):
        assert subnet in network
    assert network.count("Microsoft.App/environments") == 2
    assert "Microsoft.Network/natGateways" in network
    assert compute.count("publicNetworkAccess: 'Disabled'") == 2
    assert compute.count("zoneRedundant: true") == 2
    assert "managedEnvironmentId: edgeEnvironment.id" in compute
    assert "managedEnvironmentId: coreEnvironment.id" in compute


def test_production_data_plane_is_private_and_replica_is_opt_in():
    data = _read("modules/data.bicep")
    main = _read("main.bicep")

    for service in (
        "Microsoft.DBforPostgreSQL/flexibleServers",
        "Microsoft.Cache/redisEnterprise",
        "Microsoft.KeyVault/vaults",
        "Microsoft.Storage/storageAccounts",
        "Microsoft.ContainerRegistry/registries",
    ):
        assert service in data
    assert data.count("publicNetworkAccess: 'Disabled'") >= 5
    assert "if (enableReadReplica)" in data
    assert "DATABASE_READ_URL" in _read("modules/compute.bicep")
    assert "param databaseUrl" not in main
    assert "param redisUrl" not in main
    assert "Key Vault Secrets User" in main
    assert "Storage Blob Data Contributor" in main
    assert "AcrPull" in main


def test_front_door_is_the_only_public_edge_and_caches_assets_only():
    edge = _read("modules/edge.bicep")

    assert "Premium_AzureFrontDoor" in edge
    assert "sharedPrivateLinkResource" in edge
    assert "Microsoft_DefaultRuleSet" in edge
    assert "Microsoft_BotManagerRuleSet" in edge
    assert "RateLimitRule" in edge
    assert "patternsToMatch: ['/assets/*']" in edge
    assert "patternsToMatch: ['/*']" in edge
    assert edge.count("cacheConfiguration") == 1


def test_deployer_is_migration_gated_and_recovery_is_explicit():
    deploy = _read("deploy-production.ps1")
    recovery = _read("RECOVERY.md")

    assert "deployment group what-if" in deploy
    assert "private-endpoint-connection approve" in deploy
    assert "containerapp job execution show" in deploy
    assert "Migration failed or timed out" in deploy
    assert "Invoke-WebRequest" in deploy
    assert "read replica is\nnot a backup" in recovery
    assert "tenant-isolation" in recovery
    assert "idempotency" in recovery


def test_return_evidence_uses_private_blob_and_versioned_key_vault_key():
    main = _read("main.bicep")
    compute = _read("modules/compute.bicep")
    deploy = _read("deploy-production.ps1")

    assert "return-evidence-key-v1" in main
    assert "returnEvidenceKey = New-RandomSecret" in deploy
    assert "RETURN_EVIDENCE_STORAGE_PROVIDER" in compute
    assert "RETURN_EVIDENCE_KEY_PROVIDER" in compute
    assert "azure_key_vault" in compute
    assert "RETURN_EVIDENCE_KEY_VAULT_URL" in compute
