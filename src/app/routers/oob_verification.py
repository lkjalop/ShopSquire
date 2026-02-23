"""OOB Verification router — create, confirm, deny, and query OOB requests.

Wired into main.py via ``include_router(router)``.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException

from src.app.schemas.oob_verification import (
    OOBConfirmRequest,
    OOBConfirmResponse,
    OOBCreateRequest,
    OOBCreateResponse,
    OOBStatusResponse,
)
from src.app.security.auth import require_role, ROLE_DEVELOPER, ROLE_OWNER
from src.app.security.oob_verification import (
    OOBChannel,
    confirm_verification,
    create_verification,
    deny_verification,
    get_verification,
    list_pending,
)

router = APIRouter(prefix="/api/v1/oob", tags=["oob-verification"])


@router.post("/create", response_model=OOBCreateResponse)
def create_oob(
    payload: OOBCreateRequest,
    role: str = Depends(require_role([ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    channel_map = {
        "sms": OOBChannel.SMS,
        "email": OOBChannel.EMAIL,
        "phone_call": OOBChannel.PHONE_CALL,
    }
    channel = channel_map.get(payload.channel, OOBChannel.EMAIL)
    result = create_verification(
        vendor_domain=payload.vendor_domain,
        trigger_signal=payload.trigger_signal,
        invoice_ref=payload.invoice_ref,
        amount=payload.amount,
        channel=channel,
        destination=payload.destination,
        context=payload.context,
        trace_id=payload.trace_id,
    )
    return result


@router.post("/confirm", response_model=OOBConfirmResponse)
def confirm_oob(
    payload: OOBConfirmRequest,
    role: str = Depends(require_role([ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    result = confirm_verification(payload.request_id, payload.token)
    return result


@router.post("/deny")
def deny_oob(
    request_id: str,
    role: str = Depends(require_role([ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    result = deny_verification(request_id)
    if not result.get("ok"):
        raise HTTPException(status_code=404, detail="Verification request not found")
    return result


@router.get("/status/{request_id}", response_model=OOBStatusResponse)
def oob_status(
    request_id: str,
    role: str = Depends(require_role([ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    record = get_verification(request_id)
    if not record:
        raise HTTPException(status_code=404, detail="Verification request not found")
    return record


@router.get("/pending")
def oob_pending(
    vendor_domain: Optional[str] = None,
    role: str = Depends(require_role([ROLE_OWNER, ROLE_DEVELOPER])),
) -> List[Dict[str, Any]]:
    return list_pending(vendor_domain)
