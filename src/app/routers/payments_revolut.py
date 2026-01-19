from typing import Dict, Optional

from fastapi import APIRouter, HTTPException

from src.app.security.pci import contains_pci_data
from src.app.config import load_feature_flags, get_settings

router = APIRouter(prefix="/api/v1/payments/revolut", tags=["payments-revolut"])


@router.post("/intent")
def create_intent(uid: str, amount_cents: int, idempotency_key: Optional[str] = None, description: Optional[str] = None) -> Dict:
    flags = load_feature_flags(get_settings().feature_flags_path)
    cap = flags.get("CAPABILITIES", {}).get("revolut", {"enabled": False})
    if not cap.get("enabled"):
        raise HTTPException(status_code=503, detail="Revolut disabled by feature flags")
    if contains_pci_data(description or ""):
        raise HTTPException(status_code=400, detail="PCI-DSS sensitive data detected")
    return {
        "provider": "revolut",
        "intent_id": f"rv_{uid}_{amount_cents}",
        "idempotency_key": idempotency_key,
        "status": "created",
    }
