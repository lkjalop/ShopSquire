"""Tenant-bound privacy state requires an acknowledged shared-backend write.

Legacy UID-only values have no trustworthy controller attribution. They must
not be read as opt-in authority for any tenant. A process-local fallback cannot
acknowledge a privacy request; Redis persistence/recovery is a separate gate.
"""
import hashlib

from src.app.deps import hash_uid
from src.app.platform.tenant_context import current_tenant_id


class PrivacyStoreUnavailable(RuntimeError):
    pass


def privacy_key(uid, kind):
    if kind not in {'consent', 'requests'}:
        raise ValueError('unknown_privacy_state_kind')
    controller = hashlib.sha256(current_tenant_id().encode('utf-8')).hexdigest()
    return f'privacy:v2:{controller}:{hash_uid(uid)}:{kind}'


def _require_shared_backend(redis):
    if getattr(redis, 'is_shared_backend', True) is False:
        raise PrivacyStoreUnavailable('privacy_backend_unavailable')


def load_privacy_value(redis, key):
    try:
        _require_shared_backend(redis)
        return redis.get(key)
    except Exception:
        raise PrivacyStoreUnavailable('privacy_backend_unavailable') from None


def store_privacy_value(redis, key, value):
    try:
        _require_shared_backend(redis)
        acknowledged = redis.set(key, value)
        if acknowledged is not True and acknowledged not in ('OK', b'OK'):
            raise PrivacyStoreUnavailable('privacy_backend_unavailable')
    except Exception:
        raise PrivacyStoreUnavailable('privacy_backend_unavailable') from None
