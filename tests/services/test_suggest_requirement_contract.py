"""Recognize the existing contract receipt without accepting arbitrary additions."""
import pytest
from pydantic import ValidationError

from src.app.contracts.suggest_contract import SuggestResponse, validate_response
from src.app.services.recommendation_core.envelope import CoreResponse, TurnEnvelope
from src.app.services.recommendation_core.legacy_adapter import to_legacy


def payload(receipt=None):
    core = CoreResponse(
        envelope=TurnEnvelope.from_suggest_params(query='workstation', uid='contract-buyer'),
        message='No qualified products.', products=[],
    )
    # Mutate the transport payload after the real adapter has built its shape.
    # Malformed HTTP values must reach the validator, not crash trace assembly.
    result = to_legacy(core)
    result['requirement_contract'] = receipt
    return result


@pytest.mark.parametrize('receipt', [None, {}, {'contract_id': 'reviewed-contract', 'fit_authority': 'none'}])
def test_existing_contract_receipt_is_recognized_and_preserved(receipt):
    result = payload(receipt)
    assert validate_response(result) == []
    assert SuggestResponse.model_validate(result).requirement_contract == receipt


@pytest.mark.parametrize('receipt', ['contract-id', True, [], [{}], 3])
def test_contract_receipt_rejects_non_object_values(receipt):
    result = payload(receipt)
    assert 'requirement_contract is not a dict' in validate_response(result)
    with pytest.raises(ValidationError):
        SuggestResponse.model_validate(result)


@pytest.mark.parametrize('addition', ['unreviewed_contract', 'fit_authority_override'])
def test_recognizing_the_receipt_does_not_disable_unknown_field_detection(addition):
    result = payload()
    result.pop('requirement_contract')
    result[addition] = True
    assert validate_response(result) == [f'unknown field (contract addition?): {addition}']
