from pydantic import BaseModel, ConfigDict
from typing import Optional

class ReturnCase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    tenant_id: Optional[str] = None
    order_id: Optional[str] = None
    customer_id: Optional[str] = None
    guest_email: Optional[str] = None
    issue_type: Optional[str] = None
    description: Optional[str] = None
    status: str = "open"
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
