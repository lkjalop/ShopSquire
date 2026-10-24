from __future__ import annotations

from typing import Dict, Optional

import os

from fastapi import APIRouter, HTTPException, Depends, Query
from src.app.models.db import get_db

from src.app.services.ollama_client import OllamaClient
from src.app.services.llm_guardrails import LLMGuardrails


router = APIRouter(prefix="/api/v1/demo", tags=["demo"])
from src.app.routers.portfolio_qualification import router as qualification_router
router.include_router(qualification_router)


def _ensure_demo_enabled() -> None:
    if str(os.getenv("ENABLE_DEMO_ROUTES", "0")).strip().lower() not in ("1", "true", "yes", "on"):
        raise HTTPException(status_code=404, detail="demo_routes_disabled")


@router.get('/electronics-shop')
def electronics_shop_demo(quantity: int = Query(default=30, ge=1, le=1000),
                          sku: str | None = None, db=Depends(get_db)):
    """Read-only, fixed-clock fixture replay; never current supplier availability."""
    _ensure_demo_enabled()
    from datetime import datetime
    from sqlalchemy import text
    from src.app.services.electronics_shop_scenario import assess_request, _scenario
    fixture = _scenario()
    rows = db.execute(text("""SELECT sku FROM price_book_entry WHERE tenant_id=:tenant
        AND source=:source AND channel='default' AND currency='AUD' ORDER BY sku"""),
        dict(tenant='synthetic-electronics',source='simulation:' + fixture['id'])).scalars().all()
    if not rows:
        raise HTTPException(status_code=409, detail='synthetic_shop_not_seeded')
    selected = sku or next((item for item in rows if item.startswith('LAP-')), rows[0])
    if selected not in rows:
        raise HTTPException(status_code=404, detail='scenario_sku_not_found')
    result = assess_request(db,tenant_id='synthetic-electronics',sku=selected,quantity=quantity,
                            now=datetime.fromisoformat(fixture['effective_from']))
    from src.app.services.shop_operational_history import replay_history
    history=replay_history(db,tenant_id='synthetic-electronics',sku=selected,scenario_id=fixture['id'])
    return dict(skus=rows, scenario_time=fixture['effective_from'], assessment=result,history=history)


@router.get("/llm_guardrails")
async def llm_guardrails_demo(prompt: str, expected_format: Optional[str] = "text") -> Dict:
    _ensure_demo_enabled()
    """Run a simple Ollama generation and validate with guardrails.

    Returns blocked/allowed with reason to demonstrate safe-agent behavior.
    """
    client = OllamaClient()
    rails = LLMGuardrails()

    # Try local Ollama; fall back to echoing the prompt if unavailable.
    text = prompt
    try:
        if await client.health():
            res = await client.generate(prompt=prompt)
            text = res.text or text
        else:
            text = prompt
    except Exception:
        text = prompt

    ok, reason, parsed = await rails.validate_output(text, expected_format or "text", context={})
    if not ok:
        # Blocked output demo
        return {
            "status": "blocked",
            "reason": reason,
            "expected_format": expected_format,
            "raw": text,
        }

    return {
        "status": "allowed",
        "expected_format": expected_format,
        "parsed": parsed,
    }
