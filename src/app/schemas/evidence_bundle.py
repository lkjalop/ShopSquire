from pydantic import BaseModel, Field, ConfigDict
from typing import Any, Dict, List, Optional

class EvidenceBundle(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    case_id: str
    bundle_json: Dict[str, Any] = Field(default_factory=dict)
    created_at: Optional[str] = None
