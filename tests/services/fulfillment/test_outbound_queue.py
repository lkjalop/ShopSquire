"""Reliable outbound queue — at-least-once send with retry/backoff/dead-letter, idempotency, 855-ack."""
from __future__ import annotations

import sqlite3

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from src.app.services.fulfillment import outbound_queue as q


class _Res:
    def __init__(self, status, provider_ref="", detail=""):
        self.status, self.provider_ref, self.detail = status, provider_ref, detail


class _OkTransport:
    def send(self, *, to, subject, body, idempotency_key=""):
        return _Res("sent", provider_ref="PROV-1")


class _FailTransport:
    def send(self, *, to, subject, body, idempotency_key=""):
        return _Res("failed", detail="smtp_down")


class _CountingFail:
    """Fails the first N calls, then succeeds — proves a retried message eventually delivers."""
    def __init__(self, fail_times):
        self.calls = 0
        self.fail_times = fail_times

    def send(self, *, to, subject, body, idempotency_key=""):
        self.calls += 1
        if self.calls <= self.fail_times:
            return _Res("failed", detail="transient")
        return _Res("sent", provider_ref="PROV-EVENTUAL")


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Session = sessionmaker(bind=engine)
    s = Session()
    s.execute(text(q._DDL))
    s.commit()
    yield s
    s.close()


def _enq(db, key="hash-1", now="2026-06-28T10:00:00"):
    return q.enqueue(db, case_id="c1", recipient="s@x.com", subject="RFQ", body="...",
                     idempotency_key=key, max_attempts=3, now_iso=now)


def test_enqueue_then_process_sends(db):
    _enq(db)
    out = q.process_pending(db, transport=_OkTransport(), now_iso="2026-06-28T10:00:01")
    assert out["sent"] == 1 and out["dead_lettered"] == 0
    row = db.execute(text("SELECT status, provider_ref FROM outbound_message")).fetchone()
    assert row[0] == "sent" and row[1] == "PROV-1"


def test_weekend_email_is_due_even_when_response_sla_is_paused(db):
    q.enqueue(
        db, case_id="weekend", recipient="s@x.com", subject="RFQ", body="...",
        idempotency_key="weekend-email", channel="email",
        response_expectation={"transmission_state": "transmit_now", "sla_clock": "paused"},
        now_iso="2026-08-08T01:00:00+00:00",
    )
    out = q.process_pending(db, transport=_OkTransport(), now_iso="2026-08-08T01:00:01+00:00")
    assert out["sent"] == 1
    row = db.execute(text(
        "SELECT channel,sla_clock,schedule_reason,status FROM outbound_message"
    )).one()
    assert tuple(row) == ("email", "paused", "email_transmits_sla_paused", "sent")


def test_phone_contact_is_never_selected_by_email_worker(db):
    q.enqueue(
        db, case_id="phone", recipient="+61000000000", subject="Call supplier", body="...",
        idempotency_key="phone-task", channel="phone",
        response_expectation={
            "transmission_state": "queue_until_open", "sla_clock": "paused",
            "next_open_at": "2026-08-10T23:00:00+00:00",
        }, now_iso="2026-08-08T01:00:00+00:00",
    )
    tx = _CountingTransport()
    out = q.process_pending(db, transport=tx, now_iso="2026-08-11T00:00:00+00:00")
    assert out["processed"] == 0 and tx.calls == 0
    assert db.execute(text("SELECT status FROM outbound_message")).scalar_one() == "queued_contact"


def test_enqueue_is_idempotent_no_double_send(db):
    a = _enq(db, key="same")
    b = _enq(db, key="same")
    assert a["deduped"] is False and b["deduped"] is True and a["message_id"] == b["message_id"]
    assert db.execute(text("SELECT COUNT(*) FROM outbound_message")).fetchone()[0] == 1


