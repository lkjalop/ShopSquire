from datetime import datetime, timezone
from src.app.services.connectors.steam_requirements import _parse_requirements_html, _bounded_requirements
from src.app.services.recommendation_core.workload_grounding import compile_workload_evidence_requirements


def test_complete_provider_lines_compile_six_required_attributes_with_spans():
    raw = '''<li>OS: Windows 10 64-bit</li><li>Processor: Intel i5-4690 / AMD FX 8350</li>
        <li>Memory: 8 GB RAM</li><li>Graphics: Nvidia GTX 970 / AMD RX 480</li>
        <li>Storage: 150 GB available space</li><li>Additional Notes: SSD required</li>'''
    minimum = _bounded_requirements(_parse_requirements_html(raw, include_source_fields=True))
    compiled = compile_workload_evidence_requirements({'source': 'steam', 'app_id': 'provider-contract-fixture',
        'retrieved_at': datetime.now(timezone.utc).isoformat(), 'confidence': 1,
        'minimum': minimum}, kind='game', name='Fixture workload', product_type='el-6-6')
    claims = {claim.attribute_key: claim for claim in compiled.requirements}
    assert set(claims) == {'os', 'cpu_model', 'gpu_model', 'ram_gb', 'storage_gb', 'storage_type'}
    assert claims['os'].value == ['Windows 10 (64-bit)']
    assert len(claims['cpu_model'].value) == 2
    for key in ('cpu_model', 'gpu_model', 'storage_type'):
        claim = claims[key]
        for span in claim.value_spans:
            assert claim.source_excerpt[span[0]:span[1]].strip()
    assert claims['storage_type'].value == ['ssd']
    from src.app.services.research_outcome import build_research_outcome
    evidence = {'status': 'resolved', 'provider_id': 'steam',
        'canonical_title': 'Fixture workload', 'source_url': 'https://store.steampowered.com/app/fixture/',
        'compiled_requirements': [claim.model_dump(mode='json') for claim in compiled.requirements],
        'claim_rejections': [{'attribute_key': 'gpu_vram_gb', 'reason': 'unsupported_extra'}]}
    def outcome():
        return build_research_outcome(case_id='fixture', case_revision=1, operation_id='fixture',
            research={'evidence': [evidence]}, requirements={},
            catalog_authority='permitted', commerce_authority='none')
    assert outcome().requirement_completeness == 'complete'
    assert outcome().rejected_claim_count == 1
    evidence['compiled_requirements'] = [row for row in evidence['compiled_requirements']
                                        if row['attribute_key'] != 'storage_type']
    assert outcome().requirement_completeness == 'partial'
    assert outcome().catalog_authority == 'blocked'
