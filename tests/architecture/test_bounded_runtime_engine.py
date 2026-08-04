from __future__ import annotations

from pathlib import Path


def test_application_factory_uses_canonical_bounded_engine_factory() -> None:
    source = Path("src/app/main.py").read_text(encoding="utf-8")
    assert "dbmod.create_runtime_engine(url)" in source
    assert "eng = create_engine(url, pool_pre_ping=True, future=True)" not in source
