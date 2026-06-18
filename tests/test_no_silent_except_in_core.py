"""Silent-except RATCHET — the observability boundary guard (P1 reliability).

A bare `except Exception: pass` (or `: continue`) swallows a failure with NO signal anywhere — not
in the response, not in the decision trace. That class is what hid the ASUS grounding bug for hours
(a stage failed, returned nothing, the request silently fell back to generic).

The fix is `services/safe_stage.safe_stage(...)` (or an inline `except ... as e: log_trace_event(
"stage_partial_failure", ...)`) so a degraded stage is AUDITABLE. There are ~227 legacy silent
swallows in recommend.py; converting all at once is infeasible, so this is a RATCHET: it records
the current count per module and FAILS if a module GROWS its silent-swallow count. Baselines only
ever move DOWN — every cleanup pass lowers them; new silent swallows cannot be merged.

Detection is AST-precise (an ExceptHandler whose only statement is `pass`/`continue`), so docstring
or comment mentions of "except: pass" are NOT counted.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

# Max allowed silent swallows per module. RATCHET DOWN ONLY — never raise a baseline to land a
# change; convert the swallow to safe_stage / a trace-visible except instead.
_BASELINE = {
    # the monster — the bulk of the legacy debt; shrinks as suggest() stages are extracted
    # and critical-path swallows are converted to safe_stage / trace-visible excepts.
    "src/app/routers/recommend.py": 226,
    # safe_stage's two inner guards (payload-merge + the trace sink) ARE the recorder — the one
    # place silence is legitimate.
    "src/app/services/safe_stage.py": 2,
    # extracted/owned core modules — kept tight so new silent swallows can't sneak in.
    "src/app/services/recommend_utils.py": 2,
    "src/app/services/recommend_budget_advisor.py": 6,
    "src/app/services/recommend_nqe_stage.py": 5,
    "src/app/services/checkout_handoff.py": 1,
    "src/app/services/grounding_ladder.py": 3,
    "src/app/services/recommend_image_hints.py": 3,
}


def _count_silent_excepts(path: str) -> int:
    p = Path(path)
    if not p.exists():
        return 0
    tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
    n = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler):
            # ignore a leading string-literal (docstring-style) statement, then check if the
            # remaining body is exactly one pass/continue.
            body = [
                s for s in node.body
                if not (isinstance(s, ast.Expr) and isinstance(getattr(s, "value", None), ast.Constant)
                        and isinstance(s.value.value, str))
            ]
            if len(body) == 1 and isinstance(body[0], (ast.Pass, ast.Continue)):
                n += 1
    return n


@pytest.mark.parametrize("module,limit", sorted(_BASELINE.items()))
def test_silent_except_does_not_grow(module, limit):
    n = _count_silent_excepts(module)
    assert n <= limit, (
        f"{module} has {n} silent `except: pass/continue` (baseline {limit}). A new silent swallow "
        f"was added — route it through services.safe_stage.safe_stage(...) or an inline "
        f"`except ... as e: log_trace_event('stage_partial_failure', ...)` so the failure is "
        f"visible in the decision trace. Do NOT raise the baseline."
    )


def test_ratchet_detects_a_silent_swallow(tmp_path):
    # Guard the guard: AST counter catches pass/continue but not an observable handler.
    f = tmp_path / "m.py"
    f.write_text(
        "try:\n    x()\nexcept Exception:\n    pass\n"
        "for i in []:\n    try:\n        y()\n    except ValueError:\n        continue\n"
        "try:\n    z()\nexcept Exception as e:\n    log(e)\n",
        encoding="utf-8",
    )
    assert _count_silent_excepts(str(f)) == 2  # the pass + the continue, not the logged handler
