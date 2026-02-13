from pydantic import BaseModel, Field
from typing import Any, Dict, List, Optional

class EvidenceBundle(BaseModel):
    id: str
    case_id: str
    bundle_json: Dict[str, Any] = Field(default_factory=dict)
    created_at: Optional[str] = None
