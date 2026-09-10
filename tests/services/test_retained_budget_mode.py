from src.app.services.budget_grammar import canonical_budget_from_accepted_slots
from src.app.services.chat_turn_projection import _extract_confirmed_slots


def test_approximation_survives_a_non_budget_turn():
    slots = _extract_confirmed_slots(query='A laptop for about AUD 3000')
    slots.update(_extract_confirmed_slots(query='It needs more storage'))
    retained = canonical_budget_from_accepted_slots(None, slots)
    assert retained == dict(budget_min=None, budget_max=3000, mode='around', source_span=None)


def test_explicit_new_limit_replaces_approximation_and_old_floor():
    slots = _extract_confirmed_slots(query='between AUD 2000 and 3000')
    slots.update(_extract_confirmed_slots(query='under AUD 1500'))
    assert canonical_budget_from_accepted_slots(None, slots) == dict(
        budget_min=None, budget_max=1500, mode='ceiling', source_span=None,
    )


def test_response_constraints_cannot_rewrite_literal_buyer_budget():
    slots = _extract_confirmed_slots(query='about AUD 3000', response={
        'constraints_used': {'budget_min': 2400, 'budget_max': 3600},
    })
    assert canonical_budget_from_accepted_slots(None, slots)['budget_max'] == 3000


def test_amount_only_ingress_projection_does_not_relabel_retained_approximation():
    slots = _extract_confirmed_slots(query='about AUD 3000')
    inherited_projection = dict(budget_min=None, budget_max=3000, mode='ceiling', source_span=None)
    assert canonical_budget_from_accepted_slots(inherited_projection, slots)['mode'] == 'around'


def test_current_literal_ceiling_takes_precedence_over_retained_approximation():
    from src.app.services.budget_grammar import parse_budget
    slots = _extract_confirmed_slots(query='about AUD 3000')
    assert canonical_budget_from_accepted_slots(parse_budget('under AUD 3000').to_dict(), slots)['mode'] == 'ceiling'
