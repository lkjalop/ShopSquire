from src.app.tasks import model_ops_tasks


def test_reindex_new_products_runs_delta_index(monkeypatch):
    seen = {}

    def _fake_run_index(**kwargs):
        seen.update(kwargs)
        return {"catalog": {"indexed": 2, "errors": 0}, "faq": {"indexed": 1, "errors": 0}}

    monkeypatch.setattr("scripts.index_catalog.run_index", _fake_run_index)
    monkeypatch.setattr(model_ops_tasks, "_record_governance_run", lambda **kwargs: None)

    out = model_ops_tasks.reindex_new_products.run()

    assert out["status"] == "ok"
    assert seen["delta_only"] is True
    assert seen["index_catalog"] is True
