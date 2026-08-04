"""FAIL-OPEN RATCHET for the security / money surface (Track A, 2026-07-13).

The existing no-silent-except ratchet catches `except: pass/continue`. It does NOT catch the
fail-OPEN pattern that caused the Track-A bugs: a security/authorization/fraud/money decision
function that, on a DB/infra error, returns a FALSY value (False/None/0/[]/{}) — indistinguishable
from "all clear". Examples fixed: `_check_forced_reauth` returned False (flagged user let through),
`_is_https_request` returned False (Secure-cookie downgrade), `record_txn` returned None (lost
money event), fraud `check_phash` scored a DB outage as clean.

This ratchet is NARROW by design (to stay low-noise): it only flags an `except` handler whose body
is a single falsy `return`, AND only inside a function whose NAME signals a security decision. A
generic `except: return None` (cache miss, parse guard) is NOT flagged. New security-decision
fail-opens must fail CLOSED (return the safe/deny value) or fail LOUD (log + degrade), never silent.
"""
import ast
from pathlib import Path

import pytest

# security-decision function name markers (lowercased substring match)
_SECURITY_FN = ("reauth", "forced", "is_https", "check_phash", "verify", "authorize",
                "_authenticate", "authn", "integrity", "outbound_scan", "check_forced")

# files carrying auth / fraud / payment / outbound-security decisions
_FILES = (
    "src/app/routers/auth.py",
    "src/app/routers/fraud.py",
    "src/app/services/fraud_scorer.py",
    "src/app/services/payment_ledger.py",
    "src/app/services/fulfillment/external_comms.py",
)


def _is_falsy_return(stmt) -> bool:
    if not isinstance(stmt, ast.Return):
        return False
    v = stmt.value
    if v is None:
        return True
    if isinstance(v, ast.Constant) and v.value in (None, False, 0, ""):
        return True
    if isinstance(v, (ast.List, ast.Dict, ast.Tuple)):
        return not (getattr(v, "elts", None) or getattr(v, "keys", None))
    return False


def _fail_open_handlers_in_security_fns(path: str):
    p = Path(path)
    if not p.exists():
        return []
    tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
    hits = []
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not any(m in fn.name.lower() for m in _SECURITY_FN):
            continue
        for node in ast.walk(fn):
            if isinstance(node, ast.ExceptHandler):
                body = [s for s in node.body
                        if not (isinstance(s, ast.Expr) and isinstance(getattr(s, "value", None), ast.Constant)
                                and isinstance(s.value.value, str))]
                if len(body) == 1 and _is_falsy_return(body[0]):
                    hits.append(f"{fn.name}:{node.lineno}")
    return hits


@pytest.mark.parametrize("path", _FILES)
def test_no_fail_open_in_security_decision_functions(path):
    hits = _fail_open_handlers_in_security_fns(path)
    assert not hits, (
        f"{path}: a security-decision function fails OPEN — an `except` returns a falsy value on "
        f"error, so an infra failure reads as 'clean'. Fail CLOSED (return the deny/safe value) or "
        f"LOUD (log + degrade). Offenders: {hits}"
    )
