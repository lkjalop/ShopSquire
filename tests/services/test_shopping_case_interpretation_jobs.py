from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from src.app.models.db import set_engine
from src.app.models.orm import Base, ShoppingCase, ShoppingCaseInterpretationJob
from src.app.services.case_research_plan import build_case_research_plan
from src.app.services.shopping_case_interpretation_jobs import (
    consume_completed_case_interpretation,
    execute_case_interpretation_job,
    recover_pending_case_interpretations,
    schedule_case_interpretation,
)


def _database():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:", future=True,
        connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    set_engine(engine)
    return engine


def _case(db: Session) -> ShoppingCase:
    stamp = datetime.now(timezone.utc)
    case = ShoppingCase(
        case_id="sc-case-1", tenant_id="portfolio", uid="buyer-1",
        status="active", retained_purpose="unfamiliar scientific simulation",
        revision=1, created_at=stamp, updated_at=stamp,
    )
    db.add(case)
    db.commit()
    return case


def test_interpretation_is_durable_revision_bound_and_reconnectable(monkeypatch):
    engine = _database()
    monkeypatch.setenv("OPEN_WORLD_QUERY_PROPOSER_ASYNC_ENABLED", "1")
    monkeypatch.setattr(
        "src.app.workers.task_runner.submit_task", lambda *_args, **_kwargs: "task-1",
    )
    plan = build_case_research_plan(
        "unfamiliar scientific simulation", allow_open_world=True,
    )
    assert plan is not None
    with Session(engine) as db:
        scheduled = schedule_case_interpretation(db, case=_case(db), plan=plan)
    assert scheduled["status"] == "queued"
    assert scheduled["case_revision"] == 1

    monkeypatch.setattr(
        "src.app.services.open_world_query_proposal.propose_open_world_queries",
        lambda incoming, timeout_s: (incoming, {
            "status": "accepted", "model_calls": 1,
            "authority": "discovery_proposal_only",
        }),
    )
    monkeypatch.setattr(
        "src.app.services.decision_log.log_trace_event", lambda **_kwargs: None,
    )
    execute_case_interpretation_job({
        "job_id": scheduled["job_id"], "tenant_id": "portfolio",
    })

    with Session(engine) as db:
        stored = db.execute(select(ShoppingCaseInterpretationJob)).scalar_one()
        assert stored.status == "completed"
        consumed, receipt = consume_completed_case_interpretation(
            db, tenant_id="portfolio", case_id="sc-case-1",
            case_revision=1, plan=plan,
        )
    assert consumed.plan_id == plan.plan_id
    assert receipt["status"] == "completed_durable"
    assert receipt["authority"] == "discovery_proposal_only"


def test_late_interpretation_is_superseded_not_applied(monkeypatch):
    engine = _database()
    monkeypatch.setenv("OPEN_WORLD_QUERY_PROPOSER_ASYNC_ENABLED", "1")
    monkeypatch.setattr(
        "src.app.workers.task_runner.submit_task", lambda *_args, **_kwargs: "task-2",
    )
    plan = build_case_research_plan("novel workload", allow_open_world=True)
    assert plan is not None
    with Session(engine) as db:
        case = _case(db)
        scheduled = schedule_case_interpretation(db, case=case, plan=plan)
        case.revision = 2
        db.commit()
    monkeypatch.setattr(
        "src.app.services.open_world_query_proposal.propose_open_world_queries",
        lambda incoming, timeout_s: (incoming, {"status": "accepted", "model_calls": 1}),
    )
    execute_case_interpretation_job({
        "job_id": scheduled["job_id"], "tenant_id": "portfolio",
    })
    with Session(engine) as db:
        stored = db.execute(select(ShoppingCaseInterpretationJob)).scalar_one()
    assert stored.status == "superseded"
    assert stored.error_code == "case_revision_superseded"
    assert stored.result_plan_json is None


def test_failed_interpretation_returns_to_retry_instead_of_sticking_running(monkeypatch):
    engine = _database()
    monkeypatch.setenv("OPEN_WORLD_QUERY_PROPOSER_ASYNC_ENABLED", "1")
    monkeypatch.setattr(
        "src.app.workers.task_runner.submit_task", lambda *_args, **_kwargs: "task-3",
    )
    plan = build_case_research_plan("another novel workload", allow_open_world=True)
    assert plan is not None
    with Session(engine) as db:
        scheduled = schedule_case_interpretation(db, case=_case(db), plan=plan)
    monkeypatch.setattr(
        "src.app.services.open_world_query_proposal.propose_open_world_queries",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("model unavailable")),
    )
    try:
        execute_case_interpretation_job({
            "job_id": scheduled["job_id"], "tenant_id": "portfolio",
        })
    except RuntimeError:
        pass
    with Session(engine) as db:
        stored = db.execute(select(ShoppingCaseInterpretationJob)).scalar_one()
    assert stored.status == "retry"
    assert stored.error_code == "RuntimeError"


def test_completed_fallback_does_not_claim_model_proposal_authority(monkeypatch):
    engine = _database()
    monkeypatch.setenv("OPEN_WORLD_QUERY_PROPOSER_ASYNC_ENABLED", "1")
    monkeypatch.setattr(
        "src.app.workers.task_runner.submit_task", lambda *_args, **_kwargs: "task-4",
    )
    plan = build_case_research_plan("unfamiliar materials workload", allow_open_world=True)
    assert plan is not None
    with Session(engine) as db:
        scheduled = schedule_case_interpretation(db, case=_case(db), plan=plan)
    monkeypatch.setattr(
        "src.app.services.open_world_query_proposal.propose_open_world_queries",
        lambda incoming, timeout_s: (
            incoming, {"status": "rejected_or_unavailable", "authority": "none"},
        ),
    )
    monkeypatch.setattr(
        "src.app.services.decision_log.log_trace_event", lambda **_kwargs: None,
    )
    execute_case_interpretation_job({
        "job_id": scheduled["job_id"], "tenant_id": "portfolio",
    })
    with Session(engine) as db:
        stored = db.execute(select(ShoppingCaseInterpretationJob)).scalar_one()
        projected = consume_completed_case_interpretation(
            db, tenant_id="portfolio", case_id="sc-case-1",
            case_revision=1, plan=plan,
        )[1]
    assert stored.status == "completed"
    assert projected["authority"] == "none"


def test_restart_reclaims_stale_running_interpretation(monkeypatch):
    engine = _database()
    monkeypatch.setenv("OPEN_WORLD_QUERY_PROPOSER_ASYNC_ENABLED", "1")
    monkeypatch.setenv("CASE_INTERPRETATION_RUNNING_STALE_SEC", "30")
    monkeypatch.setattr(
        "src.app.workers.task_runner.submit_task", lambda *_args, **_kwargs: "task-5",
    )
    plan = build_case_research_plan("novel acoustic workload", allow_open_world=True)
    assert plan is not None
    with Session(engine) as db:
        schedule_case_interpretation(db, case=_case(db), plan=plan)
        job = db.execute(select(ShoppingCaseInterpretationJob)).scalar_one()
        job.status = "running"
        job.updated_at = datetime.now(timezone.utc) - timedelta(minutes=5)
        db.commit()
    assert recover_pending_case_interpretations() == 1
    with Session(engine) as db:
        job = db.execute(select(ShoppingCaseInterpretationJob)).scalar_one()
    assert job.status == "retry"
    assert job.error_code == "stale_running_reclaimed"
