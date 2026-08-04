#!/usr/bin/env python
"""Determinism / order-dependence checker (P0 harness).

For each target test, runs it (a) ALONE in its own pytest process and (b) IN-SUITE
as part of its full test file, then reports any test whose verdict DIFFERS between
the two modes. A difference means the test depends on shared mutable state leaked by
another test (the bidirectional order-dependence we are eliminating).

CRITICAL anti-masking contract: a real bug must fail in BOTH modes. If the isolation
fixture makes a known-buggy test pass in-suite while it fails alone, that is masking,
and this script will flag it as a divergence (not silently "green").

Usage:
    python scripts/determinism_check.py tests/test_recommend.py::test_a [tests/...::test_b ...]

Exit code 0 = every target has a consistent verdict alone vs in-suite.
Exit code 1 = at least one target diverges (order-dependent / masked).
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from collections import defaultdict


def _run(targets: list[str]) -> dict[str, str]:
    """Run pytest on `targets`; return {('classname','name'): verdict}."""
    fd, xml_path = tempfile.mkstemp(suffix=".xml")
    os.close(fd)
    cmd = [
        sys.executable, "-m", "pytest", *targets,
        "-p", "no:randomly", "-p", "no:cacheprovider",
        "--tb=no", "-q", "--junitxml", xml_path,
    ]
    subprocess.run(cmd, capture_output=True, text=True)
    out: dict[str, str] = {}
    try:
        tree = ET.parse(xml_path)
        for tc in tree.iter("testcase"):
            key = f"{tc.get('classname')}::{tc.get('name')}"
            verdict = "pass"
            for child in tc:
                tag = child.tag.split("}")[-1]
                if tag == "failure":
                    verdict = "fail"
                elif tag == "error":
                    verdict = "error"
                elif tag == "skipped":
                    verdict = "skip"
            out[key] = verdict
    except Exception:
        pass
    finally:
        try:
            os.remove(xml_path)
        except Exception:
            pass
    return out


def _norm(test_id: str) -> str:
    """tests/test_recommend.py::test_x[p] -> tests.test_recommend::test_x[p]."""
    path, _, rest = test_id.partition("::")
    mod = path.replace("/", ".").replace("\\", ".")
    if mod.endswith(".py"):
        mod = mod[:-3]
    return f"{mod}::{rest}"


def main() -> int:
    targets = sys.argv[1:]
    if not targets:
        print("usage: determinism_check.py <test_id> [<test_id> ...]")
        return 2

    by_file: dict[str, list[str]] = defaultdict(list)
    for t in targets:
        by_file[t.split("::")[0]].append(t)

    divergent: list[tuple[str, str, str]] = []
    for test_file, tests in by_file.items():
        print(f"\n=== {test_file} ===")
        in_suite = _run([test_file])           # full file, in order
        for t in tests:
            alone = _run([t])                  # this test, isolated process
            key = _norm(t)
            v_alone = alone.get(key) or next(iter(alone.values()), "missing")
            v_suite = in_suite.get(key, "missing")
            mark = "OK " if v_alone == v_suite else "DIVERGES"
            print(f"  [{mark}] {t}\n           alone={v_alone}  in_suite={v_suite}")
            if v_alone != v_suite:
                divergent.append((t, v_alone, v_suite))

    print("\n" + "=" * 60)
    if divergent:
        print(f"FAIL: {len(divergent)} order-dependent test(s) — verdict changes with order:")
        for t, a, s in divergent:
            print(f"  {t}: alone={a} in_suite={s}")
        print("\nThis is either (a) a test leaking shared state, or (b) the isolation")
        print("fixture MASKING a real failure. Neither is acceptable — fix the root.")
        return 1
    print("PASS: all targets have a consistent verdict alone vs in-suite.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
