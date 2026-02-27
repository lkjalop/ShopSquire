#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"


TEXT_CALL_RE = re.compile(r"\btext\s*\(")
PARAM_HINT_RE = re.compile(r"execute\s*\(\s*text\s*\(.*?\)\s*,\s*\{", re.DOTALL)


def main() -> int:
    findings = []
    for p in SRC.rglob("*.py"):
        rel = str(p.relative_to(ROOT)).replace("\\", "/")
        content = p.read_text(encoding="utf-8", errors="ignore")
        if "text(" not in content:
            continue
        lines = content.splitlines()
        for i, line in enumerate(lines, start=1):
            if TEXT_CALL_RE.search(line):
                nearby = "\n".join(lines[max(0, i - 1) : min(len(lines), i + 5)])
                parameterized = bool(PARAM_HINT_RE.search(nearby))
                findings.append(
                    {
                        "path": rel,
                        "line": i,
                        "parameterized_nearby": parameterized,
                        "snippet": line.strip()[:200],
                    }
                )

    out = {
        "total_text_calls": len(findings),
        "needs_review": [f for f in findings if not f.get("parameterized_nearby")],
        "findings": findings,
    }
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
