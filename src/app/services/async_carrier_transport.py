"""Cancellation-aware carrier HTTP boundary with normalized outputs only."""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Literal
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, model_validator


class CarrierDeployment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider_id: str = Field(min_length=1, max_length=80)
    endpoint: str = Field(min_length=1, max_length=500)
    endpoint_identity: str = Field(min_length=1, max_length=240)
    enabled: bool = False

    @model_validator(mode="after")
    def exact_endpoint_identity(self) -> "CarrierDeployment":
        parsed = urlsplit(self.endpoint)
        if parsed.scheme != "https" or not parsed.hostname:
            raise ValueError("carrier_endpoint_must_be_https")
        if parsed.hostname.lower() != self.endpoint_identity.lower():
            raise ValueError("carrier_endpoint_identity_mismatch")
        return self


class CarrierRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation: Literal["create_label", "track", "quote"]
    request_id: str = Field(min_length=1, max_length=160)
    timeout_ms: int = Field(default=10_000, ge=100, le=30_000)
    payload: dict[str, Any] = Field(default_factory=dict)


@dataclass(frozen=True)
class CarrierResult:
    status: Literal["completed", "disabled", "timeout", "cancelled", "failed"]
    provider_id: str
    request_id: str
    normalized: dict[str, Any]
    elapsed_ms: int
    failure_code: str | None
    raw_provider_body_retained: Literal[False] = False


Normalize = Callable[[int, dict[str, Any]], dict[str, Any]]
Send = Callable[[CarrierDeployment, CarrierRequest], Awaitable[tuple[int, dict[str, Any]]]]


async def _send(deployment: CarrierDeployment, request: CarrierRequest) -> tuple[int, dict[str, Any]]:
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(request.timeout_ms / 1_000), follow_redirects=False,
    ) as client:
        response = await client.post(deployment.endpoint, json=request.payload)
        body = response.json() if response.headers.get("content-type", "").startswith(
            "application/json"
        ) else {}
        return response.status_code, body if isinstance(body, dict) else {}


async def execute_carrier_request(
    deployment: CarrierDeployment,
    request: CarrierRequest,
    *,
    normalize: Normalize,
    send: Send | None = None,
) -> CarrierResult:
    started = time.monotonic()

    def result(status: str, *, normalized: dict[str, Any] | None = None,
               failure: str | None = None) -> CarrierResult:
        return CarrierResult(
            status=status, provider_id=deployment.provider_id,
            request_id=request.request_id, normalized=normalized or {},
            elapsed_ms=round((time.monotonic() - started) * 1_000),
            failure_code=failure,
        )

    if not deployment.enabled:
        return result("disabled", failure="carrier_deployment_disabled")
    try:
        status_code, body = await asyncio.wait_for(
            (send or _send)(deployment, request), request.timeout_ms / 1_000,
        )
        normalized = normalize(status_code, body)
        if not isinstance(normalized, dict):
            raise TypeError("carrier_normalizer_must_return_mapping")
        return result("completed", normalized=normalized)
    except TimeoutError:
        return result("timeout", failure="carrier_deadline_exceeded")
    except asyncio.CancelledError:
        # Preserve cooperative cancellation; callers decide the HTTP response.
        raise
    except Exception as exc:
        return result("failed", failure=f"carrier_transport_failed:{type(exc).__name__}")


__all__ = [
    "CarrierDeployment", "CarrierRequest", "CarrierResult", "execute_carrier_request",
]
