"""Money-P0 M3 — refund execution states + idempotent retry (GPT-5.6 #6).

Proves a failed provider refund is RETRYABLE (was raise-and-forget; re-approve returned
no_open_refund_request), and that the retry reuses the same provider key (no double refund).
"""
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
import pytest

from src.app.services import refund_execution as RX


def _db(tmp_path):
    return sessionmaker(bind=create_engine(f"sqlite+pysqlite:///{tmp_path/'rx.sqlite'}"))()


def test_open_execution_is_unique_per_key(tmp_path):
    db = _db(tmp_path)
    a = RX.open_execution(db, order_id="O1", approval_index=0, amount_cents=5000, currency="USD",
                          intent_id="pi_1", idempotency_key="refund:O1:0")
    b = RX.open_execution(db, order_id="O1", approval_index=0, amount_cents=5000, currency="USD",
                          intent_id="pi_1", idempotency_key="refund:O1:0")   # same key → same row
    assert a == b
    assert db.execute(text("SELECT COUNT(*) FROM refund_executions")).scalar() == 1
    assert db.execute(text("SELECT state FROM refund_executions WHERE id=:i"), {"i": a}).scalar() == RX.STATE_PENDING
    db.close()


def test_failed_then_retried_settles_with_same_key(tmp_path):
    db = _db(tmp_path)
    RX.open_execution(db, order_id="O2", approval_index=0, amount_cents=3000, currency="USD",
                      intent_id="pi_2", idempotency_key="refund:O2:0")
    seen_keys = []

    def failing(intent, amount, key):
        seen_keys.append(key)
        raise RuntimeError("provider down")

    out = RX.execute_pending(db, refund_fn=failing)
    assert out["failed"] == 1 and out["settled"] == 0
    assert db.execute(text("SELECT state FROM refund_executions WHERE order_id='O2'")).scalar() == RX.STATE_FAILED

    def ok(intent, amount, key):
        seen_keys.append(key)
        return {"id": "re_123", "status": "succeeded"}

    out2 = RX.execute_pending(db, refund_fn=ok)     # retry the failed one
    assert out2["settled"] == 1
    row = db.execute(text("SELECT state, provider_ref FROM refund_executions WHERE order_id='O2'")).fetchone()
    assert row[0] == RX.STATE_SETTLED and row[1] == "re_123"
    assert seen_keys == ["refund:O2:0", "refund:O2:0"]     # SAME key on both attempts → no double refund
    db.close()


def test_settled_execution_is_not_retried(tmp_path):
    db = _db(tmp_path)
    eid = RX.open_execution(db, order_id="O3", approval_index=0, amount_cents=100, currency="USD",
                            intent_id="pi_3", idempotency_key="refund:O3:0")
    RX.mark_settled(db, eid, provider_ref="re_done")
    calls = {"n": 0}
    RX.execute_pending(db, refund_fn=lambda *a: (calls.__setitem__("n", calls["n"] + 1), {"id": "x"})[1])
    assert calls["n"] == 0   # settled → never re-issued
    db.close()


def test_provider_success_then_local_failure_reuses_provider_key(monkeypatch, tmp_path):
    db = _db(tmp_path)
    RX.open_execution(db, order_id="O5", approval_index=0, amount_cents=700, currency="USD",
                      intent_id="pi_5", idempotency_key="refund:O5:0")
    keys = []
    real_mark = RX.mark_submitted
    local_calls = {"n": 0}

    def local_fail_once(*args, **kwargs):
        local_calls["n"] += 1
        if local_calls["n"] == 1:
            raise RuntimeError("local commit window")
        return real_mark(*args, **kwargs)

    monkeypatch.setattr(RX, "mark_submitted", local_fail_once)

    def provider(_intent, _amount, key):
        keys.append(key)
        return {"id": "re_same", "status": "pending"}

    assert RX.execute_pending(db, refund_fn=provider)["failed"] == 1
    assert RX.execute_pending(db, refund_fn=provider)["failed"] == 0
    assert keys == ["refund:O5:0", "refund:O5:0"]
    assert db.execute(text("SELECT state FROM refund_executions WHERE order_id='O5'")) .scalar() == RX.STATE_SUBMITTED
    db.close()


