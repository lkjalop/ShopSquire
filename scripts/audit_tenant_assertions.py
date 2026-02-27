#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROUTERS = ROOT / "src" / "app" / "routers"

ROUTE_RE = re.compile(r"@router\.(get|post|put|patch|delete)\(\s*\"([^\"]+)\"")
TENANT_HINT_RE = re.compile(r"x-tenant-id|X-Tenant-Id|tenant_id|TenantQuotaGuard|scope_enforcement", re.IGNORECASE)
FUNC_RE = re.compile(r"^def\s+([a-zA-Z0-9_]+)\s*\(")


def main() -> int:
    report = []
    for p in ROUTERS.rglob("*.py"):
        rel = str(p.relative_to(ROOT)).replace("\\", "/")
        lines = p.read_text(encoding="utf-8", errors="ignore").splitlines()
        for i, line in enumerate(lines, start=1):
            m = ROUTE_RE.search(line)
            if not m:
                continue
            method = m.group(1).upper()
            route = m.group(2)
            window = "\n".join(lines[i - 1 : min(len(lines), i + 80)])
            has_tenant_assertion = bool(TENANT_HINT_RE.search(window))
            fn_name = None
            for j in range(i, min(len(lines), i + 20)):
                fm = FUNC_RE.search(lines[j])
                if fm:
                    fn_name = fm.group(1)
                    break
            report.append(
                {
                    "path": rel,
                    "line": i,
                    "method": method,
                    "route": route,
                    "function": fn_name,
                    "tenant_assertion_hint": has_tenant_assertion,
                }
            )

    flagged = [x for x in report if x["route"].startswith("/api/v1/") and not x["tenant_assertion_hint"]]
    print(
        json.dumps(
            {
                "routes_scanned": len(report),
                "tenant_assertion_missing_hints": len(flagged),
                "flagged": flagged,
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
