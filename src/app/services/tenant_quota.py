from __future__ import annotations

import os
from datetime import date
from typing import Dict, Tuple

from src.app.config import get_settings


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except Exception:
        return default


class TenantQuotaGuard:
    """Simple per-tenant daily quotas for enterprise guardrails."""

    def __init__(self, redis_client):
        self.redis = redis_client
        env_val = os.getenv("TENANT_QUOTAS_ENABLED")
        if env_val is not None:
            self.enabled = str(env_val).strip().lower() in ("1", "true", "yes", "on")
        else:
            self.enabled = get_settings().app_env.lower() in ("production", "prod")
        self.limits = {
            "recommend_calls": _env_int("TENANT_QUOTA_RECOMMEND_CALLS_DAILY", 50000),
            "cv_calls": _env_int("TENANT_QUOTA_CV_CALLS_DAILY", 10000),
            "escalations": _env_int("TENANT_QUOTA_ESCALATIONS_DAILY", 5000),
        }

    def _key(self, tenant_id: str, metric: str) -> str:
        return f"tenant_quota:{tenant_id}:{metric}:{date.today().isoformat()}"

    def get_usage(self, tenant_id: str, metric: str) -> int:
        try:
            return int(self.redis.get(self._key(tenant_id, metric)) or 0)
        except Exception:
            return 0

    def get_remaining(self, tenant_id: str, metric: str) -> int:
        lim = int(self.limits.get(metric, 0))
        if lim < 0:
            return 0
        return max(0, lim - self.get_usage(tenant_id, metric))

    def check_and_consume(self, tenant_id: str | None, metric: str, amount: int = 1) -> Tuple[bool, Dict[str, int | str]]:
        if not self.enabled:
            return True, {"enabled": 0, "remaining": -1, "metric": metric}
        tid = str(tenant_id or "global")
        lim = int(self.limits.get(metric, 0))
        if lim < 0:
            return True, {"enabled": 1, "remaining": -1, "metric": metric}
        usage = self.get_usage(tid, metric)
        if usage + int(amount) > lim:
            return False, {"enabled": 1, "remaining": max(0, lim - usage), "metric": metric, "limit": lim}
        try:
            key = self._key(tid, metric)
            self.redis.incrby(key, int(amount))
            self.redis.expire(key, 86400)
        except Exception:
            pass
        return True, {"enabled": 1, "remaining": max(0, lim - usage - int(amount)), "metric": metric, "limit": lim}
