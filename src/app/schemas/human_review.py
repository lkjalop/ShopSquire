from pydantic import BaseModel
from typing import Optional

class HumanReviewTask(BaseModel):
    id: str
    case_id: str
    decision_id: Optional[str] = None
    ticket_id: Optional[str] = None
    status: str = "pending"
    reviewer_id: Optional[str] = None
    rationale: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
