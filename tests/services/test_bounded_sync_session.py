from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace

from sqlalchemy import create_engine, text

from src.app.services.bounded_sync_session import run_isolated_sync_session


class _Request:
    def __init__(self, engine):
        self.app = SimpleNamespace(state=SimpleNamespace(engine=engine))

    async def is_disconnected(self):
        return False


def test_sync_session_is_owned_by_a_bounded_worker(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'bounded.db'}",
        connect_args={"check_same_thread": False},
        future=True,
    )
    main_thread = threading.get_ident()

    async def operation(db, _cancelled):
        assert threading.get_ident() != main_thread
        db.execute(text("CREATE TABLE proof (value INTEGER NOT NULL)"))
        db.execute(text("INSERT INTO proof(value) VALUES (1)"))
        db.commit()
        return int(db.execute(text("SELECT count(*) FROM proof")).scalar_one())

    assert asyncio.run(run_isolated_sync_session(_Request(engine), operation)) == 1


def test_timeout_signals_cooperative_cancellation(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'cancel.db'}",
        connect_args={"check_same_thread": False},
        future=True,
    )
    observed = threading.Event()

    async def operation(_db, cancelled):
        while not cancelled():
            await asyncio.sleep(0.005)
        observed.set()
        return "late"

    async def run():
        try:
            await run_isolated_sync_session(_Request(engine), operation, timeout_s=0.05)
        except TimeoutError:
            return
        raise AssertionError("timeout expected")

    asyncio.run(run())
    assert observed.wait(1.0)
