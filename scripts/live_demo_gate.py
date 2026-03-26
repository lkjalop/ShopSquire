#!/usr/bin/env python3
"""Release gate for pre-recording and staging validation.

Runs fixed scenarios against a live ShopSquire API and verifies:
  Gate 1: critical dependencies are healthy
  Gate 2: no stub text leaks into recommend responses
  Gate 3: real return fixtures trigger multi-image mismatch fraud signal
  Gate 4: supply-chain scan creates a retrievable ticket
  Gate 5: budget question starts with a direct yes/no answer
"""
from __future__ import annotations

import argparse
import base64
import sys
import tempfile
import time
from pathlib import Path
from typing import Dict, List, Tuple

try:
    import requests
except ImportError:
    print("ERROR: requests not installed. Run: pip install requests")
    sys.exit(2)

PASS = "PASS"
FAIL = "FAIL"
WARN = "WARN"
_FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "images"


def _gate(name: str, passed: bool, detail: str = "") -> Dict:
    status = PASS if passed else FAIL
    print(f"  {status}  {name}" + (f" - {detail}" if detail else ""))
    return {"name": name, "passed": passed, "detail": detail}


def _get(session, base: str, path: str, **kwargs) -> requests.Response:
    return session.get(f"{base}{path}", timeout=10, **kwargs)


def _post(session, base: str, path: str, body: Dict, **kwargs) -> requests.Response:
    return session.post(f"{base}{path}", json=body, timeout=20, **kwargs)


def _fixture_b64(name: str) -> str:
    return base64.b64encode((_FIXTURE_ROOT / name).read_bytes()).decode()


_STUB_MARKERS = [
    "[anthropic stub response]",
    "[openai stub response]",
    "[mistral stub response]",
    "demo_label",
    "not_implemented",
    "placeholder",
]


def _has_stub(text: str) -> Tuple[bool, str]:
    lower = text.lower()
    for marker in _STUB_MARKERS:
        if marker.lower() in lower:
            return True, marker
    return False, ""


def check_health(session, base: str) -> List[Dict]:
    results = []
    print("\nGate 1 - Dependency Health")
    try:
        response = _get(session, base, "/api/v1/admin/integration-health")
        if response.status_code != 200:
            results.append(_gate("health endpoint reachable", False, f"HTTP {response.status_code}"))
            return results
        data = response.json()
        deps = data.get("dependencies") or {}
        overall = data.get("overall", "unknown")
        results.append(_gate("overall health", overall == "healthy", f"overall={overall}"))
        for dep_name in ("db", "redis"):
            dep = deps.get(dep_name) or {}
            status = dep.get("status", "unknown")
            latency = dep.get("latency_ms")
            detail = f"status={status}"
            if latency:
                detail += f", latency={latency}ms"
            results.append(_gate(f"dependency:{dep_name}", status == "healthy", detail))
        for dep_name in ("ollama", "pgvector"):
            dep = deps.get(dep_name) or {}
            print(f"  {WARN}  dependency:{dep_name} - status={dep.get('status', 'unknown')}")
    except Exception as exc:
        results.append(_gate("health endpoint reachable", False, str(exc)))
    return results


def check_no_stubs(session, base: str) -> List[Dict]:
    results = []
    print("\nGate 2 - No Stub Text in Responses")
    try:
        response = _post(session, base, "/api/v1/recommend", {"query": "show me a gaming laptop", "uid": "gate-check-user"})
        raw = response.text
        stub_found, marker = _has_stub(raw)
        results.append(
            _gate(
                "no stub markers in recommend response",
                not stub_found,
                f"found '{marker}'" if stub_found else f"HTTP {response.status_code}, {len(raw)} chars",
            )
        )
    except Exception as exc:
        results.append(_gate("recommend endpoint reachable", False, str(exc)))
    return results


def check_bad_return(session, base: str) -> List[Dict]:
    results = []
    print("\nGate 3 - Scenario A: Bad Return / Multi-Image Mismatch")
    try:
        body = {
            "uid": "gate-check-user",
            "sku": "LAPTOP-DELL-001",
            "description": "Screen cracked",
            "images": [
                {"filename": "return_ok_laptop.png", "b64": _fixture_b64("return_ok_laptop.png")},
                {"filename": "return_wrong_phone.png", "b64": _fixture_b64("return_wrong_phone.png")},
            ],
        }
        response = _post(session, base, "/api/v1/returns/submit", body)
        results.append(_gate("returns endpoint reachable", response.status_code < 500, f"HTTP {response.status_code}"))
        if response.status_code < 500:
            data = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
            signal_names = set()
            for signal in data.get("signals") or data.get("fraud_signals") or []:
                if isinstance(signal, dict):
                    signal_names.add(str(signal.get("signal") or signal.get("type") or ""))
                else:
                    signal_names.add(str(signal))
            results.append(
                _gate(
                    "return mismatch signal emitted",
                    "multi_image_mismatch" in signal_names,
                    f"signals={sorted(s for s in signal_names if s)[:6]}",
                )
            )
    except Exception as exc:
        results.append(_gate("returns/submit reachable", False, str(exc)))
    return results


