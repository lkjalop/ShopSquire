"""Authenticate an image proposal and namespace buyer-controlled artifact IDs."""
from dataclasses import dataclass
import json
import uuid

from fastapi import Depends, HTTPException, Query, Request

from src.app.security.auth import ROLE_DEVELOPER, ROLE_MERCHANT, ROLE_OWNER, require_role
from src.app.security.buyer_principal import (
    BuyerPrincipal,
    _session_subject,
    _verified_access_subject,
    resolve_buyer_principal,
)


@dataclass(frozen=True)
class ImageUploadActor:
    role: str
    buyer: BuyerPrincipal | None = None


def require_image_upload_actor(request: Request) -> ImageUploadActor:
    key=request.headers.get('x-api-key') or request.cookies.get('shopsquire_api_key')
    authorization=request.headers.get('authorization')
    if not key and (_verified_access_subject(request) or _session_subject(request)):
        buyer=resolve_buyer_principal(request,supplied_uid=request.query_params.get('uid'))
        if buyer is None or not buyer.verified:
            raise HTTPException(status_code=401,detail='verified_buyer_identity_required')
        tenant=str(request.headers.get('x-tenant-id') or 'default').strip() or 'default'
        if tenant!=buyer.tenant_id:
            raise HTTPException(status_code=403,detail='buyer_tenant_context_mismatch')
        return ImageUploadActor('buyer',buyer)
    role=require_role([ROLE_MERCHANT,ROLE_OWNER,ROLE_DEVELOPER])(
        x_api_key=key,authorization=authorization,request=request)
    return ImageUploadActor(role)


def image_upload_role(actor: ImageUploadActor = Depends(require_image_upload_actor)) -> str:
    return actor.role


def scoped_upload_artifact_id(
    artifact_id: str | None = Query(None,min_length=8,max_length=128),
    actor: ImageUploadActor = Depends(require_image_upload_actor),
) -> str | None:
    if actor.buyer is None:
        return artifact_id
    # Fast/full inspection of one client ID resolves to the same server ID.
    # Another buyer, tenant or supplied foreign ID cannot append to its history.
    identity=json.dumps(['buyer-image-v1',actor.buyer.tenant_id,actor.buyer.subject,
                         artifact_id or str(uuid.uuid4())],separators=(',',':'))
    return str(uuid.uuid5(uuid.NAMESPACE_URL,identity))
