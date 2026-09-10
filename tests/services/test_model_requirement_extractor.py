import json
import pytest
from datetime import datetime, timezone

from src.app.services.model_requirement_extractor import (
    propose_typed_requirements,
    select_requirement_sections,
)


@pytest.mark.parametrize('value', ['CPU B', ['CPU A', 'CPU B']])
def test_real_quote_cannot_support_invented_model_identity(value):
    raw = json.dumps({'claims':[{
        'attribute':'cpu_model', 'operator':'in' if isinstance(value,list) else 'equals',
        'value':value, 'unit':None, 'requirement_class':'minimum',
        'condition':None, 'page_section':'Minimum', 'quoted_evidence_span':'Processor: CPU A',
    }]})
    receipt = propose_typed_requirements('Minimum\nProcessor: CPU A',
        citation_url='https://publisher.example/requirements',
        observed_at=datetime(2026,9,10,tzinfo=timezone.utc), model_fn=lambda *_:raw)
    assert receipt['claims'] == []
    assert receipt['rejected'][0]['reason'] == 'value_not_in_quoted_span'


def test_model_proposals_are_typed_and_retain_exact_page_spans():
    text = "Recommended\nProcessor: Intel Core i7-12700K\nMemory: 32 GB RAM"
    raw = json.dumps({"claims": [
        {
            "attribute": "cpu_model", "operator": "equals",
            "value": "Intel Core i7-12700K", "unit": None,
            "requirement_class": "recommended", "condition": None,
            "page_section": "Recommended",
            "quoted_evidence_span": "Processor: Intel Core i7-12700K",
        },
        {
            "attribute": "ram_gb", "operator": ">=", "value": 32,
            "unit": "GB", "requirement_class": "recommended", "condition": None,
            "page_section": "Recommended", "quoted_evidence_span": "Memory: 32 GB RAM",
        },
    ]})

    receipt = propose_typed_requirements(
        text,
        citation_url="https://publisher.example/requirements",
        observed_at=datetime(2026, 9, 2, tzinfo=timezone.utc),
        model_fn=lambda _prompt, _timeout: raw,
    )

    assert receipt["status"] == "completed"
    assert [row.attribute for row in receipt["claims"]] == ["cpu_model", "ram_gb"]
    assert receipt["extractor"] == "model_proposal_deterministic_critic"


def test_model_proposal_with_invented_span_is_rejected_by_critic():
    raw = json.dumps({"claims": [{
        "attribute": "ram_gb", "operator": ">=", "value": 64, "unit": "GB",
        "requirement_class": "recommended", "condition": None,
        "page_section": "Recommended", "quoted_evidence_span": "64 GB RAM",
    }]})
    receipt = propose_typed_requirements(
        "Recommended: 16 GB RAM",
        citation_url="https://publisher.example/requirements",
        observed_at=datetime(2026, 9, 2, tzinfo=timezone.utc),
        model_fn=lambda _prompt, _timeout: raw,
    )
    assert receipt["claims"] == []
    assert receipt["rejected"] == [{"attribute": "ram_gb", "reason": "quoted_span_not_found"}]


def test_long_page_selects_requirement_sections_without_rewriting_source_spans():
    filler = "Company news and navigation text.\n" * 500
    source = filler + (
        "System Requirements\nRecommended\nProcessor: Intel Core i7-12700K\n"
        "Graphics API: DirectX 12\nMemory: 32 GB RAM\n"
    ) + filler
    selected = select_requirement_sections(source, max_chars=2_000)

    assert len(selected) <= 2_000
    assert "Processor: Intel Core i7-12700K" in selected
    assert "Graphics API: DirectX 12" in selected
    assert "Memory: 32 GB RAM" in selected
    assert all(line in source for line in selected.splitlines())


def test_model_receipt_records_section_selection_capacity():
    source = ("Navigation filler.\n" * 600) + "Recommended\nMemory: 32 GB RAM"
    raw = json.dumps({"claims": [{
        "attribute": "ram_gb", "operator": ">=", "value": 32, "unit": "GB",
        "requirement_class": "recommended", "condition": None,
        "page_section": "Recommended", "quoted_evidence_span": "Memory: 32 GB RAM",
    }]})
    receipt = propose_typed_requirements(
        source, citation_url="https://publisher.example/requirements",
        observed_at=datetime(2026, 9, 2, tzinfo=timezone.utc),
        model_fn=lambda prompt, _timeout: raw if len(prompt) < 8_000 else "",
    )

    assert receipt["status"] == "completed"
    assert receipt["selected_chars"] < receipt["source_chars"]
    assert receipt["claims"][0].attribute == "ram_gb"
