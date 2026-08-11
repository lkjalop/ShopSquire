from __future__ import annotations

from typing import Dict, Any

import hmac
import os

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, ConfigDict

from src.app.services.registry import get_tool_contract_fingerprint

app = FastAPI(title="ShopSquire Tool Bridge")


class ToolRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tool: str
    params: Dict[str, Any] | None = None
    tenant_id: str | None = None
    trace_id: str | None = None
    contract_hash: str | None = None


@app.post("/tools/run")
def run_tool(req: ToolRequest, authorization: str | None = Header(default=None)) -> Dict[str, Any]:
    expected_token = str(os.getenv("TOOL_BRIDGE_TOKEN", "") or "").strip()
    strict = str(os.getenv("TOOL_BRIDGE_AUTH_ENFORCE", "0")).lower() in {"1", "true", "yes", "on"}
    if strict and not expected_token:
        raise HTTPException(status_code=503, detail="tool_bridge_identity_not_configured")
    if expected_token and not hmac.compare_digest(str(authorization or ""), f"Bearer {expected_token}"):
        raise HTTPException(status_code=401, detail="invalid_tool_bridge_identity")
    expected_contract = get_tool_contract_fingerprint(req.tool)
    if req.contract_hash and not hmac.compare_digest(req.contract_hash, expected_contract):
        raise HTTPException(status_code=409, detail="tool_contract_mismatch")
    params = req.params or {}
    if req.tool == "catalog.search":
        query = str(params.get("query") or "")
        return {
            "_tool_contract_hash": expected_contract,
            "results": [
                {"sku": "DEMO-001", "name": f"{query} Pro 14", "price_cents": 199900},
                {"sku": "DEMO-002", "name": f"{query} Air 13", "price_cents": 129900},
            ]
        }
    if req.tool == "inventory.check":
        return {"_tool_contract_hash": expected_contract, "sku": params.get("sku"), "stock": 8}
    if req.tool == "shipping.quote":
        subtotal = int(params.get("subtotal_cents") or 0)
        return {"_tool_contract_hash": expected_contract, "carrier": "UPS", "service": "2-day", "cost_cents": max(799, int(subtotal * 0.05)), "eta_days": 2}
    return {"_tool_contract_hash": expected_contract, "error": "unknown_tool"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=os.getenv("TOOL_BRIDGE_BIND", "127.0.0.1"), port=9001)
