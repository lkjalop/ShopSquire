from pathlib import Path


def test_supplier_governance_profile_has_migration_authority() -> None:
    migration = Path("alembic/versions/20260842_supplier_governance_authority.py").read_text(
        encoding="utf-8"
    )
    assert '"supplier_governance_profiles"' in migration
    assert 'down_revision = "20260841_procurement_orchestration"' in migration
