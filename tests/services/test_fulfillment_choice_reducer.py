from src.app.services.fulfillment_choice_reducer import reduce_fulfillment_choices


def test_partial_inventory_offers_split_wait_next_best_supplier_and_relax_without_actions():
    choices = reduce_fulfillment_choices(
        requested_quantity=30, available_now=12, known_lead_time_days=8,
        deadline_days=10, has_next_best=True, has_architecture_alternative=True,
    )
    assert [choice.choice_id for choice in choices] == [
        "split_delivery", "wait_preferred", "next_best_now", "supplier_enquiry",
        "alternative_architecture", "relax_constraint",
    ]
    assert all(choice.requires_buyer_confirmation for choice in choices)
    assert not any(choice.cart_mutation or choice.supplier_send_authorized for choice in choices)
