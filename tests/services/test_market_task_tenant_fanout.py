from contextlib import contextmanager


def test_scheduled_pipeline_fans_out_over_authoritative_tenants(monkeypatch):
    from src.app.models import db as db_module
    from src.app.services import market_pipeline
    from src.app.tasks import market_analysis_tasks

    monkeypatch.setenv("MARKET_PIPELINE_ENABLED", "1")
    monkeypatch.setattr(market_analysis_tasks, "_tenant_ids", lambda: ("tenant-a", "tenant-b"))
    seen = []

    @contextmanager
    def fake_session():
        yield object()

    def fake_pipeline(_db, *, tenant_id, limit):
        seen.append((tenant_id, limit))
        return {"ingested": 1, "findings": 2, "persisted": 2}

    monkeypatch.setattr(db_module, "db_session", fake_session)
    monkeypatch.setattr(market_pipeline, "run_pipeline", fake_pipeline)

    result = market_analysis_tasks.run_market_pipeline.run()

    assert seen == [("tenant-a", 2000), ("tenant-b", 2000)]
    assert result["ingested"] == 2
    assert result["findings"] == 4
    assert result["persisted"] == 4
    assert set(result["tenants"]) == {"tenant-a", "tenant-b"}
