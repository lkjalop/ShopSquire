from __future__ import annotations

from src.app.services.product_identity import resolve_product_alias


class _Nested:
    def __init__(self, owner) -> None:
        self.owner = owner

    def __enter__(self):
        self.owner.nested += 1
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


class _Rows:
    @staticmethod
    def fetchall():
        return []


class _Db:
    def __init__(self) -> None:
        self.nested = 0
        self.params = None
        self.sql = ""

    def begin_nested(self):
        return _Nested(self)

    def execute(self, statement, params):
        self.sql = str(statement)
        self.params = dict(params)
        return _Rows()


def test_alias_lookup_uses_migration_owned_flag_inside_savepoint() -> None:
    db = _Db()

    assert resolve_product_alias(
        db, tenant_id="tenant-a", query="please add RGAM-0007"
    ) is None

    assert db.nested == 1
    assert "active=:active" in db.sql
    assert db.params is not None
    assert db.params["active"] == 1
    assert not isinstance(db.params["active"], bool)
