import uuid

from fastapi.testclient import TestClient

from src.app.main import create_app
from src.app.schemas.recruiting import (
    FeedbackRecord,
    JobRequirement,
    ParseResumeRequest,
    RankingRequest,
    ResumeSchema,
    TriageRequest,
)
from src.app.services.recruiting_pipeline import (
    feedback_summary,
    parse_resume,
    rank_candidates,
    record_feedback,
    triage_candidate,
)


def _resume_text() -> str:
    return """
Jane Doe
jane.doe@example.com
+61 400 111 222
Melbourne, Australia

Summary
Software engineer with API and data platform delivery experience.

Experience
Software Engineer | Acme Pty Ltd Jan 2020 - Dec 2022
Senior Software Engineer | Acme Pty Ltd Jan 2023 - Present

Skills
Python, FastAPI, SQL, Docker, React

Education
Bachelor of Computer Science - University of Melbourne - 2015 - 2018
""".strip()


def test_parse_resume_extracts_structured_fields():
    parsed = parse_resume(ParseResumeRequest(candidate_id="cand-1", text=_resume_text(), source="unit-test"))
    resume = parsed.resume
    assert resume.candidate_id == "cand-1"
    assert resume.full_name == "Jane Doe"
    assert resume.email == "jane.doe@example.com"
    assert len(resume.roles) >= 1
    canon = {s.canonical for s in resume.skills}
    assert "python" in canon
    assert "fastapi" in canon
    assert resume.years_experience >= 1.0
    assert parsed.pipeline.get("parser") == "deterministic-v1"


def test_triage_candidate_produces_explainable_output():
    req = TriageRequest(
        job=JobRequirement(
            job_id="job-1",
            title="Software Engineer",
            min_years_experience=2,
            required_skills=["Python", "FastAPI", "SQL"],
            preferred_skills=["Docker"],
            keywords=["backend", "api"],
        ),
        parse=ParseResumeRequest(candidate_id="cand-2", text=_resume_text()),
        mode="blind",
        latency_path="fast",
        use_semantic_cache=False,
        proxy_attributes={"gender_proxy": "group_a"},
    )
    out = triage_candidate(req)
    assert out.mode == "blind"
    assert out.decision in {"shortlist", "review", "reject"}
    assert out.route in {"allow", "review", "escalate", "block"}
    assert len(out.feature_contributions) >= 4
    assert len(out.citations) >= 1
    assert "suppressed_fields" in (out.fairness or {})


def test_ranking_outputs_fairness_metrics():
    job = JobRequirement(
        job_id="job-rank-1",
        title="Software Engineer",
        min_years_experience=1,
        required_skills=["Python", "SQL"],
        preferred_skills=["FastAPI"],
    )
    resume_a = parse_resume(ParseResumeRequest(candidate_id="cand-a", text=_resume_text())).resume
    resume_b = ResumeSchema(
        candidate_id="cand-b",
        full_name="John Doe",
        years_experience=0.5,
        roles=[],
        skills=[],
        education=[],
        raw_text_hash="b123",
    )
    ranked = rank_candidates(
        RankingRequest(
            job=job,
            top_k=2,
            mode="standard",
            latency_path="fast",
            candidates=[
                TriageRequest(job=job, resume=resume_a, proxy_attributes={"gender_proxy": "group_a"}),
                TriageRequest(job=job, resume=resume_b, proxy_attributes={"gender_proxy": "group_b"}),
            ],
        )
    )
    assert len(ranked.ranked) == 2
    assert ranked.ranked[0].rank == 1
    assert any(a.proxy == "gender_proxy" for a in ranked.fairness)
    audit = next(a for a in ranked.fairness if a.proxy == "gender_proxy")
    assert audit.n == 2


def test_feedback_summary_roundtrip(monkeypatch, tmp_path):
    db_file = tmp_path / "recruiting_feedback.sqlite"
    db_url = f"sqlite+pysqlite:///{db_file.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setenv("DATABASE_URL_RO", db_url)

    job_id = "job-feedback-1"
    record_feedback(
        FeedbackRecord(
            candidate_id="cand-1",
            job_id=job_id,
            recruiter_decision="shortlist",
            model_decision="shortlist",
            model_score=0.86,
            trace_id=f"trace-{uuid.uuid4().hex[:8]}",
        )
    )
    record_feedback(
        FeedbackRecord(
            candidate_id="cand-2",
            job_id=job_id,
            recruiter_decision="reject",
            model_decision="review",
            model_score=0.41,
            trace_id=f"trace-{uuid.uuid4().hex[:8]}",
        )
    )
    summary = feedback_summary(job_id=job_id)
    assert summary.total >= 2
    assert summary.by_decision.get("shortlist", 0) >= 1
    assert summary.by_decision.get("reject", 0) >= 1


def test_recruiting_router_triage_smoke(monkeypatch, tmp_path):
    db_file = tmp_path / "recruiting_api.sqlite"
    db_url = f"sqlite+pysqlite:///{db_file.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setenv("DATABASE_URL_RO", db_url)
    monkeypatch.setenv("MERCHANT_API_KEY", "local-merchant-key")

    app = create_app()
    client = TestClient(app)
    resp = client.post(
        "/api/v1/recruiting/triage",
        headers={"x-api-key": "local-merchant-key"},
        json={
            "job": {
                "job_id": "job-api-1",
                "title": "Software Engineer",
                "min_years_experience": 1,
                "required_skills": ["Python", "SQL"],
                "preferred_skills": ["FastAPI"],
            },
            "parse": {
                "candidate_id": "cand-api-1",
                "text": _resume_text(),
            },
            "mode": "standard",
            "latency_path": "fast",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body.get("decision") in {"shortlist", "review", "reject"}
    assert isinstance(body.get("feature_contributions"), list)
