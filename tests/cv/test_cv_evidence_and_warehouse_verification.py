import os
import json
from src.app.services.cv_evidence import persist_cv_analysis
from src.app.services.warehouse_verification import WarehouseVerification
from src.app.models.db import db_session


def test_persist_and_compare_mismatch(tmp_path):
    os.environ["DATABASE_URL"] = f"sqlite+pysqlite:///{tmp_path}/cv.sqlite"
    case_id = "CASE-1"
    # Persist complaint analysis
    persist_cv_analysis(
        case_id=case_id,
        image_sha256="sha1",
        image_phash="ph1",
        analysis={"damage_type": "screen_crack", "component": "screen", "severity": "minor", "confidence": 0.9},
        labels=["screen", "crack"],
        extracted_text="SN-ABC123",
        provider="ollama",
        model="llava",
        processing_time_ms=1200,
    )
    # Persist return photo analysis with different damage
    persist_cv_analysis(
        case_id=case_id,
        image_sha256="sha2",
        image_phash="ph2",
        analysis={"damage_type": "hinge_damage", "component": "hinge", "severity": "major", "confidence": 0.88},
        labels=["hinge", "damage"],
        extracted_text="SN-ABC123",
        provider="ollama",
        model="llava",
        processing_time_ms=900,
    )
    ver = WarehouseVerification()
    result = ver.compare_latest_pair(case_id)
    assert result["status"] == "ok"
    assert set(result["mismatches"]) >= set(["damage_type", "severity", "damage_location"])  # expect differences
