"""Project exact successful refund receipts from authenticated Stripe events."""
from typing import Any


def completed_refund_receipts(event_type: str, obj: dict[str, Any]) -> list[dict[str, Any]]:
    if event_type == 'charge.refunded':
        candidates = (obj.get('refunds') or {}).get('data') or []
        intent = obj.get('payment_intent')
    elif event_type in {'refund.created', 'refund.updated'}:
        candidates = [obj]
        intent = obj.get('payment_intent')
    else:
        return []
    if not isinstance(intent, str) or not intent:
        return []
    receipts = {}
    for row in candidates:
        if not isinstance(row, dict) or row.get('status') != 'succeeded':
            continue
        ref, amount = row.get('id'), row.get('amount')
        if (not isinstance(ref, str) or not ref.startswith('re_')
                or type(amount) is not int or amount <= 0
                or row.get('payment_intent', intent) != intent):
            continue
        receipts[ref] = {'intent_id':intent, 'provider_ref':ref, 'amount_cents':amount}
    return list(receipts.values())
