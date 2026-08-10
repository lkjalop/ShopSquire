"""Seed the five reviewed evidence-rich configurations."""
from src.app.models.db import db_session
from src.app.services.catalog_evidence_seed import ingest_reviewed_configurations


if __name__ == "__main__":
    with db_session() as db:
        ids = ingest_reviewed_configurations(db)
    print(f"Seeded {len(ids)} reviewed product configurations")
