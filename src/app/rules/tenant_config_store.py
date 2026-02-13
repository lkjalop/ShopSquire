from __future__ import annotations

import json
import time
from typing import Any, Dict, Optional

from src.app.models.db import db_session


class TenantConfigStore:
    """Tenant-scoped overrides for JSON config packs.

    Default behavior:
    - Base config comes from on-disk JSON files.
    - Optional overrides can be stored in DB table `tenant_config_overrides`.

    Table columns:
      tenant_id TEXT (nullable in payload, but stored as 'global' when None)
      config_key TEXT
      value_json TEXT (JSON object)
    """

    def __init__(self, cache_ttl: int = 10):
        self.cache_ttl = int(cache_ttl)
        self._cache: dict[tuple[str, str], dict[str, Any]] = {}

    def _now(self) -> float:
        return time.time()

    def _key(self, tenant_id: str | None, config_key: str) -> tuple[str, str]:
        return (str(tenant_id or "global"), str(config_key or ""))

    def get_override(self, config_key: str, *, tenant_id: str | None = None) -> Optional[Dict[str, Any]]:
        k = self._key(tenant_id, config_key)
        cached = self._cache.get(k)
        if cached and (self._now() - float(cached.get("ts") or 0)) < self.cache_ttl:
            return cached.get("value")

        try:
            with db_session() as db:
                row = db.execute(
                    "SELECT value_json FROM tenant_config_overrides WHERE tenant_id = :tid AND config_key = :k",
                    {"tid": tenant_id or "global", "k": config_key},
                ).fetchone()
        except Exception:
            row = None

        if not row:
            self._cache[k] = {"ts": self._now(), "value": None}
            return None

        try:
            val = json.loads(row[0] or "{}")
            if not isinstance(val, dict):
                val = {}
        except Exception:
            val = {}
        self._cache[k] = {"ts": self._now(), "value": val}
        return val

    def set_override(self, config_key: str, value: Dict[str, Any], *, tenant_id: str | None = None) -> bool:
        if not isinstance(value, dict):
            return False
        try:
            payload = json.dumps(value, ensure_ascii=False)
        except Exception:
            return False
        tid = tenant_id or "global"
        try:
            with db_session() as db:
                db.execute(
                    "INSERT OR REPLACE INTO tenant_config_overrides (tenant_id, config_key, value_json, updated_at) "
                    "VALUES (:tid, :k, :v, CURRENT_TIMESTAMP)",
                    {"tid": tid, "k": config_key, "v": payload},
                )
                db.commit()
            self._cache.pop(self._key(tenant_id, config_key), None)
            return True
        except Exception:
            # Postgres upsert
            try:
                with db_session() as db:
                    db.execute(
                        "INSERT INTO tenant_config_overrides (tenant_id, config_key, value_json, updated_at) "
                        "VALUES (:tid, :k, :v, CURRENT_TIMESTAMP) "
                        "ON CONFLICT (tenant_id, config_key) DO UPDATE SET value_json = EXCLUDED.value_json, updated_at = EXCLUDED.updated_at",
                        {"tid": tid, "k": config_key, "v": payload},
                    )
                    db.commit()
                self._cache.pop(self._key(tenant_id, config_key), None)
                return True
            except Exception:
                return False

    def delete_override(self, config_key: str, *, tenant_id: str | None = None) -> bool:
        tid = tenant_id or "global"
        try:
            with db_session() as db:
                db.execute(
                    "DELETE FROM tenant_config_overrides WHERE tenant_id = :tid AND config_key = :k",
                    {"tid": tid, "k": config_key},
                )
                db.commit()
            self._cache.pop(self._key(tenant_id, config_key), None)
            return True
        except Exception:
            return False

