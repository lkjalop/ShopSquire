from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, ConfigDict


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LineItem(StrictModel):
    sku: str
    quantity: int


class DraftOrder(StrictModel):
    customer_id: Optional[str]
    line_items: List[LineItem]


class PricingProposal(StrictModel):
    cart_total_cents: int
    discount_percent: int
    reason: str
    proposal_id: str


class MedusaEvent(StrictModel):
    type: str
    data: Dict[str, Any]


class FeatureFlags(StrictModel):
    USE_AGENT_CAPABILITIES: bool = True
    AGENT_ROLLOUT_PERCENT: int = 20
    CAPABILITIES: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    KILL_SWITCH: bool = False


class SessionEvent(StrictModel):
    """Lightweight session-level event with privacy-safe fields.

    - uid: raw user identifier (hashed server-side)
    - session_id: client session identifier (hashed server-side)
    - device_id: client device identifier (hashed server-side)
    - action: event name (e.g., 'view', 'search', 'add_to_cart', 'return_request')
    - properties: arbitrary event properties (sanitized server-side)
    - ip: client IP (never stored raw; used for coarse GeoIP/ASN then discarded)
    - ts: ISO timestamp supplied by client; if missing, server will use current time
    """
    uid: Optional[str] = None
    session_id: Optional[str] = None
    device_id: Optional[str] = None
    action: str
    properties: Dict[str, Any] = Field(default_factory=dict)
    ip: Optional[str] = None
    ts: Optional[str] = None
