import os
from src.app.services.cv_evidence import persist_cv_analysis
from src.app.services.warehouse_verification import WarehouseVerification


def test_warehouse_label_overlap_and_confidence(tmp_path):
    os.environ["DATABASE_URL"] = f"sqlite+pysqlite:///{tmp_path}/wh.sqlite"
    case_id = "CASE-LABEL"
    # First analysis: high confidence, labels A
    persist_cv_analysis(
        case_id=case_id,
        image_sha256="s1",
        image_phash="p1",
        analysis={"damage_type": "screen_crack", "component": "screen", "severity": "minor", "confidence": 0.9},
        labels=["screen", "crack"],
        extracted_text="",
        provider="ollama",
        model="llava",
        processing_time_ms=1000,
    )
    # Latest analysis: different labels set, low confidence
    persist_cv_analysis(
        case_id=case_id,
        image_sha256="s2",
        image_phash="p2",
        analysis={"damage_type": "screen_crack", "component": "screen", "severity": "minor", "confidence": 0.3},
        labels=["hinge", "damage"],
        extracted_text="",
        provider="ollama",
        model="llava",
        processing_time_ms=800,
    )
    ver = WarehouseVerification()
    res = ver.compare_latest_pair(case_id)
    assert res["status"] == "ok"
    assert "labels_overlap_low" in res["mismatches"]
    assert "confidence_delta_high" in res["mismatches"]
