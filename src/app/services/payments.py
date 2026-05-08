from typing import Dict, Optional

from src.app.security.agent_events import AgentInteractionType, log_agent_security_event
from src.app.security.supply_chain import SupplyChainMonitor


class StripeClient:
    def __init__(self, api_key: str):
        import stripe  # type: ignore

        stripe.api_key = api_key
        self.stripe = stripe
        self.supply_chain = SupplyChainMonitor()

    def create_payment_intent(self, amount_cents: int, currency: str = "USD", metadata: Optional[Dict] = None) -> Dict:
        try:
            self.supply_chain.check_endpoint_integrity("stripe")
        except Exception:
            pass
        intent = self.stripe.PaymentIntent.create(
            amount=int(amount_cents),
            currency=currency.lower(),
            metadata=metadata or {},
        )
        try:
            log_agent_security_event(
                interaction_type=AgentInteractionType.payment_api_call,
                source="shopsquire",
                destination="stripe",
                threat_category=None,
                severity="info",
                confidence=0.2,
                details={"amount_cents": amount_cents, "currency": currency},
                requires_escalation=False,
            )
            self.supply_chain.detect_response_anomaly("stripe", dict(intent))
        except Exception:
            pass
        return {
            "id": intent.get("id"),
            "client_secret": intent.get("client_secret"),
            "amount": intent.get("amount"),
            "currency": intent.get("currency"),
            "status": intent.get("status"),
        }


class PayPalClient:
    def __init__(self, client_id: str, client_secret: str):
        from paypalcheckoutsdk.orders import OrdersCreateRequest  # type: ignore
        from paypalcheckoutsdk.core import SandboxEnvironment, PayPalHttpClient  # type: ignore

        env = SandboxEnvironment(client_id=client_id, client_secret=client_secret)
        self.client = PayPalHttpClient(env)
        self.OrdersCreateRequest = OrdersCreateRequest
        self.supply_chain = SupplyChainMonitor()

    def create_order(self, amount_cents: int, currency: str = "USD", description: Optional[str] = None) -> Dict:
        try:
            self.supply_chain.check_endpoint_integrity("paypal")
        except Exception:
            pass
        req = self.OrdersCreateRequest()
        req.prefer('return=representation')
        req.request_body({
            "intent": "CAPTURE",
            "purchase_units": [
                {
                    "amount": {
                        "currency_code": currency.upper(),
                        "value": f"{amount_cents/100:.2f}",
                    },
                    **({"description": description} if description else {})
                }
            ]
        })
        resp = self.client.execute(req)
        result = resp.result
        try:
            log_agent_security_event(
                interaction_type=AgentInteractionType.payment_api_call,
                source="shopsquire",
                destination="paypal",
                threat_category=None,
                severity="info",
                confidence=0.2,
                details={"amount_cents": amount_cents, "currency": currency},
                requires_escalation=False,
            )
            self.supply_chain.detect_response_anomaly("paypal", getattr(result, "__dict__", {}) or {})
        except Exception:
            pass
        return {"id": getattr(result, 'id', None), "status": getattr(result, 'status', None)}
