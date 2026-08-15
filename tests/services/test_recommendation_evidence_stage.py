from types import SimpleNamespace

from src.app.services.recommendation_core.evidence_stage import (
    resolve_semantic_evidence_stage,
)


def test_semantic_evidence_stage_compiles_only_provider_evidence(monkeypatch):
    plan = SimpleNamespace(semantic_proposal={
        "desired_outcome": "run an unfamiliar local simulation",
        "concepts": [{
            "text": "unfamiliar local simulation",
            "status": "unresolved",
            "material": True,
            "interpretations": [],
        }],
        "evidence_questions": [],
        "proposed_action": "research",
        "confidence": 0.86,
    })
    envelope = SimpleNamespace(
        query="run an unfamiliar local simulation",
        buyer_query="run an unfamiliar local simulation",
        uid="buyer-1",
        tenant_id="tenant-1",
        external_research_consent=True,
    )
    decision = SimpleNamespace(clarification_relation="continuation")
    observed: dict[str, object] = {}

    def fake_gather(_plan, **kwargs):
        observed.update(kwargs)
        return {"legs": {"concept_resolution": {"data": {
            "status": "resolved",
            "normalized_evidence": [],
            "claims": [{
                "status": "accepted",
                "authority": "official_requirements",
                "source_id": "publisher",
                "source_record_id": "publisher:ram",
                "lineage_root": "publisher",
                "observed_at": "2026-08-15T00:00:00Z",
                "confidence": 0.95,
                "attribute_key": "ram_gb",
                "operator": ">=",
                "value": 32,
                "requirement_class": "minimum",
            }],
            "catalog_qualifications": [{"sku": "EXACT-1"}],
        }}}}

    monkeypatch.setenv("EXTERNAL_RESEARCH_ENABLED", "1")
    monkeypatch.setattr(
        "src.app.services.evidence_orchestrator.gather_evidence", fake_gather,
    )

    result = resolve_semantic_evidence_stage(plan, envelope, decision)

    assert observed["web_consent"] is True
    assert observed["tenant_id"] == "tenant-1"
    assert result.research_trigger.should_execute_external_research is True
    assert [item.attribute_key for item in result.compilation.requirements] == ["ram_gb"]
    assert result.catalog_qualifications == ({"sku": "EXACT-1"},)


def test_semantic_evidence_stage_never_searches_before_authorization(monkeypatch):
    plan = SimpleNamespace(semantic_proposal={
        "desired_outcome": "novel workload",
        "concepts": [{"text": "novel workload", "status": "unresolved", "material": True}],
        "evidence_questions": [],
        "proposed_action": "research",
        "confidence": 0.4,
    })
    envelope = SimpleNamespace(
        query="novel workload", buyer_query="novel workload", uid="buyer-1",
        tenant_id="tenant-1", external_research_consent=False,
    )
    decision = SimpleNamespace(clarification_relation="continuation")
    observed: dict[str, object] = {}

    def fake_gather(_plan, **kwargs):
        observed.update(kwargs)
        return {"legs": {"concept_resolution": {"data": {"status": "unresolved"}}}}

    monkeypatch.setenv("EXTERNAL_RESEARCH_ENABLED", "1")
    monkeypatch.setattr(
        "src.app.services.evidence_orchestrator.gather_evidence", fake_gather,
    )

    result = resolve_semantic_evidence_stage(plan, envelope, decision)

    assert observed["web_consent"] is False
    assert result.research_trigger.authorization_required is True
    assert result.research_trigger.should_execute_external_research is False
