import pytest
from src.app.services.catalog_shortfall_projection import stretch_consent_receipt


def test_stretch_is_explicit_revision_bound_and_does_not_replace_budget():
    assert stretch_consent_receipt(None, case_id='case', revision=3, budget=300000, reviewer='buyer') is None
    receipt = stretch_consent_receipt({'expected_revision': 3, 'unit_cap_cents': 330000},
        case_id='case', revision=3, budget=300000, reviewer='buyer')
    assert receipt['original_unit_budget_cents'] == 300000
    assert receipt['unit_cap_cents'] == 330000
    assert receipt['commerce_authority'] == 'none'
    assert receipt['scope'] == 'this_acceptance_only'


@pytest.mark.parametrize('revision,budget,cap', [(4,300000,330000),(3,None,330000),(3,300000,300000),(3,300000,True)])
def test_invalid_or_stale_stretch_fails_closed(revision,budget,cap):
    with pytest.raises(ValueError):
        stretch_consent_receipt({'expected_revision': 3, 'unit_cap_cents': cap},
            case_id='case', revision=revision, budget=budget, reviewer='buyer')


@pytest.mark.parametrize('change', [{'confirmed': False}, {'unit_cap_cents': True}, {'unit_cap_cents': 330000.5}])
def test_http_contract_rejects_implicit_consent_or_non_integer_money(change):
    from pydantic import ValidationError
    from src.app.schemas.shopping_case import StretchConsent
    with pytest.raises(ValidationError):
        StretchConsent.model_validate({'confirmed': True, 'expected_revision': 3,
            'unit_cap_cents': 330000, **change})