def test_demo_intent_is_not_executed(tmp_path):
    db = _db(tmp_path)
    RX.open_execution(db, order_id="O4", approval_index=0, amount_cents=100, currency="USD",
                      intent_id="pi_demo_abc", idempotency_key="refund:O4:0")
    out = RX.execute_pending(db, refund_fn=lambda *a: {"id": "x"})
    assert out["checked"] == 0   # demo intent excluded (no provider charge to refund)
    db.close()


def test_expired_revoked_and_modified_refunds_never_dispatch(tmp_path):
    import time
    db = _db(tmp_path)
    calls = []
    for index in range(3):
        eid = RX.open_execution(db, order_id=f'O{index}', approval_index=index, amount_cents=100,
            currency='AUD', intent_id=f'pi_{index}', idempotency_key=f'permit:{index}',
            authorized_until=time.time()-1 if index == 0 else time.time()+60)
        if index == 1:
            assert not RX.revoke_pending(db, exec_id=eid, tenant_id='other')
            assert RX.revoke_pending(db, exec_id=eid, tenant_id='default')
        if index == 2:
            db.execute(text('UPDATE refund_executions SET amount_cents=999 WHERE id=:id'), {'id':eid})
            db.commit()
    RX.execute_pending(db, refund_fn=lambda *args: calls.append(args))
    assert calls == []
    db.close()


def test_retry_does_not_renew_expired_authorization(tmp_path):
    import time
    db = _db(tmp_path)
    args = dict(order_id='O1', approval_index=0, amount_cents=100, currency='AUD',
                intent_id='pi_1', idempotency_key='expired')
    RX.open_execution(db, **args, authorized_until=time.time()-1)
    RX.open_execution(db, **args)
    assert RX.execute_pending(db, refund_fn=lambda *args: (_ for _ in ()).throw(AssertionError('dispatch')))['settled'] == 0
    db.close()


def test_success_without_exact_receipt_cannot_settle(tmp_path):
    db = _db(tmp_path)
    eid = RX.open_execution(db, order_id='O1', approval_index=0, amount_cents=100, currency='AUD',
                           intent_id='pi_1', idempotency_key='no-receipt')
    assert RX.execute_pending(db, refund_fn=lambda *args: {'status':'succeeded'})['failed'] == 1
    assert db.execute(text('SELECT state FROM refund_executions WHERE id=:id'), {'id':eid}).scalar() == RX.STATE_FAILED
    db.close()


def test_expired_worker_cannot_overwrite_newer_settlement(tmp_path):
    db = _db(tmp_path)
    eid = RX.open_execution(db, order_id='O1', approval_index=0, amount_cents=100, currency='AUD',
                           intent_id='pi_1', idempotency_key='fenced')
    def provider(*args):
        db.execute(text("UPDATE refund_executions SET claim_token='new-worker',state='settled',provider_ref='re_done' WHERE id=:id"), {'id':eid})
        db.commit()
        return {'id':'re_old','status':'pending'}
    RX.execute_pending(db, refund_fn=provider)
    assert tuple(db.execute(text('SELECT state,provider_ref FROM refund_executions WHERE id=:id'), {'id':eid}).one()) == ('settled','re_done')
    db.close()


def test_reused_refund_key_cannot_authorize_different_effect(tmp_path):
    import pytest
    db = _db(tmp_path)
    original = dict(order_id="O1", approval_index=0, amount_cents=1000, currency="USD",
                    intent_id="pi_1", idempotency_key="exact-refund", tenant_id="tenant-a")
    RX.open_execution(db, **original)
    for change in ({"tenant_id":"tenant-b"}, {"amount_cents":2000}, {"intent_id":"pi_other"}):
        with pytest.raises(ValueError, match="refund_effect_binding_conflict"):
            RX.open_execution(db, **{**original, **change})
    assert db.execute(text("SELECT COUNT(*) FROM refund_executions")).scalar() == 1
    db.close()


