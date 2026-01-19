from typing import Dict


class StripeClientStub:
    def __init__(self, api_key: str):
        self.api_key = api_key

    def create_payment_intent(self, amount_cents: int, currency: str = "USD") -> Dict:
        # MVP stub (no external call)
        return {"id": "pi_test_123", "amount": amount_cents, "currency": currency, "status": "requires_payment_method"}