def test_failure_schedules_retry_not_dead_letter(db):
    _enq(db)
    out = q.process_pending(db, transport=_FailTransport(), now_iso="2026-06-28T10:00:01")
    assert out["retried"] == 1 and out["dead_lettered"] == 0
    row = db.execute(text("SELECT status, attempts, next_attempt_at FROM outbound_message")).fetchone()
    assert row[0] == "pending" and row[1] == 1 and row[2] > "2026-06-28T10:00:01"  # backed off into the future


def test_retry_is_not_due_until_backoff_elapses(db):
    _enq(db)
    q.process_pending(db, transport=_FailTransport(), now_iso="2026-06-28T10:00:01")
    # one second later the backed-off message is NOT due → nothing processed
    out = q.process_pending(db, transport=_OkTransport(), now_iso="2026-06-28T10:00:02")
    assert out["processed"] == 0
    # far in the future it IS due → delivers
    out2 = q.process_pending(db, transport=_OkTransport(), now_iso="2026-06-28T13:00:00")
    assert out2["sent"] == 1
    row = db.execute(
        text("SELECT status, last_error FROM outbound_message")
    ).fetchone()
    assert row[0] == "sent" and row[1] is None


def test_max_attempts_dead_letters(db):
    _enq(db, key="doomed")  # max_attempts=3
    far = ["2026-06-28T10:00:01", "2026-06-28T14:00:00", "2026-06-29T00:00:00"]
    tx = _FailTransport()
    for t in far:
        q.process_pending(db, transport=tx, now_iso=t)
    row = db.execute(text("SELECT status, attempts FROM outbound_message")).fetchone()
    assert row[0] == "dead_letter" and row[1] == 3


def test_record_ack_closes_the_loop(db):
    _enq(db, key="ackme")
    q.process_pending(db, transport=_OkTransport(), now_iso="2026-06-28T10:00:01")
    assert q.queue_status(db)["unacknowledged_sent"] == 1
    r = q.record_ack(db, idempotency_key="ackme", ack_ref="855-REF", now_iso="2026-06-28T11:00:00")
    assert r["acked"] is True
    assert q.queue_status(db)["unacknowledged_sent"] == 0
    row = db.execute(text("SELECT ack_status, provider_ref FROM outbound_message")).fetchone()
    assert row[0] == "acked" and row[1] == "855-REF"


def test_queue_status_counts_by_status(db):
    _enq(db, key="a")
    _enq(db, key="b")
    q.process_pending(db, transport=_OkTransport(), now_iso="2026-06-28T10:00:01")
    st = q.queue_status(db)["by_status"]
    assert st.get("sent") == 2


def test_send_now_delivers_and_reports_sent(db):
    r = q.send_now(db, case_id="c1", recipient="s@x.com", subject="RFQ", body="...",
                   idempotency_key="sn-1", transport=_OkTransport(), now_iso="2026-06-28T10:00:00")
    assert r["status"] == "sent" and r["provider_ref"] == "PROV-1"


def test_send_now_transient_failure_is_pending_then_redispatch_dedupes(db):
    tx = _CountingFail(fail_times=1)
    r1 = q.send_now(db, case_id="c1", recipient="s@x.com", subject="RFQ", body="...",
                    idempotency_key="sn-2", transport=tx, now_iso="2026-06-28T10:00:00")
    assert r1["status"] == "pending"  # first attempt failed → durably retryable, no transition
    # human re-dispatches far enough in the future that the backoff has elapsed → delivers, no double send
    r2 = q.send_now(db, case_id="c1", recipient="s@x.com", subject="RFQ", body="...",
                    idempotency_key="sn-2", transport=tx, now_iso="2026-06-28T13:00:00")
    assert r2["status"] == "sent"
    assert db.execute(text("SELECT COUNT(*) FROM outbound_message WHERE idempotency_key='sn-2'")).fetchone()[0] == 1


def test_send_now_redispatch_of_delivered_is_deduped_no_second_send(db):
    tx = _OkTransport()
    q.send_now(db, case_id="c1", recipient="s@x.com", subject="RFQ", body="...",
               idempotency_key="sn-3", transport=tx, now_iso="2026-06-28T10:00:00")
    r = q.send_now(db, case_id="c1", recipient="s@x.com", subject="RFQ", body="...",
                   idempotency_key="sn-3", transport=tx, now_iso="2026-06-28T10:05:00")
    assert r["status"] == "sent" and r["detail"] == "deduped"


