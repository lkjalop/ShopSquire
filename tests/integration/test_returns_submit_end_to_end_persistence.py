import base64
import json
import os
import re
import uuid
from io import BytesIO

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from src.app.models.db import db_session, set_engine
from src.app.models.init_db import ensure_metadata
from src.app.services.returns import image_phash_hex


def _png_with_embedded_text(text_value: str) -> bytes:
    try:
        from PIL import Image  # type: ignore
        from PIL.PngImagePlugin import PngInfo  # type: ignore
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(f"PIL required for this test: {exc}")
    img = Image.new("RGB", (320, 200), color=(255, 255, 255))
    meta = PngInfo()
    meta.add_text("shopsquire_text", text_value)
    buf = BytesIO()
    img.save(buf, format="PNG", pnginfo=meta)
    return buf.getvalue()


def _seed_fraud_hash(phash: str) -> None:
    # Force image_reuse -> high score -> human review task created.
    with db_session() as db:
        dialect = ""
        try:
            bind = getattr(db, "get_bind", lambda: None)()
            dialect = str(getattr(getattr(bind, "dialect", None), "name", "") or "").lower()
        except Exception:
            dialect = ""
        if dialect == "postgresql":
            db.execute(
                text(
                    "INSERT INTO fraud_image_hashes (phash, first_seen_case_id, times_seen, confirmed_fraud, created_at) "
                    "VALUES (:phash, 'seed', 1, true, CURRENT_TIMESTAMP) "
                    "ON CONFLICT (phash) DO NOTHING"
                ),
                {"phash": phash},
            )
        else:
            db.execute(
                text(
                    "INSERT OR IGNORE INTO fraud_image_hashes (phash, first_seen_case_id, times_seen, confirmed_fraud, created_at) "
                    "VALUES (:phash, 'seed', 1, 1, CURRENT_TIMESTAMP)"
                ),
                {"phash": phash},
            )
        db.commit()


def _run_returns_submit_flow(img_bytes: bytes) -> None:
    from src.app.main import create_app

    client = TestClient(create_app())
    payload = {
        "sku": "TEST-SKU-123",
        "uid": "u1",
        "description": "test return",
        "images": [{"filename": "upload.png", "b64": base64.b64encode(img_bytes).decode("ascii")}],
        "vertical_pack": "electronics",
    }
    r = client.post("/api/v1/returns/submit", json=payload, headers={"x-api-key": "local-merchant-key"})
    assert r.status_code == 200
    body = r.json()
    assert body.get("case_id")
    assert body.get("evidence_id")
    assert body.get("mode") in ("require_human", "escalate_security")
    assert (body.get("human_review") or {}).get("status") == "pending"

    evidence_id = body["evidence_id"]
    case_id = body["case_id"]

    with db_session() as db:
        row = db.execute(
            text("SELECT bundle_json FROM evidence_bundles WHERE id = :id AND case_id = :case_id"),
            {"id": evidence_id, "case_id": case_id},
        ).fetchone()
        assert row is not None
        bundle = json.loads(row[0] or "{}")
        assert bundle.get("evidence_id") == evidence_id
        assert bundle.get("sku") == "TEST-SKU-123"
        assert "cv" in bundle
        cv = bundle.get("cv") or {}
        assert isinstance(cv.get("images"), list) and cv["images"]
        assert isinstance((cv.get("fields") or {}).get("order_id"), str)

        hr = db.execute(
            text("SELECT status FROM human_review_tasks WHERE case_id = :case_id"),
            {"case_id": case_id},
        ).fetchone()
        assert hr is not None
        assert hr[0] == "pending"

        fs = db.execute(
            text("SELECT score, features_json FROM fusion_scores WHERE case_id = :case_id ORDER BY created_at DESC"),
            {"case_id": case_id},
        ).fetchone()
        assert fs is not None
        assert fs[0] is not None
        feats = json.loads(fs[1] or "{}")
        assert isinstance(feats, dict)
        assert "phash_reuse" in feats
        assert "customer_trust_score" in feats


def test_returns_submit_persists_evidence_and_human_review(monkeypatch, tmp_path):
    monkeypatch.setenv("CV_OCR_PROVIDER", "embedded")
    monkeypatch.setenv("DISABLE_TRACING", "1")
    monkeypatch.setenv("RATE_LIMIT_PER_IP_PER_MIN", "0")

    db_path = tmp_path / "returns_submit.sqlite"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+pysqlite:///{db_path}")

    eng = create_engine(
        f"sqlite+pysqlite:///{db_path}", connect_args={"check_same_thread": False}, future=True
    )
    set_engine(eng)
    try:
        import src.app.models.db as dbmod

        dbmod.SessionLocal = sessionmaker(bind=eng, future=True)
    except Exception:
        pass

    ensure_metadata()

    img_bytes = _png_with_embedded_text("Order: ABCD-123456 Serial: SN-99887766 Total: $199.99")
    phash = image_phash_hex(img_bytes)

    _seed_fraud_hash(phash)
    _run_returns_submit_flow(img_bytes)


def test_returns_submit_persists_evidence_and_human_review_postgres(monkeypatch):
    """Optional: runs against a disposable Postgres DB when a local server is available.

    To force-enable locally, start docker-compose db and set:
      POSTGRES_TEST_ADMIN_URL=postgresql://postgres:postgres@127.0.0.1:5432/postgres
    """
    from alembic.config import Config
    from alembic import command

    monkeypatch.setenv("CV_OCR_PROVIDER", "embedded")
    monkeypatch.setenv("DISABLE_TRACING", "1")
    monkeypatch.setenv("RATE_LIMIT_PER_IP_PER_MIN", "0")
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:6399/15")

    admin_url = os.getenv("POSTGRES_TEST_ADMIN_URL") or "postgresql://postgres:postgres@127.0.0.1:5432/postgres"
    test_db = f"shopsquire_test_{uuid.uuid4().hex[:12]}"
    if not re.fullmatch(r"[a-zA-Z0-9_]+", test_db):
        raise RuntimeError("unsafe_db_name")

    # Check reachability and create a disposable database.
    try:
        admin_eng = create_engine(admin_url, isolation_level="AUTOCOMMIT", future=True)
        with admin_eng.connect() as conn:
            conn.execute(text(f"CREATE DATABASE {test_db}"))
    except Exception:
        # Postgres not reachable in this environment; skip.
        return

    db_url = admin_url.rsplit("/", 1)[0] + f"/{test_db}"
    try:
        monkeypatch.setenv("DATABASE_URL", db_url)
        cfg = Config("alembic.ini")
        cfg.set_main_option("sqlalchemy.url", db_url)
        command.upgrade(cfg, "head")

        eng = create_engine(db_url, future=True)
        set_engine(eng)
        try:
            import src.app.models.db as dbmod

            dbmod.SessionLocal = sessionmaker(bind=eng, future=True)
        except Exception:
            pass

        img_bytes = _png_with_embedded_text("Order: ABCD-123456 Serial: SN-99887766 Total: $199.99")
        phash = image_phash_hex(img_bytes)
        _seed_fraud_hash(phash)
        _run_returns_submit_flow(img_bytes)
    finally:
        try:
            try:
                eng.dispose()
            except Exception:
                pass
            admin_eng.dispose()
        except Exception:
            pass
        try:
            with admin_eng.connect() as conn:
                conn.execute(text(f"DROP DATABASE {test_db} WITH (FORCE)"))
        except Exception:
            pass
