"""Exact, expiring authority for queued refund effects."""
import hashlib
import json
import time


def refund_effect_digest(*, tenant_id, order_id, approval_index, amount_cents,
                         currency, intent_id, idempotency_key):
    effect = dict(tenant_id=tenant_id, order_id=order_id, approval_index=approval_index,
                  amount_cents=amount_cents, currency=currency, intent_id=intent_id,
                  idempotency_key=idempotency_key, policy='refund-effect-v1')
    return hashlib.sha256(json.dumps(effect, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def refund_permit_current(row):
    try:
        return (not row['revoked_at'] and float(row['authorized_until'] or 0) > time.time()
                and row['effect_digest'] == refund_effect_digest(**{
                    k:row[k] for k in ('tenant_id','order_id','approval_index','amount_cents',
                                      'currency','intent_id','idempotency_key')}))
    except (KeyError, TypeError, ValueError):
        return False
