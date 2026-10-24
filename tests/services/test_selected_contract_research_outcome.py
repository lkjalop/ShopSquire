from datetime import datetime,timezone
import pytest
from src.app.services.research_outcome import build_research_outcome
from src.app.services import portfolio_qualification as fixture
from src.app.services.recommendation_core.requirement_scope import RequirementScope
from src.app.services.recommendation_core.requirement_compiler import compile_authoritative_requirements


@pytest.mark.parametrize('revision,expected',[(4,'complete'),(3,'partial')])
def test_terminal_coverage_uses_current_selected_obligations_not_the_whole_profile(revision,expected):
    now=datetime.now(timezone.utc)
    claim=fixture._claim();claim['observed_at']=now.isoformat()
    contract=fixture.bindings.load_contract_by_id(fixture.CONTRACT_ID)
    compiled=compile_authoritative_requirements([claim],scope=RequirementScope.model_validate(claim['compilation_scope']),
        contract=contract,contract_context=contract.context,now=now)
    receipt=dict(state='current',case_id='case',case_revision=revision,contract_id=contract.id,
        contract_revision=contract.revision,context=contract.context.model_dump())
    out=build_research_outcome(case_id='case',case_revision=4,operation_id='turn',
        research={'evidence':[dict(status='resolved',provider_id=claim['source_id'],source_url='fixture://memory',
            canonical_title=contract.context.subject,compiled_requirements=[r.model_dump() for r in compiled.requirements])]},
        requirements={},catalog_authority='permitted',commerce_authority='none',contract_receipt=receipt)
    assert out.requirement_completeness==expected
    if expected=='complete':assert out.missing_requirement_attributes==[]
