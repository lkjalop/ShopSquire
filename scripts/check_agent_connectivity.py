#!/usr/bin/env python3
"""Agent connectivity verification script for local dev.

Run: python scripts/check_agent_connectivity.py
"""
import asyncio
import httpx
import sys


import os

BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1:8081")

# Which endpoints should use merchant vs owner API key
HEALTH_CHECKS = [
    ("Health", "GET", "/health", None),
    ("Orchestrator", "POST", "/api/v1/orchestrate", "merchant"),
    ("Inventory Alerts", "GET", "/api/v1/inventory/alerts", "merchant"),
    ("Decision Trace", "GET", "/api/v1/decisions/test-trace-id", "merchant"),
    ("Fraud Score", "POST", "/api/v1/fraud/score", "merchant"),
    ("CV Analyze", "POST", "/api/v1/cv/analyze", "merchant"),
]

MERCHANT_KEY = os.getenv("MERCHANT_API_KEY")
OWNER_KEY = os.getenv("OWNER_API_KEY")

async def check_endpoint(client: httpx.AsyncClient, name: str, method: str, path: str, key_type: str) -> dict:
    try:
        url = f"{BASE_URL}{path}"
        headers = {}
        if key_type == "merchant" and MERCHANT_KEY:
            headers["x-api-key"] = MERCHANT_KEY
        if key_type == "owner" and OWNER_KEY:
            headers["x-api-key"] = OWNER_KEY

        if method == "GET":
            r = await client.get(url, timeout=5.0, headers=headers)
        else:
            r = await client.post(url, json={}, timeout=5.0, headers=headers)
        status = "OK" if r.status_code < 500 else "ERROR"
        return {"name": name, "status": status, "code": r.status_code, "url": url}
    except httpx.ConnectError:
        return {"name": name, "status": "UNREACHABLE", "code": None, "url": url}
    except Exception as e:
        return {"name": name, "status": "ERROR", "code": str(e), "url": url}


async def main():
    async with httpx.AsyncClient() as client:
        results = await asyncio.gather(*[
            check_endpoint(client, name, method, path, key_type)
            for name, method, path, key_type in HEALTH_CHECKS
        ])

    print("\n=== Agent Connectivity Report ===\n")
    all_ok = True
    for r in results:
        icon = "✓" if r["status"] == "OK" else "✗"
        print(f"  {icon} {r['name']}: {r['status']} (HTTP {r['code']}) -> {r['url']}")
        if r["status"] != "OK":
            all_ok = False

    print("\n" + ("All agents reachable!" if all_ok else "Some agents unreachable - check server logs"))
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
#!/usr/bin/env python3
"""Agent connectivity verification script.

Run this BEFORE implementing changes to verify all agents respond.

Usage:
    python scripts/check_agent_connectivity.py

Expected output: All agents should show OK or 4xx (route exists).
5xx or UNREACHABLE indicates a problem.
"""

import asyncio
import sys
from typing import Dict, List, Tuple

try:
    import httpx
except ImportError:
    print("httpx not installed. Run: pip install httpx")
    sys.exit(1)


BASE_URL = "http://localhost:8000"

HEALTH_CHECKS: List[Tuple[str, str, str, Dict]] = [
    # (name, method, path, body)
    ("Health", "GET", "/api/v1/health", {}),
    ("Orchestrator", "POST", "/api/v1/orchestrate", {"cart_total_cents": 1000}),
    ("Inventory Alerts", "GET", "/api/v1/inventory/alerts", {}),
    ("Decision Trace", "GET", "/api/v1/trace/test-id/events", {}),
    ("Decisions API", "GET", "/api/v1/decisions/test-id", {}),
    ("Fraud Score", "POST", "/api/v1/fraud/score", {"signals": {}}),
    ("CV Analyze", "POST", "/api/v1/cv/analyze", {}),
    ("Recommendations", "POST", "/api/v1/recommendations", {"query": "test"}),
    ("Products", "GET", "/api/v1/products", {}),
    ("Security Observer", "GET", "/api/v1/security/status", {}),
]


async def check_endpoint(
    client: httpx.AsyncClient,
    name: str,
    method: str,
    path: str,
    body: Dict,
) -> Dict:
    """Check if endpoint responds (even with 4xx is OK - means route exists)."""
    try:
        headers = {"x-api-key": "local-merchant-key", "Content-Type": "application/json"}
        if method == "GET":
            r = await client.get(f"{BASE_URL}{path}", headers=headers, timeout=5.0)
        else:
            r = await client.post(f"{BASE_URL}{path}", json=body, headers=headers, timeout=5.0)
        # 2xx, 4xx means endpoint exists; 5xx or timeout means issue
        if r.status_code < 500:
            status = "OK"
        else:
            status = "ERROR"
            try:
                detail = r.json().get("detail", "")[:50]
            except:
                detail = r.text[:50]
            return {"name": name, "status": status, "code": r.status_code, "detail": detail}
        return {"name": name, "status": status, "code": r.status_code}
    except httpx.ConnectError:
        return {"name": name, "status": "UNREACHABLE", "code": None, "detail": "Connection refused"}
    except httpx.TimeoutException:
        return {"name": name, "status": "TIMEOUT", "code": None, "detail": "Request timed out"}
    except Exception as e:
        return {"name": name, "status": "ERROR", "code": None, "detail": str(e)[:50]}


async def check_cors():
    """Test CORS preflight."""
    async with httpx.AsyncClient() as client:
        try:
            r = await client.options(
                f"{BASE_URL}/api/v1/health",
                headers={
                    "Origin": "http://localhost:5173",
                    "Access-Control-Request-Method": "GET",
                },
                timeout=5.0,
            )
            cors_origin = r.headers.get("access-control-allow-origin", "")
            cors_creds = r.headers.get("access-control-allow-credentials", "")
            return {
                "status": "OK" if cors_origin else "MISSING",
                "allow_origin": cors_origin,
                "allow_credentials": cors_creds,
            }
        except Exception as e:
            return {"status": "ERROR", "detail": str(e)}


async def main():
    print("\n" + "=" * 60)
    print("  ShopSquire Agent Connectivity Report")
    print("=" * 60 + "\n")

    # Check CORS first
    print("CORS Configuration:")
    cors = await check_cors()
    if cors["status"] == "OK":
        print(f"  [OK] allow-origin: {cors.get('allow_origin')}")
        print(f"       allow-credentials: {cors.get('allow_credentials')}")
    else:
        print(f"  [WARN] CORS may not be configured: {cors}")
    print()

    # Check all endpoints
    print("Agent Endpoints:")
    async with httpx.AsyncClient() as client:
        results = await asyncio.gather(
            *[check_endpoint(client, name, method, path, body) for name, method, path, body in HEALTH_CHECKS]
        )

    all_ok = True
    for r in results:
        if r["status"] == "OK":
            icon = "[OK]"
        elif r["status"] in ("UNREACHABLE", "TIMEOUT"):
            icon = "[!!]"
            all_ok = False
        else:
            icon = "[??]"
            all_ok = False

        line = f"  {icon} {r['name']}: {r['status']}"
        if r.get("code"):
            line += f" (HTTP {r['code']})"
        if r.get("detail"):
            line += f" - {r['detail']}"
        print(line)

    print()
    print("-" * 60)
    if all_ok:
        print("All agents reachable! Ready for implementation.")
        return 0
    else:
        print("Some agents unreachable. Check if server is running:")
        print("  uvicorn src.app.main:app --reload --port 8000")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
