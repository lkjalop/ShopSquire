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
    # A changed derivation policy invalidates the pinned scope just as changed
    # definitions do. Hashing a rule is not approval to execute that rule.
    snapshot = {"policy": policy, "derivations": raw.get("derivations") or [], "definitions": {
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


def accepted_requirement_gaps(claims, *, tenant_id: str, contract=None, now=None) -> list[str]:
    """Recheck completeness at fit time; unrelated identities cannot fill gaps."""
    gaps: set[str] = set()
    groups = {}
    if not claims:
        return ['manifest_scope_missing']
    for claim in claims:
        try:
            scope = RequirementScope.model_validate(claim.get('compilation_scope'))
        except ValueError:
            gaps.add('manifest_scope_missing')
            continue
        if scope.tenant_id != tenant_id or not scope_is_current(scope):
            gaps.add('manifest_scope_stale_or_mismatched')
            continue
        identity = str(claim.get('artefact_name') or '').strip()
        if not identity:
            gaps.add('requirement_identity_missing')
        key = (scope.model_dump_json(), identity, str(claim.get('artefact_version') or ''),
               str(claim.get('requirement_class') or 'minimum'), str(claim.get('condition') or ''))
        group = groups.setdefault(key, (scope, set()))
        if claim.get('authority_status') == 'verified_official':
            group[1].add(str(claim.get('attribute') or ''))
    if contract is not None:
        from src.app.services.requirement_contract import assess_contract_coverage
        coverage=assess_contract_coverage(contract,context=contract.context,claims=list(claims),now=now)
        if not coverage['coverage_complete']:
            gaps.add('selected_contract_incomplete')
    else:
        for scope, present in groups.values():
            if not scope.required_attributes:
                gaps.add('manifest_obligations_missing')
            gaps.update(set(scope.required_attributes) - present)
    return sorted(gaps)
