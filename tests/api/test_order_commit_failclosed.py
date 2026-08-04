import pytest
from fastapi import HTTPException

from src.app.routers import orders


class _Result:
    rowcount = 1


class _CommitFailure:
    rolled_back = False

    def execute(self, *_args, **_kwargs):
        return _Result()

    def commit(self):
        raise RuntimeError("database commit failed")

    def rollback(self):
        self.rolled_back = True


def test_cancel_does_not_report_success_when_commit_fails(monkeypatch):
    db = _CommitFailure()
    monkeypatch.setattr(orders, "_get_order_status", lambda *_args: "created")
    monkeypatch.setattr(orders, "release_inventory_for_order", lambda *_args, **_kwargs: None)
    with pytest.raises(HTTPException) as caught:
        orders.cancel_order("ORDER-1", role="owner", db=db)
    assert caught.value.status_code == 503
    assert db.rolled_back is True


def test_return_does_not_report_success_when_commit_fails(monkeypatch):
    db = _CommitFailure()
    monkeypatch.setattr(orders, "_get_order_status", lambda *_args: "delivered")
    with pytest.raises(HTTPException) as caught:
        orders.return_order("ORDER-2", role="owner", db=db)
    assert caught.value.status_code == 503


def test_status_update_does_not_report_success_when_commit_fails(monkeypatch):
    db = _CommitFailure()
    monkeypatch.setattr(orders, "_get_order_status", lambda *_args: "created")
    with pytest.raises(HTTPException) as caught:
        orders.update_status("ORDER-3", orders.OrderStatusUpdate(status="paid"), role="owner", db=db)
    assert caught.value.status_code == 503
