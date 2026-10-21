"""Explicit nonproduction effect controls shared by preparation and browser replay."""


def simulation_controls():
    return {'FULFILLMENT_SUPPLIER_TRANSPORT':'sandbox','FULFILLMENT_PO_TRANSPORT':'sandbox',
        'PAYMENT_EXECUTION_ENABLED':'0','ALLOW_DEMO_CHECKOUT':'0',
        'STRIPE_API_KEY':'','STRIPE_API_KEY_REF':'','PAYPAL_CLIENT_ID':'','PAYPAL_CLIENT_ID_REF':'',
        'PAYPAL_CLIENT_SECRET':'','PAYPAL_CLIENT_SECRET_REF':'','ERP_PO_URL':'','ERP_API_KEY':''}


def local_backend_isolation():
    """Use the documented local fallback, never an inherited developer cache/queue.

    Real Redis recovery and multi-worker tests require a separately owned backend.
    Port 1 is deliberately unavailable; it is checked by the browser runner.
    """
    return {'REDIS_URL':'redis://127.0.0.1:1/0','REDIS_URL_REF':'',
        'REDIS_ACL_USERNAME':'','REDIS_ACL_PASSWORD':'',
        'SCHEDULER_REDIS_URL':'redis://127.0.0.1:1/0','RQ_REDIS_URL':'redis://127.0.0.1:1/0',
        'CELERY_BROKER_URL':'redis://127.0.0.1:1/0','CELERY_RESULT_BACKEND':'redis://127.0.0.1:1/0',
        'TASK_CONSUMER_ENABLED':'0'}
