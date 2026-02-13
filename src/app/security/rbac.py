from __future__ import annotations

import os
import json
from typing import Dict


def _policy_path() -> str:
    return os.getenv("RBAC_POLICY_PATH", "config/security/rbac_policy.json")


def load_rbac_policy() -> Dict[str, any]:
    path = _policy_path()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def enforce_rbac(role: str, resource: str, action: str) -> bool:
    policy = load_rbac_policy()
    try:
        roles = policy.get("roles") or {}
        r = roles.get(role) or {}
        perms = r.get("permissions") or {}
        allowed_actions = perms.get(resource) or []
        return action in allowed_actions or "*" in allowed_actions
    except Exception:
        return False