def check_fraud_ring(session, base: str) -> List[Dict]:
    results = []
    print("\nGate 4 - Scenario B: Ticket Creation")
    try:
        before = _get(session, base, "/api/v1/tickets/")
        results.append(_gate("tickets endpoint reachable", before.status_code == 200, f"HTTP {before.status_code}"))
        if before.status_code == 200:
            before_count = len((before.json() or {}).get("tickets") or [])
            with tempfile.TemporaryDirectory() as tmp:
                Path(tmp, "requirements.txt").write_text("requests\njinja2\n", encoding="utf-8")
                scan = session.post(
                    f"{base}/api/v1/security/scan/supply-chain",
                    params={"repo_root": tmp, "create_tickets": "true"},
                    timeout=20,
                )
            results.append(_gate("supply-chain scan reachable", scan.status_code == 200, f"HTTP {scan.status_code}"))
            after = _get(session, base, "/api/v1/tickets/")
            after_count = len((after.json() or {}).get("tickets") or []) if after.status_code == 200 else before_count
            results.append(
                _gate(
                    "critical scan creates retrievable ticket",
                    after_count > before_count,
                    f"before={before_count} after={after_count}",
                )
            )
    except Exception as exc:
        results.append(_gate("tickets endpoint reachable", False, str(exc)))
    return results


def check_budget_question(session, base: str) -> List[Dict]:
    results = []
    print("\nGate 5 - Scenario C: Budget Question Direct Answer")
    try:
        response = _post(
            session,
            base,
            "/api/v1/recommend",
            {
                "query": "Is $1800 enough for a gaming laptop?",
                "uid": "gate-check-user",
                "context": {"budget_max": 1800, "use_case": "gaming"},
            },
        )
        results.append(_gate("recommend for budget question reachable", response.status_code < 500, f"HTTP {response.status_code}"))
        if response.status_code < 500:
            data = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
            msg = str(data.get("assistant_message") or data.get("message") or "").strip()
            first_word = msg.split()[0].lower().rstrip(".,!") if msg else ""
            stub_found, marker = _has_stub(msg)
            results.append(
                _gate(
                    "response starts with direct answer",
                    first_word in ("yes", "no") and not stub_found,
                    f"first_word='{first_word}' msg_preview='{msg[:80]}'",
                )
            )
            results.append(_gate("no stub text in budget response", not stub_found, f"found '{marker}'" if stub_found else "clean"))
    except Exception as exc:
        results.append(_gate("recommend/budget reachable", False, str(exc)))
    return results


def run_gate(base_url: str, api_key: str | None) -> bool:
    session = requests.Session()
    if api_key:
        session.headers["X-API-Key"] = api_key
        session.headers["Authorization"] = f"Bearer {api_key}"

    print("\n" + "=" * 60)
    print("  ShopSquire Release Gate")
    print(f"  Target: {base_url}")
    print(f"  Time:   {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}")
    print("=" * 60)

    all_results: List[Dict] = []
    all_results += check_health(session, base_url)
    all_results += check_no_stubs(session, base_url)
    all_results += check_bad_return(session, base_url)
    all_results += check_fraud_ring(session, base_url)
    all_results += check_budget_question(session, base_url)

    passed = sum(1 for result in all_results if result["passed"])
    total = len(all_results)
    failed = total - passed

    print("\n" + "=" * 60)
    print(f"  Result: {passed}/{total} checks passed")
    if failed:
        print("  FAILED CHECKS:")
        for result in all_results:
            if not result["passed"]:
                print(f"    x {result['name']}: {result['detail']}")
        print(f"\n  NOT READY - fix {failed} check(s) above")
    else:
        print("\n  ALL GATES PASSED - ready for staging recording")
    print("=" * 60 + "\n")
    return failed == 0


def main() -> None:
    parser = argparse.ArgumentParser(description="ShopSquire release gate checker")
    parser.add_argument("--base-url", default="http://localhost:8080", help="API base URL")
    parser.add_argument("--api-key", default=None, help="Owner or developer API key")
    args = parser.parse_args()
    sys.exit(0 if run_gate(args.base_url, args.api_key) else 1)


if __name__ == "__main__":
    main()
