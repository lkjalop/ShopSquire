"""Pydantic schemas for OOB verification endpoints."""
from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field, ConfigDict


class OOBCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    vendor_domain: str = Field(..., description="Vendor domain that triggered the bank-change signal")
    trigger_signal: str = Field(..., description="Signal type that triggered OOB (e.g. bank_fingerprint_baseline_mismatch)")
    invoice_ref: str = ""
    amount: str = ""
    channel: str = Field("email", description="Delivery channel: sms | email | phone_call")
    destination: str = Field("", description="Phone number or email for delivery")
    trace_id: str = ""
    context: Optional[Dict[str, Any]] = None


class OOBCreateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: str
    status: str
    channel: str
    expires_at: float
    token: str = Field(..., description="One-time token to relay via the chosen channel")


class OOBConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: str
    token: str


class OOBConfirmResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ok: bool
    status: Optional[str] = None
    error: Optional[str] = None
    request_id: Optional[str] = None
    attempts_remaining: Optional[int] = None


class OOBStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: str
    vendor_domain: str
    trigger_signal: str
    status: str
    channel: str
    created_at: float
    expires_at: float
    trace_id: str = ""
