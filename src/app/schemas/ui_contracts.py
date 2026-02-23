from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, ConfigDict


class BitemporalStamp(BaseModel):
    valid_from: Optional[str] = None
    valid_to: Optional[str] = None
    system_from: Optional[str] = None
    system_to: Optional[str] = None


class DecisionTraceEvent(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: Optional[str] = None
    seq: Optional[int] = None
    trace_id: Optional[str] = None
    event_type: Optional[str] = None
    source_type: Optional[str] = None
    source_id: Optional[str] = None
    target_type: Optional[str] = None
    target_id: Optional[str] = None
    payload: Dict[str, Any] = Field(default_factory=dict)
    created_at: Optional[str] = None


class DecisionTraceQueryResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    decision_id: Optional[str] = None
    timestamp: Optional[str] = None
    input_query: Optional[str] = None
    bitemporal: Optional[BitemporalStamp] = None
    events: List[DecisionTraceEvent] = Field(default_factory=list)
    evidence: Any = Field(default_factory=dict)


class IncidentEscalateResponse(BaseModel):
    ok: bool
    incident_id: str
    buyer_token: str
    staff_token: str
    ttl_seconds: int


class IncidentMessageResponse(BaseModel):
    sent: bool
    role: Optional[str] = None


class TransactionTimeseriesPoint(BaseModel):
    bucket: Optional[str] = None
    orders: int = 0
    revenue: float = 0.0
    paid: int = 0
    refunded: int = 0
    chargeback: int = 0
    pending_payment: int = 0


class TransactionTimeseriesTotals(BaseModel):
    orders: int = 0
    revenue: float = 0.0
    aov: float = 0.0
    paid: int = 0
    refunded: int = 0
    chargeback: int = 0
    pending_payment: int = 0


class TransactionTimeseriesResponse(BaseModel):
    granularity: str
    start: str
    end: str
    series: List[TransactionTimeseriesPoint] = Field(default_factory=list)
    totals: TransactionTimeseriesTotals
    source: Optional[str] = None
