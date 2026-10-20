"""Local SDK capabilities required by the payment adapters, without provider calls."""
from importlib import import_module
import logging


_INTERFACES = {
    'stripe': [('stripe', 'PaymentIntent.create'), ('stripe', 'Refund.create')],
    'paypal': [('paypalcheckoutsdk.core', 'SandboxEnvironment'),
               ('paypalcheckoutsdk.core', 'PayPalHttpClient'),
               ('paypalcheckoutsdk.orders', 'OrdersCreateRequest')],
}


def payment_provider_available(provider: str) -> bool:
    requirements = _INTERFACES.get(provider)
    if requirements is None:
        return False
    try:
        for name, path in requirements:
            value = import_module(name)
            for attribute in path.split('.'):
                value = getattr(value, attribute, None)
            if not callable(value):
                return False
    except Exception as error:
        # Optional SDK failures are unavailable capabilities, never exposed errors
        # or proof that credentials/provider connectivity have been validated.
        logging.getLogger(__name__).debug('Payment capability unavailable provider=%s error_type=%s',
                                         provider, type(error).__name__)
        return False
    return True
