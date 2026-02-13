from __future__ import annotations

from typing import Dict, Any

from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="ShopSquire Tool Bridge")


class ToolRequest(BaseModel):
    tool: str
    params: Dict[str, Any] | None = None


@app.post("/tools/run")
def run_tool(req: ToolRequest) -> Dict[str, Any]:
    params = req.params or {}
    if req.tool == "catalog.search":
        query = str(params.get("query") or "")
        return {
            "results": [
                {"sku": "DEMO-001", "name": f"{query} Pro 14", "price_cents": 199900},
                {"sku": "DEMO-002", "name": f"{query} Air 13", "price_cents": 129900},
            ]
        }
    if req.tool == "inventory.check":
        return {"sku": params.get("sku"), "stock": 8}
    if req.tool == "shipping.quote":
        subtotal = int(params.get("subtotal_cents") or 0)
        return {"carrier": "UPS", "service": "2-day", "cost_cents": max(799, int(subtotal * 0.05)), "eta_days": 2}
    return {"error": "unknown_tool"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=9001)
