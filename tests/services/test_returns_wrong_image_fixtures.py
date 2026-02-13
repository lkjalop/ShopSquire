import os
from pathlib import Path

from src.app.services.returns import capture_evidence, compute_return_score, mark_evidence_as_fraud


FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "images"


def _read_fixture(name: str) -> bytes:
    return (FIXTURE_DIR / name).read_bytes()


def test_wrong_image_fixture_triggers_reuse_flag(tmp_path):
    os.environ["DATABASE_URL"] = f"sqlite+pysqlite:///{tmp_path}/returns.sqlite"

    wrong_img = _read_fixture("return_wrong_phone.png")
    ok_img = _read_fixture("return_ok_laptop.png")

    # Seed fraud hash with the wrong image.
    pkg1 = capture_evidence("SKU-RET", "uid-1", [("wrong.png", wrong_img)], description="wrong image")
    inserted = mark_evidence_as_fraud(pkg1["evidence_id"])
    assert inserted >= 1

    # Reuse should be detected for the wrong image.
    pkg2 = capture_evidence("SKU-RET", "uid-2", [("wrong.png", wrong_img)], description="wrong image again")
    assert any(s.get("type") == "image_reuse" for s in pkg2.get("fraud_signals", []))
    score = compute_return_score(pkg2)
    assert score["score"] >= 70

    # A clean image should not be flagged as reuse.
    pkg3 = capture_evidence("SKU-RET", "uid-3", [("ok.png", ok_img)], description="ok image")
    assert not any(s.get("type") == "image_reuse" for s in pkg3.get("fraud_signals", []))