def test_dead_letters_lists_exhausted(db):
    _enq(db, key="dl-1")  # max_attempts=3
    for t in ("2026-06-28T10:00:01", "2026-06-28T14:00:00", "2026-06-29T00:00:00"):
        q.process_pending(db, transport=_FailTransport(), now_iso=t)
    dl = q.dead_letters(db)
    assert len(dl) == 1 and dl[0]["case_id"] == "c1" and dl[0]["attempts"] == 3


# ── fixes from the Tier-1 #5 review ───────────────────────────────────────────
class _CountingTransport:
    def __init__(self):
        self.calls = 0

    def send(self, *, to, subject, body, idempotency_key=""):
        self.calls += 1
        return _Res("sent", provider_ref="PROV-C")


def test_claimed_sending_row_is_not_resent(db):
    """A row already CLAIMED ('sending', within the stale window) by another worker must NOT be transmitted by
    a concurrent process pass — the claim guard prevents the double-send race."""
    _enq(db, key="claimed")
    db.execute(text("UPDATE outbound_message SET status='sending', updated_at='2026-06-28T10:00:00' "
                    "WHERE idempotency_key='claimed'"))
    db.commit()
    tx = _CountingTransport()
    out = q.process_pending(db, transport=tx, now_iso="2026-06-28T10:01:00")  # well within 300s stale window
    assert tx.calls == 0 and out["processed"] == 0
    assert db.execute(text("SELECT status FROM outbound_message")).fetchone()[0] == "sending"


def test_stale_claim_is_reclaimed_and_delivered(db):
    """A 'sending' row older than the stale-claim window (crashed worker) is reclaimed to pending and retried."""
    _enq(db, key="stale")
    db.execute(text("UPDATE outbound_message SET status='sending', updated_at='2026-06-28T09:00:00' "
                    "WHERE idempotency_key='stale'"))
    db.commit()
    tx = _CountingTransport()
    out = q.process_pending(db, transport=tx, now_iso="2026-06-28T10:00:00")  # >300s later → reclaimed
    assert tx.calls == 1 and out["sent"] == 1
    assert db.execute(text("SELECT status FROM outbound_message")).fetchone()[0] == "sent"


def test_record_ack_rejects_unsent_row(db):
    _enq(db, key="unsent")  # never processed → still pending
    r = q.record_ack(db, idempotency_key="unsent", now_iso="2026-06-28T11:00:00")
    assert r["acked"] is False and r["reason"].startswith("not_sent")
    assert db.execute(text("SELECT ack_status FROM outbound_message")).fetchone()[0] == "awaiting"


def test_record_ack_rejects_case_mismatch(db):
    _enq(db, key="cm")  # case_id="c1"
    q.process_pending(db, transport=_OkTransport(), now_iso="2026-06-28T10:00:01")
    r = q.record_ack(db, idempotency_key="cm", case_id="WRONG-CASE", now_iso="2026-06-28T11:00:00")
    assert r["acked"] is False and r["reason"] == "case_mismatch"
    ok = q.record_ack(db, idempotency_key="cm", case_id="c1", now_iso="2026-06-28T11:00:00")
    assert ok["acked"] is True


def test_sent_rows_carry_the_approved_transition_intent(db):
    q.enqueue(db, case_id="c9", recipient="s@x.com", subject="RFQ", body="...", idempotency_key="intent",
              actor_type="human_operator", actor_id="ap-1", transition_event="external_message_sent",
              now_iso="2026-06-28T10:00:00")
    out = q.process_pending(db, transport=_OkTransport(), now_iso="2026-06-28T10:00:01")
    assert len(out["sent_rows"]) == 1
    row = out["sent_rows"][0]
    assert (row["case_id"] == "c9" and row["actor_type"] == "human_operator"
            and row["transition_event"] == "external_message_sent" and row["provider_ref"] == "PROV-1")
