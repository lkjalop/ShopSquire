from src.app.services.evidence_acquisition_ladder import choose_evidence_stage


def test_known_persona_corpus_hit_never_calls_external_provider():
    result = choose_evidence_stage(
        corpus_hit=True, cache_hit=False, accepted_buyer_upload=False,
        ambiguous_material_gap=False, external_authorized=False,
        local_discovery_enrolled=True, authoritative_origin_enrolled=True,
    )
    assert result.selected_stage == "sealed_corpus"
    assert (result.external_calls, result.paid_calls) == (0, 0)


def test_ambiguous_gap_requires_authorization_before_free_discovery():
    denied = choose_evidence_stage(
        corpus_hit=False, cache_hit=False, accepted_buyer_upload=False,
        ambiguous_material_gap=True, external_authorized=False,
        local_discovery_enrolled=True, authoritative_origin_enrolled=True,
    )
    assert denied.execution_status == "authorization_required"
    assert denied.external_calls == 0
    approved = choose_evidence_stage(
        corpus_hit=False, cache_hit=False, accepted_buyer_upload=False,
        ambiguous_material_gap=True, external_authorized=True,
        local_discovery_enrolled=True, authoritative_origin_enrolled=True,
    )
    assert approved.selected_stage == "local_discovery"
    assert approved.next_stage == "authoritative_origin"
    assert approved.paid_calls == 0


def test_no_provider_falls_back_to_buyer_input_without_claiming_spend():
    result = choose_evidence_stage(
        corpus_hit=False, cache_hit=False, accepted_buyer_upload=False,
        ambiguous_material_gap=True, external_authorized=True,
        local_discovery_enrolled=False, authoritative_origin_enrolled=False,
    )
    assert result.selected_stage == "request_buyer_input"
    assert result.execution_status == "not_configured"
    assert result.paid_calls == 0
