import json

from src.app.flows.nqe_templates import TemplateStore
from src.app.flows.catalog import QuestionTemplateCatalog


def test_template_store_variant_and_version_selection(tmp_path, monkeypatch):
    p = tmp_path / "nqe_templates.json"
    p.write_text(
        json.dumps(
            {
                "tenant-a": {
                    "version": "v2",
                    "default_variant": "control",
                    "variants": {
                        "control": {"templates": [{"id": "ask_budget", "text": "budget?", "intent": "product_search", "product_category": "laptop"}]},
                        "vB": {"templates": [{"id": "ask_use_case", "text": "use case?", "intent": "product_search", "product_category": "laptop"}]},
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("NQE_TEMPLATES_PATH", str(p))
    ts = TemplateStore()
    out = ts.get_templates("product_search", "laptop", tenant_id="tenant-a", variant="vB", version="v2", trace_id="t1")
    assert out and out[0]["id"] == "ask_use_case"
    assert out[0]["variant"] == "vB"
    assert out[0]["version"] == "v2"


def test_template_catalog_falls_back_to_static_when_store_empty(monkeypatch):
    monkeypatch.setenv("NQE_TEMPLATES_PATH", "does-not-exist.json")
    cat = QuestionTemplateCatalog()
    out = cat.get_templates("product_search", "general", tenant_id=None, trace_id="trace-1")
    ids = {x.get("id") for x in out}
    assert "ask_budget" in ids or "ask_budget_tier" in ids
