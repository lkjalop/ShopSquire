"""Pinned compilation scope. Source evidence never chooses its own manifest.

The existing attribute packs own definitions and use policies. This boundary
selects one pack, not a union of every installed category. Snapshots currently
use content revisions; durable manifest publication is a separate migration.
"""
from dataclasses import asdict
import hashlib
import json

from pydantic import BaseModel, ConfigDict, Field

from src.app.services import attribute_registry as registry


class RequirementScope(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    tenant_id: str = Field(min_length=1)
    product_type: str = Field(min_length=1)
    relationship: str = Field(min_length=1)
    manifest_id: str = Field(min_length=1)
    manifest_revision: str = Field(min_length=64, max_length=64)
    required_attributes: tuple[str, ...] = ()


def resolve_requirement_scope(*, tenant_id: str, profile_id: str,
                              product_type: str, relationship: str) -> RequirementScope | None:
    """Resolve server-selected context; no fallback for an unknown category.

    This does not authenticate a tenant or grant source authority. Callers must
    supply their request tenant and clamped product type, never provider fields.
    """
    if not str(tenant_id).strip() or profile_id not in registry.registered_verticals():
        return None
    try:
        raw = json.loads((registry._DATA_DIR / f"{profile_id}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    policy = raw.get("compilation") or {}
    if relationship not in policy.get("relationships", []):
        return None
    from src.app.services.taxonomy_registry import get_node
    if not get_node(product_type) or not any(
        product_type == root or product_type.startswith(root + "-")
        for root in policy.get("taxonomy_roots", [])
    ):
        return None
    definitions = registry.load_defs(profile_id)
    if not definitions:
        return None
    snapshot = {"policy": policy, "definitions": {
        key: asdict(value) for key, value in definitions.items()
    }}
    revision = hashlib.sha256(json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return RequirementScope(
        tenant_id=tenant_id, product_type=product_type, relationship=relationship,
        manifest_id=profile_id, manifest_revision=revision,
        required_attributes=tuple(policy.get("required_attributes") or ()),
    )


def scope_is_current(scope: RequirementScope) -> bool:
    current = resolve_requirement_scope(
        tenant_id=scope.tenant_id, profile_id=scope.manifest_id,
        product_type=scope.product_type, relationship=scope.relationship,
    )
    return current == scope
