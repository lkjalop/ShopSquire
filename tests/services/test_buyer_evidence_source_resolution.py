from src.app.services.buyer_evidence_source_resolution import resolve_buyer_evidence_source


def _sources():
    return [
        {
            "source_id": "factory_io", "publisher": "Real Games",
            "allowed_domains": ["docs.factoryio.com"],
            "canonical_entrypoints": ["https://docs.factoryio.com/manual/system-requirements/"],
            "review_status": "approved",
        },
        {
            "source_id": "autocad", "publisher": "Autodesk",
            "allowed_domains": ["www.autodesk.com"],
            "canonical_entrypoints": ["https://www.autodesk.com/support/autocad"],
            "review_status": "approved",
        },
        {
            "source_id": "revit", "publisher": "Autodesk",
            "allowed_domains": ["www.autodesk.com"],
            "canonical_entrypoints": ["https://www.autodesk.com/support/revit"],
            "review_status": "approved",
        },
        {
            "source_id": "draft_vendor", "publisher": "Draft Vendor",
            "allowed_domains": ["docs.draft.example"],
            "canonical_entrypoints": ["https://docs.draft.example/requirements"],
            "review_status": "pending_independent_human_review",
        },
    ]


def test_exact_url_resolves_without_network_or_authority_inflation():
    result = resolve_buyer_evidence_source(
        source_url="https://docs.factoryio.com/manual/system-requirements/",
        sources=_sources(),
    )
    assert result.status == "resolved"
    assert result.selected_source_id == "factory_io"
    assert result.candidates[0].match_basis == "canonical_url"
    assert result.external_calls == result.paid_calls == 0


def test_unrelated_page_on_allowed_domain_is_not_treated_as_authority():
    result = resolve_buyer_evidence_source(
        source_url="https://www.autodesk.com/company/news", sources=_sources(),
    )
    assert result.status == "not_enrolled"
    assert result.candidates == []


def test_obsolete_path_on_uniquely_enrolled_domain_maps_to_reviewed_canonical():
    result = resolve_buyer_evidence_source(
        source_url="https://docs.factoryio.com/legacy/requirements-2024",
        sources=_sources(),
    )
    assert result.status == "resolved"
    assert result.selected_source_id == "factory_io"
    assert result.candidates[0].match_basis == "enrolled_domain"
    assert result.candidates[0].canonical_url == (
        "https://docs.factoryio.com/manual/system-requirements/"
    )
    assert result.external_calls == result.paid_calls == 0


def test_vendor_resolution_preserves_ambiguity_and_review_state():
    ambiguous = resolve_buyer_evidence_source(vendor_name="Autodesk", sources=_sources())
    assert ambiguous.status == "ambiguous"
    assert {row.source_id for row in ambiguous.candidates} == {"autocad", "revit"}
    pending = resolve_buyer_evidence_source(vendor_name="Draft Vendor", sources=_sources())
    assert pending.status == "not_enrolled"
    assert pending.candidates[0].research_eligible is False


def test_rejects_non_https_or_compound_hints():
    assert resolve_buyer_evidence_source(
        source_url="http://docs.factoryio.com/manual/system-requirements/", sources=_sources(),
    ).status == "invalid"
    assert resolve_buyer_evidence_source(
        source_url="https://docs.factoryio.com/manual/system-requirements/",
        vendor_name="Factory IO", sources=_sources(),
    ).reason == "provide_exactly_one_url_or_vendor_name"
