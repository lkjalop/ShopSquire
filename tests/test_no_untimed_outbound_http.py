"""Ratchet: no outbound HTTP call may omit an explicit timeout.

A `requests`/`httpx` call (or an httpx Client/AsyncClient constructed) without a `timeout` can hang a
worker or request thread indefinitely on a slow/dead endpoint — a silent hang. The whole codebase
currently passes timeouts everywhere (baseline 0); this AST ratchet keeps it that way. New call sites
should pass timeout=src.app.services.http_defaults.DEFAULT_OUTBOUND_TIMEOUT (env OUTBOUND_HTTP_TIMEOUT_SEC).

AST-based (not a line grep) so multi-line calls with timeout on a continuation line are correctly
recognised as compliant.
"""
from __future__ import annotations

import ast
import pathlib

_HTTP_METHODS = {"get", "post", "put", "delete", "patch", "request", "head", "options"}
_CLIENTS = {"requests", "httpx"}
_SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "app"


def _root_name(value: ast.AST):
    if isinstance(value, ast.Name):
        return value.id
    if isinstance(value, ast.Attribute):
        return value.attr
    return None


def _offenders():
    bad = []
    for p in _SRC.rglob("*.py"):
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            attr = node.func.attr
            kw = {k.arg for k in node.keywords if k.arg}
            # requests.get(...) / httpx.post(...) style verbs
            if attr in _HTTP_METHODS and _root_name(node.func.value) in _CLIENTS:
                if "timeout" not in kw:
                    bad.append(f"{p.relative_to(_SRC.parent.parent)}:{node.lineno} {attr}()")
            # httpx.Client(...) / httpx.AsyncClient(...) constructors
            elif attr in ("Client", "AsyncClient") and _root_name(node.func.value) == "httpx":
                if "timeout" not in kw:
                    bad.append(f"{p.relative_to(_SRC.parent.parent)}:{node.lineno} httpx.{attr}()")
    return sorted(set(bad))


def test_no_outbound_http_without_timeout():
    bad = _offenders()
    assert not bad, (
        "Outbound HTTP call(s) without an explicit timeout (silent-hang risk) — add "
        "timeout=DEFAULT_OUTBOUND_TIMEOUT (src.app.services.http_defaults):\n  " + "\n  ".join(bad)
    )
