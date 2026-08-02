from pathlib import Path


def test_sourcing_wave_parent_rfq_has_migration_authority() -> None:
    migration = Path("alembic/versions/20260843_sourcing_wave_rfq.py").read_text(
        encoding="utf-8"
    )
    assert 'down_revision = "20260842_supplier_governance_authority"' in migration
    assert '"parent_rfq_ref"' in migration
    assert '"fulfillment_case_id"' in migration
