from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.app.models.db import set_engine
from src.app.rules.tenant_config_store import TenantConfigStore
from src.app.services.cv_model_pack import get_model_pack


def test_model_registry_can_disable_ocr_per_tenant(monkeypatch, tmp_path):
    db_path = tmp_path / "model_registry.sqlite"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+pysqlite:///{db_path}")

    eng = create_engine(f"sqlite+pysqlite:///{db_path}", connect_args={"check_same_thread": False}, future=True)
    set_engine(eng)
    try:
        import src.app.models.db as dbmod
        dbmod.SessionLocal = sessionmaker(bind=eng, future=True)
    except Exception:
        pass

    store = TenantConfigStore(cache_ttl=0)
    assert store.set_override("cv_model_registry", {"ocr": {"enabled": False}}, tenant_id="t1") is True

    pack = get_model_pack(None, tenant_id="t1")
    ocr = pack.get("ocr") or {}
    assert str(ocr.get("provider") or "") == "disabled"

