from src.app.routers import chat


def test_chat_uses_owned_transport_security_cart_and_projection_boundaries():
    assert chat._chat_in_progress.__module__ == 'src.app.services.chat_transport'
    assert chat._extract_confirmed_slots.__module__ == 'src.app.services.chat_turn_projection'
    assert chat._assess_image_compromise_breach.__module__ == 'src.app.services.chat_image_security'
    assert chat._cart_mutation_short_circuit.__module__ == 'src.app.services.chat_cart_projection'
