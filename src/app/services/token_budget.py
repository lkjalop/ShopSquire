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


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except Exception:
        return default


def estimate_tokens(text: str, response_tokens: int = 500) -> int:
    base = max(1, len(text or "") // 4)
    return base + int(response_tokens or 0)


def estimate_cost(tokens: int) -> float:
    cost_per_1k = _env_float("TOKEN_COST_PER_1K", 0.002)
    return (max(tokens, 0) / 1000.0) * cost_per_1k


def infer_tier(uid: str) -> str:
    u = (uid or "").lower()
    if "enterprise" in u or u.startswith("ent"):
        return "enterprise"
    if "premium" in u or u.startswith("prem") or u.startswith("vip"):
        return "premium"
    if "basic" in u:
        return "basic"
    return os.getenv("TOKEN_BUDGET_DEFAULT_TIER", "guest")


class TokenBudget:
    def __init__(self, redis_client):
        self.redis = redis_client
        # Enable token budget checks only when explicitly configured via
        # environment or when running in production. Default to disabled
        # for local/test runs to avoid flakiness in integration tests.
        env_val = os.getenv("TOKEN_BUDGET_ENABLED")
        if env_val is not None:
            self.enabled = str(env_val).lower() in ("1", "true", "yes")
        else:
            self.enabled = get_settings().app_env.lower() in ("production", "prod")
        self.limits = {
            "guest": {
                # A 1,000-token default admitted only one normal recommendation
                # turn (the estimator reserves 500 response tokens), breaking
                # the minimum multi-turn buyer journey in production-shaped
                # environments. Keep a bounded default, but permit roughly one
                # short shopping conversation.
                "daily_tokens": _env_int("TOKEN_BUDGET_GUEST_DAILY_TOKENS", 10000),
                "daily_usd": _env_float("TOKEN_BUDGET_GUEST_DAILY_USD", 1.00),
            },
            "basic": {
                "daily_tokens": _env_int("TOKEN_BUDGET_BASIC_DAILY_TOKENS", 10000),
                "daily_usd": _env_float("TOKEN_BUDGET_BASIC_DAILY_USD", 1.00),
            },
            "premium": {
                "daily_tokens": _env_int("TOKEN_BUDGET_PREMIUM_DAILY_TOKENS", 100000),
                "daily_usd": _env_float("TOKEN_BUDGET_PREMIUM_DAILY_USD", 10.00),
            },
            "enterprise": {
                "daily_tokens": _env_int("TOKEN_BUDGET_ENTERPRISE_DAILY_TOKENS", 10**12),
                "daily_usd": _env_float("TOKEN_BUDGET_ENTERPRISE_DAILY_USD", 10**9),
            },
        }

    def _key(self, uid: str, metric: str) -> str:
        return f"token_budget:{uid}:{metric}:{date.today().isoformat()}"

    def get_usage(self, uid: str) -> Dict[str, float]:
        tokens = 0
        cost = 0.0
        try:
            tokens = int(self.redis.get(self._key(uid, "tokens")) or 0)
            cost = float(self.redis.get(self._key(uid, "cost")) or 0)
        except Exception:
            pass
        return {"tokens": tokens, "cost_usd": cost}

    def check_budget(self, uid: str, tier: str, estimated_tokens: int) -> Tuple[bool, str, Dict[str, float]]:
        if not self.enabled:
            return True, "disabled", {"tokens_remaining": -1, "cost_remaining_usd": -1}
        limits = self.limits.get(tier, self.limits["guest"])
        usage = self.get_usage(uid)
        if usage["tokens"] + estimated_tokens > limits["daily_tokens"]:
            remaining = self.get_remaining(uid, tier)
            return False, "daily_token_limit", remaining
        estimated_cost = estimate_cost(estimated_tokens)
        if usage["cost_usd"] + estimated_cost > limits["daily_usd"]:
            remaining = self.get_remaining(uid, tier)
            return False, "daily_cost_limit", remaining
        return True, "ok", self.get_remaining(uid, tier)

    def record_usage(self, uid: str, tokens: int, cost: float):
        if not self.enabled:
            return
        try:
            token_key = self._key(uid, "tokens")
            cost_key = self._key(uid, "cost")
            if hasattr(self.redis, "pipeline"):
                pipe = self.redis.pipeline()
                pipe.incrby(token_key, int(tokens))
                pipe.incrbyfloat(cost_key, float(cost))
                pipe.expire(token_key, 86400)
                pipe.expire(cost_key, 86400)
                pipe.execute()
            else:
                self.redis.incrby(token_key, int(tokens))
                self.redis.incrbyfloat(cost_key, float(cost))
                self.redis.expire(token_key, 86400)
                self.redis.expire(cost_key, 86400)
        except Exception:
            pass

    def get_remaining(self, uid: str, tier: str) -> Dict[str, float]:
        limits = self.limits.get(tier, self.limits["guest"])
        usage = self.get_usage(uid)
        return {
            "tokens_remaining": max(0, limits["daily_tokens"] - usage["tokens"]),
            "cost_remaining_usd": max(0.0, limits["daily_usd"] - usage["cost_usd"]),
        }