def test_one_refund_receipt_cannot_settle_sibling_partial_refund(tmp_path):
    db = _db(tmp_path)
    ids = [RX.open_execution(db, order_id="O1", approval_index=i, amount_cents=1000,
        currency="USD", intent_id="pi_1", idempotency_key=f"refund-{i}") for i in range(2)]
    for i, eid in enumerate(ids): RX.mark_submitted(db, eid, provider_ref=f"re_{i}")
    assert RX.settle_submitted_for_intent(db, intent_id="pi_1") == 0
    assert RX.settle_submitted_for_intent(db, intent_id="pi_1", provider_ref="re_0") == 1
    assert db.execute(text("SELECT state FROM refund_executions WHERE id=:i"),{"i":ids[1]}).scalar() == RX.STATE_SUBMITTED
    assert RX.settle_submitted_for_intent(db, intent_id="pi_1", provider_ref="re_0") == 0
    db.close()


def test_charge_cumulative_amount_is_not_a_refund_receipt():
    from src.app.services.refund_completion import completed_refund_receipts
    charge = {"id":"ch_1", "payment_intent":"pi_1", "amount_refunded":2000}
    assert completed_refund_receipts("charge.refunded", charge) == []
    charge["refunds"] = {"data":[
        {"id":"re_a", "status":"succeeded", "amount":1000},
        {"id":"re_b", "status":"pending", "amount":1000}]}
    assert completed_refund_receipts("charge.refunded", charge) == [
        {"intent_id":"pi_1", "provider_ref":"re_a", "amount_cents":1000}]


def test_legacy_charge_total_job_cannot_be_counted_as_one_refund():
    import pytest
    from src.app.routers.payments import _handle_payment_outbox_job
    with pytest.raises(ValueError, match="exact_refund_receipt_required"):
        _handle_payment_outbox_job("reconcile_refund", {
            "intent_id":"pi_1", "provider_ref":"ch_1", "amount_cents":2000})


@pytest.mark.parametrize('provider_status', ['failed', 'canceled', '', 'unsupported', None])
def test_failed_or_unknown_provider_status_cannot_be_reported_submitted(tmp_path, provider_status):
    db = _db(tmp_path)
    try:
        execution = RX.open_execution(db, order_id='O1', approval_index=0, amount_cents=100,
            currency='AUD', intent_id='pi_one', idempotency_key='status-control')
        result = RX.execute_pending(db, refund_fn=lambda *args: {
            'id': 're_status', 'status': provider_status})
        assert result['failed'] == 1 and result['settled'] == 0
        assert db.execute(text('SELECT state FROM refund_executions WHERE id=:id'),
                          {'id': execution}).scalar_one() == RX.STATE_FAILED
    finally:
        db.close()


def test_conflicting_refund_replay_cannot_commit_unrelated_caller_work(tmp_path):
    db = _db(tmp_path)
    try:
        original = dict(order_id='O1', approval_index=0, amount_cents=100,
            currency='AUD', intent_id='pi_one', idempotency_key='same-key')
        RX.open_execution(db, **original)
        db.execute(text('CREATE TABLE caller_work (value TEXT)'))
        db.commit()
        db.execute(text("INSERT INTO caller_work VALUES ('pending')"))
        with pytest.raises(ValueError, match='refund_effect_binding_conflict'):
            RX.open_execution(db, **{**original, 'amount_cents': 999})
        db.rollback()
        assert db.execute(text('SELECT COUNT(*) FROM caller_work')).scalar_one() == 0
    finally:
        db.close()


@pytest.mark.parametrize('provider_status', ['pending', 'requires_action'])
def test_recognized_incomplete_refund_is_never_marked_settled(tmp_path, provider_status):
    db = _db(tmp_path)
    try:
        execution = RX.open_execution(db, order_id='O1', approval_index=0, amount_cents=100,
            currency='AUD', intent_id='pi_one', idempotency_key='incomplete')
        result = RX.execute_pending(db, refund_fn=lambda *args: {
            'id': 're_pending', 'status': provider_status})
        assert result['failed'] == result['settled'] == 0
        assert db.execute(text('SELECT state FROM refund_executions WHERE id=:id'),
                          {'id': execution}).scalar_one() == RX.STATE_SUBMITTED
    finally:
        db.close()
