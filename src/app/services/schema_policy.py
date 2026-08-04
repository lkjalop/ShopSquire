"""Policy boundary for legacy runtime DDL.

Production schema is owned by Alembic. Local/test databases may retain idempotent bootstrap DDL
while fixtures and demo databases transition to versioned migrations.
"""
from __future__ import annotations

import os


def runtime_ddl_allowed() -> bool:
    override = str(os.getenv("ALLOW_RUNTIME_DDL", "")).strip().lower()
    if override:
        return override in ("1", "true", "yes", "on")
    env = str(os.getenv("APP_ENV", "local") or "local").strip().lower()
    return env in ("local", "dev", "development", "test", "testing")
