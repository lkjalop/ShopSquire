"""Concurrent recovery observations and replacement requests; no real effects."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

import tests.chaos.test_outbound_dispatch_postgres as shared_fixtures

from tests.services.test_supplier_enquiry_journey import approved, NOW
from src.app.services import supplier_enquiry_recovery as recovery
from src.app.services.fulfillment import outbound_queue as queue, person_approval, operator_recovery

outbound_engine = shared_fixtures.outbound_engine


def prepare(engine, *, uncertain=False):
    with Session(engine) as db:
        person_approval.ensure_tables(db)
        db.execute(
            text(
                "CREATE TABLE operator_tenant_membership (tenant_id TEXT,principal_hash TEXT,role TEXT,status TEXT)"
            )
        )
        for principal, person in [
            ("alice-key-1", "alice"),
            ("alice-key-2", "alice"),
            ("bob-key", "bob"),
        ]:
            db.execute(
                text(
                    "INSERT INTO operator_tenant_membership VALUES ('shop',:principal,'owner','active')"
                ),
                {"principal": principal},
            )
            person_approval.bind_person(
                db,
                tenant_id="shop",
                principal_hash=principal,
                person_id=person,
                assigned_by="fixture-admin",
            )
        db.commit()
        row = approved(db)
        operator_recovery.ensure_tables(db)
        if uncertain:
            from src.app.services.supplier_enquiry_journey import _effect

            message = queue.enqueue(
                db,
                **_effect(row, "bob-key"),
                person_approval_id=row["approval_id"],
                now_iso=NOW.isoformat(),
            )["message_id"]
            db.execute(
                text("UPDATE outbound_message SET status='reconciliation_required' WHERE id=:id"),
                {"id": message},
            )
        else:
            person_approval.revoke(
                db, tenant_id="shop", approval_id=row["approval_id"], revoked_by="bob-key", now=NOW
            )
            message = None
        db.commit()
        return row, message


def test_concurrent_exact_observations_store_once_and_replay_successfully(
    outbound_engine, monkeypatch
):
    _, message = prepare(outbound_engine, uncertain=True)
    barrier = Barrier(4)
    original = operator_recovery._person

    def authenticate(db, tenant, principal):
        result = original(db, tenant, principal)
        barrier.wait(timeout=5)
        return result

    monkeypatch.setattr(operator_recovery, "_person", authenticate)

    def work(_):
        with Session(outbound_engine) as db:
            result = operator_recovery.resolve(
                db,
                tenant_id="shop",
                message_id=message,
                operator_principal="bob-key",
                outcome="not_delivered",
                evidence_ref="simulation:provider-log:one",
                now=NOW,
            )
            db.commit()
            return result

    with ThreadPoolExecutor(max_workers=4) as workers:
        results = list(workers.map(work, range(4)))
    assert sum(not result["replayed"] for result in results) == 1
    with outbound_engine.connect() as db:
        assert db.scalar(text("SELECT COUNT(*) FROM outbound_recovery_observation")) == 1
        assert db.scalar(text("SELECT status FROM outbound_message")) == "resolved_not_delivered"


def test_conflicting_concurrent_observations_cannot_replace_the_winner(
    outbound_engine, monkeypatch
):
    _, message = prepare(outbound_engine, uncertain=True)
    barrier = Barrier(2)
    original = operator_recovery._person

    def authenticate(db, tenant, principal):
        result = original(db, tenant, principal)
        barrier.wait(timeout=5)
        return result

    monkeypatch.setattr(operator_recovery, "_person", authenticate)

    def work(outcome):
        with Session(outbound_engine) as db:
            try:
                result = operator_recovery.resolve(
                    db,
                    tenant_id="shop",
                    message_id=message,
                    operator_principal="bob-key",
                    outcome=outcome,
                    evidence_ref="simulation:provider-log:" + outcome,
                    provider_ref="PROVIDER-1" if outcome == "submitted" else "",
                    now=NOW,
                )
                db.commit()
                return outcome, result
            except ValueError as exc:
                assert str(exc) == "recovery_observation_conflict"
                db.rollback()
                return None

    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(work, ["submitted", "not_delivered"]))
    successful = [result for result in results if result]
    assert len(successful) == 1
    with outbound_engine.connect() as db:
        assert db.scalar(text("SELECT COUNT(*) FROM outbound_recovery_observation")) == 1
        assert (
            db.scalar(text("SELECT outcome FROM outbound_recovery_observation")) == successful[0][0]
        )
        status = db.scalar(text("SELECT status FROM outbound_message"))
        assert status == ("sent" if successful[0][0] == "submitted" else "resolved_not_delivered")


@pytest.mark.parametrize("same_reference", [False, True])
def test_concurrent_replacement_is_single_and_has_no_inherited_approval(
    outbound_engine, same_reference
):
    row, _ = prepare(outbound_engine)
    barrier = Barrier(2)

    def work(index):
        with Session(outbound_engine) as db:
            barrier.wait(timeout=5)
            try:
                replacement = recovery.renew(
                    db,
                    tenant_id="shop",
                    enquiry_id=row["id"],
                    operator_principal="bob-key",
                    expected_revision=2,
                    reference="same" if same_reference else str(index),
                    recipient_resolver=lambda _: "quotes@fixture.invalid",
                    now=NOW,
                )
                db.commit()
                return replacement["id"]
            except ValueError as exc:
                assert str(exc) == "replacement_already_exists"
                db.rollback()
                return None

    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(work, range(2)))
    assert len({result for result in results if result}) == 1
    assert sum(result is not None for result in results) == (2 if same_reference else 1)
    with outbound_engine.connect() as db:
        replacements = db.execute(
            text(
                "SELECT status,approval_id FROM supplier_enquiry_request WHERE source_reference LIKE 'renew:%'"
            )
        ).all()
        assert [tuple(row) for row in replacements] == [("pending", None)]
        assert db.scalar(text("SELECT COUNT(*) FROM outbound_message")) == 0


def test_review_and_disclosure_edit_serialize_on_the_same_draft(outbound_engine, monkeypatch):
    from src.app.services import supplier_enquiry_journey as journey

    row, _ = prepare(outbound_engine)
    with Session(outbound_engine) as db:
        journey.revise_draft(
            db,
            tenant_id="shop",
            enquiry_id=row["id"],
            operator_principal="alice-key-1",
            expected_version=1,
            include_budget=False,
            now=NOW,
        )
        db.commit()
    reviewing, release, editing, edited = Event(), Event(), Event(), Event()
    original = person_approval.issue

    def pause_review(*args, **kwargs):
        reviewing.set()
        assert release.wait(5)
        return original(*args, **kwargs)

    monkeypatch.setattr(person_approval, "issue", pause_review)

    def approve():
        with Session(outbound_engine) as db:
            result = journey.approve(
                db, tenant_id="shop", enquiry_id=row["id"], approver_principal="bob-key", now=NOW
            )
            db.commit()
            return result

    def edit():
        with Session(outbound_engine) as db:
            editing.set()
            result = journey.revise_draft(
                db,
                tenant_id="shop",
                enquiry_id=row["id"],
                operator_principal="alice-key-1",
                expected_version=2,
                include_budget=True,
                now=NOW,
            )
            db.commit()
            edited.set()
            return result

    with ThreadPoolExecutor(max_workers=2) as workers:
        review = workers.submit(approve)
        assert reviewing.wait(3)
        amendment = workers.submit(edit)
        try:
            assert editing.wait(3)
            assert not edited.wait(0.2), "editing must wait for the review transaction"
        finally:
            release.set()
        approved_row, changed = review.result(timeout=5), amendment.result(timeout=5)
    assert changed["draft_version"] == 3 and changed["status"] == "pending"
    with Session(outbound_engine) as db:
        assert db.scalar(
            text("SELECT revoked_at FROM person_effect_approval WHERE id=:id"),
            {"id": approved_row["approval_id"]},
        )
        current = journey.get(db, tenant_id="shop", enquiry_id=row["id"])
        assert current["status"] == "pending" and current["approval_id"] is None
