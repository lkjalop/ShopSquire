"""Uniform retention sweeper — deterministic via injected `now`, isolated in-memory DB + fake Redis."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from src.app.services import retention_sweeper as rs


NOW = datetime(2026, 7, 6, 12, 0, 0)
CONFIG = {
    "cart_soft_expire_seconds": 28800,     # 8h
    "cart_hard_purge_seconds": 2592000,    # 30d
    "session_ttl_seconds": 86400,          # 24h
    "conversation_ttl_seconds": 86400,     # 24h
}


def _ts(**kw) -> str:
    return (NOW - timedelta(**kw)).strftime("%Y-%m-%d %H:%M:%S")


@pytest.fixture()
def db():
    eng = create_engine("sqlite+pysqlite:///:memory:")
    with eng.begin() as c:
        c.execute(text("CREATE TABLE draft_orders (id TEXT PRIMARY KEY, customer_id TEXT, line_items TEXT, "
                       "status TEXT DEFAULT 'draft', created_at TEXT, updated_at TEXT)"))
        c.execute(text("CREATE TABLE chat_messages (id TEXT PRIMARY KEY, uid TEXT, content TEXT, created_at TEXT)"))
    Session = sessionmaker(bind=eng)
    s = Session()
    yield s
    s.close()


def _cart(db, updated_delta, status="draft"):
    cid = str(uuid.uuid4())
    ts = (NOW - timedelta(**updated_delta)).strftime("%Y-%m-%d %H:%M:%S")
    db.execute(text("INSERT INTO draft_orders (id, customer_id, line_items, status, created_at, updated_at) "
                    "VALUES (:id, :u, '[]', :st, :ts, :ts)"),
               {"id": cid, "u": "u-" + cid[:6], "st": status, "ts": ts})
    db.commit()
    return cid


def _status(db, cid):
    return db.execute(text("SELECT status FROM draft_orders WHERE id = :id"), {"id": cid}).scalar()


def _exists(db, cid):
    return db.execute(text("SELECT COUNT(*) FROM draft_orders WHERE id = :id"), {"id": cid}).scalar() == 1


# ---- carts: soft-expire vs hard-purge ---------------------------------------

def test_cart_soft_expire_between_soft_and_hard(db):
    cid = _cart(db, {"hours": 10})          # 10h idle -> past 8h soft, well under 30d hard
    rs.sweep_carts(db, now=NOW, soft_seconds=CONFIG["cart_soft_expire_seconds"],
                   hard_seconds=CONFIG["cart_hard_purge_seconds"], dry_run=False)
    db.commit()
    assert _exists(db, cid)                 # RECOVERABLE — row kept
    assert _status(db, cid) == "stale"      # hidden from the active (status='draft') lookup


def test_cart_fresh_not_expired(db):
    cid = _cart(db, {"minutes": 30})        # 30m idle -> fresh, untouched
    rs.sweep_carts(db, now=NOW, soft_seconds=CONFIG["cart_soft_expire_seconds"],
                   hard_seconds=CONFIG["cart_hard_purge_seconds"], dry_run=False)
    db.commit()
    assert _status(db, cid) == "draft"


def test_cart_hard_purge_past_horizon(db):
    cid = _cart(db, {"days": 31})           # 31d idle -> deleted
    rs.sweep_carts(db, now=NOW, soft_seconds=CONFIG["cart_soft_expire_seconds"],
                   hard_seconds=CONFIG["cart_hard_purge_seconds"], dry_run=False)
    db.commit()
    assert not _exists(db, cid)


def test_already_stale_cart_hard_purged_at_horizon(db):
    cid = _cart(db, {"days": 40}, status="stale")   # soft-expired long ago, now past hard horizon
    rs.sweep_carts(db, now=NOW, soft_seconds=CONFIG["cart_soft_expire_seconds"],
                   hard_seconds=CONFIG["cart_hard_purge_seconds"], dry_run=False)
    db.commit()
    assert not _exists(db, cid)


def test_dry_run_mutates_nothing_but_reports(db):
    soft = _cart(db, {"hours": 10})
    hard = _cart(db, {"days": 31})
    report = rs.sweep_carts(db, now=NOW, soft_seconds=CONFIG["cart_soft_expire_seconds"],
                            hard_seconds=CONFIG["cart_hard_purge_seconds"], dry_run=True)
    db.commit()
    assert report == {"carts_hard_purged": 1, "carts_soft_expired": 1}
    assert _status(db, soft) == "draft"     # unchanged
    assert _exists(db, hard)                 # not deleted


# ---- conversation age-out ----------------------------------------------------

def test_conversation_aged_out(db):
    db.execute(text("INSERT INTO chat_messages (id, uid, content, created_at) VALUES ('old', 'u', 'hi', :t)"),
               {"t": _ts(days=2)})
    db.execute(text("INSERT INTO chat_messages (id, uid, content, created_at) VALUES ('new', 'u', 'yo', :t)"),
               {"t": _ts(hours=2)})
    db.commit()
    report = rs.sweep_conversation(db, now=NOW, ttl_seconds=CONFIG["conversation_ttl_seconds"], dry_run=False)
    db.commit()
    assert report == {"chat_messages_purged": 1}
    remaining = db.execute(text("SELECT id FROM chat_messages")).fetchall()
    assert [r[0] for r in remaining] == ["new"]


# ---- redis session TTL backstop ---------------------------------------------

class _FakeRedis:
    """Minimal Redis stub: keys with ttl -1 (no expiry) vs an integer ttl already set."""
    def __init__(self, keys):      # keys: {name: ttl}
        self._keys = dict(keys)
        self.expired = {}
    def scan_iter(self, match=None, count=100):
        import fnmatch
        for k in list(self._keys):
            if match is None or fnmatch.fnmatch(k, match):
                yield k
    def ttl(self, key):
        return self._keys.get(key, -2)
    def expire(self, key, seconds):
        self.expired[key] = seconds
        self._keys[key] = seconds
        return True


def test_redis_sets_ttl_only_on_ttl_less_keys(monkeypatch):
    monkeypatch.setattr(rs, "_DEFAULTS", rs._DEFAULTS)  # no-op; keep import used
    # patch the key templates so the test is independent of the real inventory
    import src.app.services.user_data_inventory as inv
    monkeypatch.setattr(inv, "all_redis_key_templates", lambda: ["session:{uid}:summary", "session:{uid}:kv_state"])
    r = _FakeRedis({
        "session:alice:summary": -1,    # no ttl -> should be set
        "session:alice:kv_state": 500,  # already has ttl -> left alone
        "session:bob:summary": -1,      # no ttl -> should be set
        "unrelated:key": -1,            # not a session template -> ignored
    })
    report = rs.sweep_redis_sessions(r, ttl_seconds=CONFIG["session_ttl_seconds"], dry_run=False)
    assert report == {"session_keys_expiring": 2}
    assert set(r.expired) == {"session:alice:summary", "session:bob:summary"}
    assert r.expired["session:alice:summary"] == 86400


def test_redis_none_is_noop():
    assert rs.sweep_redis_sessions(None, ttl_seconds=1, dry_run=False) == {"session_keys_expiring": 0}


# ---- full run + config -------------------------------------------------------

def test_run_sweep_reports_uniform_not_geo_gated(db):
    _cart(db, {"hours": 10})
    report = rs.run_sweep(db, None, now=NOW, dry_run=True, config=CONFIG)
    assert report["geo_gated"] is False
    assert report["dry_run"] is True
    assert report["carts_soft_expired"] == 1


def test_load_sweeper_config_defaults_when_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(rs, "_CONFIG_PATH", str(tmp_path / "nope.json"))
    cfg = rs.load_sweeper_config()
    assert cfg == rs._DEFAULTS


def test_load_sweeper_config_reads_file(monkeypatch, tmp_path):
    p = tmp_path / "retention_policy.json"
    p.write_text(json.dumps({"sweeper": {"session_ttl_seconds": 3600}}), encoding="utf-8")
    monkeypatch.setattr(rs, "_CONFIG_PATH", str(p))
    cfg = rs.load_sweeper_config()
    assert cfg["session_ttl_seconds"] == 3600
    assert cfg["cart_hard_purge_seconds"] == rs._DEFAULTS["cart_hard_purge_seconds"]   # unspecified -> default


def test_config_guard_hard_never_below_soft(monkeypatch, tmp_path):
    p = tmp_path / "retention_policy.json"
    p.write_text(json.dumps({"sweeper": {"cart_soft_expire_seconds": 9999, "cart_hard_purge_seconds": 10}}), encoding="utf-8")
    monkeypatch.setattr(rs, "_CONFIG_PATH", str(p))
    cfg = rs.load_sweeper_config()
    assert cfg["cart_hard_purge_seconds"] >= cfg["cart_soft_expire_seconds"]
