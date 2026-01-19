import json
import os
from dataclasses import dataclass
from functools import lru_cache


@dataclass
class Settings:
    app_env: str
    api_host: str
    api_port: int
    database_url: str
    redis_url: str
    stripe_api_key: str
    feature_flags_path: str


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings(
        app_env=os.getenv("APP_ENV", "local"),
        api_host=os.getenv("API_HOST", "0.0.0.0"),
        api_port=int(os.getenv("API_PORT", "8080")),
        database_url=os.getenv(
            "DATABASE_URL", "postgresql+psycopg2://postgres:postgres@localhost:5432/shopsquire"
        ),
        redis_url=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
        stripe_api_key=os.getenv("STRIPE_API_KEY", "sk_test_xxx"),
        feature_flags_path=os.getenv("FEATURE_FLAGS_PATH", "config/feature_flags.json"),
    )


def load_feature_flags(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {
            "USE_AGENT_CAPABILITIES": True,
            "AGENT_ROLLOUT_PERCENT": 20,
            "CAPABILITIES": {
                "pricing": {"enabled": True, "rollout_percent": 20},
                "support": {"enabled": False, "rollout_percent": 0},
                "inventory": {"enabled": False, "rollout_percent": 0},
            },
            "KILL_SWITCH": False,
            "DECISION_LOG_WRITES_ENABLED": False,
        }
