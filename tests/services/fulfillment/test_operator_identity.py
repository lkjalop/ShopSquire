"""Per-user identity plumbing (#4) — additive Actor.user_id, stamped into the audit, sentinel when no JWT."""
from __future__ import annotations

import base64
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.app.security.auth import OperatorSubject, _bearer_email, _bearer_subject, operator_subject
from src.app.services.fulfillment import repository as repo
from src.app.services.fulfillment import workflow as wf
from src.app.services.fulfillment.domain import Actor, ActorType as A


@pytest.fixture()
def db():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True)
    s = sessionmaker(bind=eng, future=True)()
    try:
        yield s
    finally:
        s.close()


def _jwt(claims: dict) -> str:
    seg = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")
    return f"Bearer {seg({'alg': 'none', 'typ': 'JWT'})}.{seg(claims)}.sig"


def test_actor_user_id_is_additive():
    assert Actor(A.AGENT, "agent").user_id == ""                        # default — old construction unchanged
    a = Actor(A.HUMAN_OPERATOR, "owner", user_id="u-jane")
    assert a.id == "owner" and a.user_id == "u-jane"                    # authority axis + audit axis, distinct


def test_transition_stamps_actor_user_id_into_audit(db):
    cid = wf.open_case(db, buyer_uid_hash="u1", source_trace_id="T1", requested_by="u1",
                       now_iso="2026-06-30 09:00:00"); db.commit()
    res = wf.transition(db, case_id=cid, event="availability_assessed",
                        actor=Actor(A.AGENT, "agent", user_id="u-jane"),
                        state_patch={"availability": {"requested_qty": 10, "in_stock": 4, "shortfall": 6}},
                        now_iso="2026-06-30 09:00:01")
    assert res.ok
    cur = repo.current_version(db, cid)
    assert cur.evidence.get("actor_user_id") == "u-jane"               # WHO fired it is on the bitemporal record


def test_transition_without_user_id_records_nothing_extra(db):
    cid = wf.open_case(db, buyer_uid_hash="u1", source_trace_id="T1", requested_by="u1",
                       now_iso="2026-06-30 09:00:00"); db.commit()
    wf.transition(db, case_id=cid, event="availability_assessed", actor=Actor(A.AGENT, "agent"),
                  state_patch={"availability": {"shortfall": 6}}, now_iso="2026-06-30 09:00:01")
    assert "actor_user_id" not in (repo.current_version(db, cid).evidence or {})  # additive — no noise


def test_operator_subject_extracts_jwt_subject_and_email():
    auth = _jwt({"sub": "user-42", "email": "jane@acme.example", "role": "owner"})
    assert _bearer_subject(auth) == "user-42" and _bearer_email(auth) == "jane@acme.example"
    subj = operator_subject(authorization=auth)
    assert isinstance(subj, OperatorSubject) and subj.user_id == "user-42" and subj.email == "jane@acme.example"


def test_operator_subject_empty_without_bearer():
    subj = operator_subject(authorization=None)               # shared API key, no JWT
    assert subj.user_id == "" and subj.email == ""


def test_operator_actor_falls_back_to_role_sentinel():
    from src.app.routers.fulfillment_cases import _operator_actor
    # a JWT present → real user on the actor
    real = _operator_actor("owner", OperatorSubject(user_id="user-42", email="x"))
    assert real.user_id == "user-42" and real.id == "owner"
    # only a shared key → 'key:<role>' sentinel so the audit shows 'shared key, no user'
    sentinel = _operator_actor("owner", OperatorSubject(user_id="", email=""))
    assert sentinel.user_id == "key:owner"
