"""Exact-message permit binding and separately observed completion."""
import hashlib
import json
from datetime import datetime, timezone

POLICY_VERSION = 'outbound-exact-effect-v1'


def effect_digest(*, tenant_id, case_id, recipient, subject, body, channel,
                  actor_type, actor_id, transition_event, idempotency_key, person_approval_id=None):
    fields = dict(tenant_id=tenant_id, case_id=case_id, recipient=recipient, subject=subject,
                  body=body, channel=channel, actor_type=actor_type, actor_id=actor_id,
                  transition_event=transition_event, idempotency_key=idempotency_key,
                  policy_version=POLICY_VERSION)
    if person_approval_id:
        fields['person_approval_id']=person_approval_id
    return hashlib.sha256(json.dumps(fields, sort_keys=True, separators=(',', ':'),
                                    ensure_ascii=False).encode()).hexdigest()


def permit_current(expiry, revoked, now):
    if revoked or not expiry:
        return False
    try:
        parse = lambda value: datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        end, stamp = parse(expiry), parse(now)
        end = end if end.tzinfo else end.replace(tzinfo=timezone.utc)
        stamp = stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)
        return end > stamp
    except (TypeError, ValueError):
        return False


def completion_status(*, status, provider_ref, ack_status, acked_at):
    if str(provider_ref or '').startswith('DEMO-OUT-'):
        return 'simulated'
    if status == 'sent' and ack_status == 'acked' and acked_at:
        return 'acknowledged'
    if status == 'sent':
        return 'submitted_unverified'
    return 'not_completed'
