from __future__ import annotations

import json
import time
from typing import Dict, Any, List, Optional

from src.app.models.db import db_session


class RuleStore:
    """Persistence layer for rule definitions.

    - Loads tenant-scoped rules and global rules
    - Caches in memory with TTL and supports explicit refresh
    """

    def __init__(self, cache_ttl: int = 30):
        self.cache_ttl = cache_ttl
        self._cache: Dict[Optional[str], Dict[str, Any]] = {}

    def _now(self) -> float:
        return time.time()

    def get_active_rules(self, tenant_id: Optional[str] = None, *, domain: Optional[str] = None) -> List[Dict[str, Any]]:
        """Return active rules for tenant (tenant-specific override + global rules).

        When `domain` is provided, only rules with matching `domain` are returned.
        """
        key = f"{tenant_id or '__global__'}::{domain or '__any__'}"
        cached = self._cache.get(key)
        if cached and (self._now() - cached.get('ts', 0) < self.cache_ttl):
            return cached.get('rules', [])

        # Load from DB: tenant-specific OR global (tenant_id IS NULL)
        try:
            with db_session() as db:
                rows = db.execute(
                    "SELECT id, tenant_id, domain, title, pattern, expression, priority, active, created_by, version, effective_from, effective_to, created_at FROM rule_definitions WHERE active = 1 AND (tenant_id IS NULL OR tenant_id = :tid) AND (:domain IS NULL OR domain = :domain) ORDER BY priority ASC",
                    {"tid": tenant_id, "domain": domain},
                ).fetchall()
        except Exception:
            return []

        rules: List[Dict[str, Any]] = []
        for r in rows or []:
            rules.append({
                "id": r[0],
                "tenant_id": r[1],
                "domain": r[2],
                "title": r[3],
                "pattern": r[4],
                "expression": r[5],
                "priority": int(r[6]) if r[6] is not None else 100,
                "active": bool(r[7]) if r[7] is not None else True,
                "created_by": r[8],
                "version": r[9],
                "effective_from": r[10],
                "effective_to": r[11],
                "created_at": r[12],
            })

        self._cache[key] = {"ts": self._now(), "rules": rules}
        return rules

    def refresh(self, tenant_id: Optional[str] = None, *, domain: Optional[str] = None) -> List[Dict[str, Any]]:
        """Force refresh cache for tenant/domain."""
        key = f"{tenant_id or '__global__'}::{domain or '__any__'}"
        if key in self._cache:
            del self._cache[key]
        return self.get_active_rules(tenant_id, domain=domain)

    def create_rule(self, rule: Dict[str, Any]) -> bool:
        """Insert a new rule definition. Expects keys: id, tenant_id, title, pattern, expression, priority, active, created_by, version."""
        try:
            with db_session() as db:
                db.execute(
                    "INSERT INTO rule_definitions (id, tenant_id, domain, title, pattern, expression, priority, active, created_by, version, effective_from, effective_to, created_at) VALUES (:id, :tenant_id, :domain, :title, :pattern, :expression, :priority, :active, :created_by, :version, :effective_from, :effective_to, CURRENT_TIMESTAMP)",
                    {
                        "id": rule.get("id"),
                        "tenant_id": rule.get("tenant_id"),
                        "domain": rule.get("domain"),
                        "title": rule.get("title"),
                        "pattern": rule.get("pattern"),
                        "expression": rule.get("expression"),
                        "priority": int(rule.get("priority") or 100),
                        "active": 1 if rule.get("active", True) else 0,
                        "created_by": rule.get("created_by"),
                        "version": rule.get("version"),
                        "effective_from": rule.get("effective_from"),
                        "effective_to": rule.get("effective_to"),
                    },
                )
                db.commit()
            # invalidate cache for tenant
            self._cache.clear()
            return True
        except Exception:
            return False

    def update_rule(self, rule_id: str, updates: Dict[str, Any]) -> bool:
        try:
            with db_session() as db:
                field_sql = {
                    "domain": "UPDATE rule_definitions SET domain = :v WHERE id = :id",
                    "title": "UPDATE rule_definitions SET title = :v WHERE id = :id",
                    "pattern": "UPDATE rule_definitions SET pattern = :v WHERE id = :id",
                    "expression": "UPDATE rule_definitions SET expression = :v WHERE id = :id",
                    "priority": "UPDATE rule_definitions SET priority = :v WHERE id = :id",
                    "active": "UPDATE rule_definitions SET active = :v WHERE id = :id",
                    "created_by": "UPDATE rule_definitions SET created_by = :v WHERE id = :id",
                    "version": "UPDATE rule_definitions SET version = :v WHERE id = :id",
                    "effective_from": "UPDATE rule_definitions SET effective_from = :v WHERE id = :id",
                    "effective_to": "UPDATE rule_definitions SET effective_to = :v WHERE id = :id",
                }
                touched = 0
                for k, v in (updates or {}).items():
                    stmt = field_sql.get(k)
                    if not stmt:
                        continue
                    if k == "priority":
                        try:
                            v = int(v)
                        except Exception:
                            pass
                    elif k == "active":
                        v = 1 if bool(v) else 0
                    db.execute(stmt, {"id": rule_id, "v": v})
                    touched += 1
                if touched == 0:
                    return False
                db.commit()
            # best-effort cache refresh for all tenants (simpler)
            self._cache.clear()
            return True
        except Exception:
            return False

    def delete_rule(self, rule_id: str) -> bool:
        try:
            with db_session() as db:
                db.execute("DELETE FROM rule_definitions WHERE id = :id", {"id": rule_id})
                db.commit()
            self._cache.clear()
            return True
        except Exception:
            return False

    def get_rule(self, rule_id: str) -> Optional[Dict[str, Any]]:
        try:
            with db_session() as db:
                r = db.execute(
                    "SELECT id, tenant_id, domain, title, pattern, expression, priority, active, created_by, version, effective_from, effective_to, created_at FROM rule_definitions WHERE id = :id",
                    {"id": rule_id},
                ).fetchone()
            if not r:
                return None
            return {
                "id": r[0],
                "tenant_id": r[1],
                "domain": r[2],
                "title": r[3],
                "pattern": r[4],
                "expression": r[5],
                "priority": int(r[6]) if r[6] is not None else 100,
                "active": bool(r[7]) if r[7] is not None else True,
                "created_by": r[8],
                "version": r[9],
                "effective_from": r[10],
                "effective_to": r[11],
                "created_at": r[12],
            }
        except Exception:
            return None
