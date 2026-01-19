from fastapi import APIRouter, Depends, HTTPException
from typing import Dict
import hashlib

from src.app.deps import get_redis
from src.app.security.firewall import TransactionFirewall
from src.app.services.memory import Memory
from src.app.services.orchestrator import Orchestrator
from src.app.config import load_feature_flags, get_settings
import time
from src.app.observability.metrics import record_pricing_latency
import os
from src.app.analytics.anomaly import ewma, is_anomaly
from src.app.observability.metrics import record_incident_alert


router = APIRouter(prefix="/api/v1/pricing", tags=["pricing"])


@router.get("/suggest")
def suggest(uid: str, cart_total_cents: int, sku: str | None = None, idempotency_key: str | None = None, redis=Depends(get_redis)) -> Dict:
    flags = load_feature_flags(get_settings().feature_flags_path)
    if flags.get("KILL_SWITCH"):
        raise HTTPException(status_code=503, detail="Agent disabled by kill switch")

    cap = flags.get("CAPABILITIES", {}).get("pricing", {"enabled": True, "rollout_percent": flags.get("AGENT_ROLLOUT_PERCENT", 20)})
    if not cap.get("enabled", True):
        raise HTTPException(status_code=503, detail="Pricing capability disabled")
    rollout = int(cap.get("rollout_percent", flags.get("AGENT_ROLLOUT_PERCENT", 20)))
    cohort = int(hashlib.sha256(uid.encode("utf-8")).hexdigest(), 16) % 100
    mem = Memory(redis)
    fw = TransactionFirewall(flags)
    orch = Orchestrator(mem, fw, flags)
    simulate = cohort >= rollout

    start = time.time()
    result = orch.run(
        uid,
        {"cart_total_cents": cart_total_cents, "sku": sku, "idempotency_key": idempotency_key},
        simulate_only=simulate,
    )
    elapsed = time.time() - start
    record_pricing_latency(elapsed)
    # EWMA-based anomaly guard using session KV memory
    ctx = mem.get_context(uid)
    kv = ctx.get("kv") or {}
    lat_series = kv.get("latency_series", [])
    lat_series = (lat_series + [elapsed])[-50:]
    kv["latency_series"] = lat_series
    mem.set_kv(uid, kv)
    baseline = ewma(lat_series, 0.2)
    if is_anomaly(elapsed, lat_series, 0.2, 3.0):
        record_incident_alert("performance", "p2")
    payload = {
        "eligible": not simulate,
        "message": None if not simulate else "User not in rollout cohort",
        "proposal": result.proposal,
        "firewall": result.firewall,
        "executed": result.executed,
        "latency_baseline": baseline,
    }
    if os.getenv("SHOW_INTERNAL_TIMINGS", "false").lower() in ("1", "true", "yes"):
        payload["timings"] = getattr(result, "timings", None)
    return payload
