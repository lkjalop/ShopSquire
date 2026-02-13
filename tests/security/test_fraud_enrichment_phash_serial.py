import os
from sqlalchemy import text

from src.app.services.fraud_scorer import FraudScorer
from src.app.models.db import db_session, set_engine
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def test_fraud_enrichment_with_serial_and_phash(tmp_path):
    os.environ["DATABASE_URL"] = f"sqlite+pysqlite:///{tmp_path}/fraud.sqlite"
    # Seed fraud_image_hashes with a confirmed fraud phash
    phash = "abcd1234"
    # Patch engine/session to SQLite for this test
    eng = create_engine(f"sqlite+pysqlite:///{tmp_path}/fraud.sqlite", future=True)
    set_engine(eng)
    try:
        import src.app.models.db as dbmod
        dbmod.SessionLocal = sessionmaker(bind=eng, future=True)
    except Exception:
        pass
    with db_session() as db:
        db.execute(text("CREATE TABLE IF NOT EXISTS fraud_image_hashes (phash TEXT PRIMARY KEY, first_seen_case_id TEXT, times_seen INTEGER, confirmed_fraud INTEGER)"))
        db.execute(text("INSERT INTO fraud_image_hashes (phash, first_seen_case_id, times_seen, confirmed_fraud) VALUES (:p, 'CASE-X', 3, :cf)"), {"p": phash, "cf": True})
        db.commit()
    fs = FraudScorer()
    base = {"damage_not_visible": False}
    score, level, signals = fs.score_with_enrichment(base_signals=base, expected_serial="SN-XYZ", observed_serial="SN-ABC", image_phash=phash, case_id="CASE-Y")
    assert signals["serial_mismatch"] is True
    assert signals["image_hash_match_fraud_db"] is True
    assert level in ("medium", "high")
