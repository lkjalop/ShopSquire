import json
from io import BytesIO

import pytest

from src.app.cv.evidence_writer import EvidenceWriter
from src.app.models.db import db_session, set_engine
from src.app.services.cases import create_case
from src.app.services.returns import capture_evidence
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import os


def _png_with_embedded_text(text: str) -> bytes:
    try:
        from PIL import Image  # type: ignore
        from PIL.PngImagePlugin import PngInfo  # type: ignore
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(f"PIL required for this test: {exc}")
    img = Image.new("RGB", (320, 200), color=(255, 255, 255))
    meta = PngInfo()
    meta.add_text("shopsquire_text", text)
    buf = BytesIO()
    img.save(buf, format="PNG", pnginfo=meta)
    return buf.getvalue()


def test_roi_ocr_postprocess_and_persist_evidence_bundle(monkeypatch, tmp_path):
    monkeypatch.setenv("CV_OCR_PROVIDER", "embedded")
    db_path = tmp_path / "returns_cv.sqlite"
    os.environ["DATABASE_URL"] = f"sqlite+pysqlite:///{db_path}"
    eng = create_engine(f"sqlite+pysqlite:///{db_path}", connect_args={"check_same_thread": False}, future=True)
    set_engine(eng)
    try:
        import src.app.models.db as dbmod
        dbmod.SessionLocal = sessionmaker(bind=eng, future=True)
    except Exception:
        pass

    case_id = create_case(order_id=None, issue_type="return", description="test", tenant_id=None)
    img_bytes = _png_with_embedded_text("Order: ABCD-123456 Serial: SN-99887766 Total: $199.99")

    pkg = capture_evidence(
        sku="TEST-SKU-123",
        uid="u1",
        images=[("upload.png", img_bytes)],
        description="test return",
        vertical_pack_id="electronics",
    )
    assert pkg.get("evidence_id")
    assert "cv" in pkg
    assert (pkg.get("cv") or {}).get("fields", {}).get("order_id") == "ABCD-123456"
    assert (pkg.get("cv") or {}).get("fields", {}).get("serial") in ("99887766", "SN-99887766", "SN99887766")

    evidence_id = EvidenceWriter().write(case_id, pkg, evidence_id=pkg.get("evidence_id"))
    assert evidence_id == pkg.get("evidence_id")

    with db_session() as db:
        row = db.execute(
            "SELECT bundle_json FROM evidence_bundles WHERE id = :id",
            {"id": evidence_id},
        ).fetchone()
        assert row is not None
        bundle = json.loads(row[0] or "{}")
        assert bundle.get("evidence_id") == evidence_id
        assert (bundle.get("cv") or {}).get("fields", {}).get("order_id") == "ABCD-123456"
