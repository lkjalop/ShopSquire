from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class LineItem(BaseModel):
    sku: str
    quantity: int


class DraftOrder(BaseModel):
    customer_id: Optional[str]
    line_items: List[LineItem]


class PricingProposal(BaseModel):
    cart_total_cents: int
    discount_percent: int
    reason: str
    proposal_id: str


class MedusaEvent(BaseModel):
    type: str
    data: Dict[str, Any]


class FeatureFlags(BaseModel):
    USE_AGENT_CAPABILITIES: bool = True
    AGENT_ROLLOUT_PERCENT: int = 20
    CAPABILITIES: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    KILL_SWITCH: bool = False
