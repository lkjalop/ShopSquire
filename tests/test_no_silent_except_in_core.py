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
    # and critical-path swallows are converted to safe_stage / record_partial_failure. 2026-06-24:
    # tightened 226→190 (true current count) after converting the security-emit + 2 memory-writeback
    # swallows to observable record_partial_failure (error-budget Tier 1). 2026-06-27: 190→183 after
    # extracting the inventory + bulk-shortfall handoff block to recommend_inventory_handoff_stage.
    "src/app/routers/recommend.py": 183,
    # inventory + bulk-shortfall handoff (extracted): the 4 swallows are best-effort trace/telemetry
    # guards moved verbatim; locked so no NEW silent swallow can land in the extracted stage.
    "src/app/services/recommend_inventory_handoff_stage.py": 4,
    # safe_stage's two inner guards (payload-merge + the trace sink) ARE the recorder — the one
    # place silence is legitimate.
    "src/app/services/safe_stage.py": 2,
    # V2 recommendation_core — ENROLLED 2026-07-12 at 0 (all clean): the greenfield replacement
    # for suggest() is now under the ratchet from the start, so it can NEVER accrue the legacy
    # 183-swallow debt. Every degradation in these modules is logged (record_partial_failure /
    # logger.warning), never a bare except: pass.
    "src/app/services/recommendation_core/core.py": 0,
    "src/app/services/recommendation_core/evidence.py": 0,
    "src/app/services/recommendation_core/fit.py": 0,
    "src/app/services/recommendation_core/gates.py": 0,
    "src/app/services/recommendation_core/plan.py": 0,
    "src/app/services/recommendation_core/ranking.py": 0,
    "src/app/services/recommendation_core/envelope.py": 0,
    "src/app/services/recommendation_core/legacy_adapter.py": 0,
    "src/app/services/recommendation_core/intent_resolver.py": 0,
    "src/app/services/recommendation_core/turn_router.py": 0,
    "src/app/services/recommendation_core/cart_resolver.py": 0,
    # C1 cart-mutation boundary: typed contract + transactional service + apply endpoint —
    # a financial mutation path is exactly where silence must be impossible.
    "src/app/domain/cart_mutation.py": 0,
    "src/app/services/cart_mutation_service.py": 0,
    "src/app/routers/cart_mutations.py": 0,
    "src/app/services/recommendation_facade.py": 0,
    "src/app/services/recommendation_postflight.py": 0,
    # extracted/owned core modules — kept tight so new silent swallows can't sneak in.
    "src/app/services/recommend_utils.py": 2,
    "src/app/services/recommend_budget_advisor.py": 6,
    "src/app/services/recommend_nqe_stage.py": 5,
    "src/app/services/checkout_handoff.py": 1,
    "src/app/services/grounding_ladder.py": 3,
    "src/app/services/recommend_image_hints.py": 3,
    # adaptive-growth core (market-intel / hippograph / experiments / governance) — locked at their
    # current counts so no NEW silent swallow can land. Most are 0 (they use observable
    # `except Exception: return X`); the few >0 are best-effort commit/telemetry guards.
    "src/app/services/market_signal.py": 0,
    "src/app/services/market_signal_adapters.py": 0,
    "src/app/services/market_analysis.py": 0,
    "src/app/services/market_intelligence_agent.py": 0,
    "src/app/services/recommend_intelligence_stage.py": 0,
    "src/app/services/human_feedback.py": 0,
    "src/app/services/shadow_actions.py": 1,
    "src/app/services/contact_governance.py": 2,
    "src/app/services/campaign_governance.py": 0,
    "src/app/services/experiments.py": 0,
    "src/app/services/experiment_eval.py": 0,
    "src/app/services/experiment_console.py": 0,
    "src/app/services/experiment_ops.py": 2,
    "src/app/services/ranking_nudge.py": 0,
    "src/app/services/template_phrasing.py": 0,
    "src/app/services/hippograph.py": 0,
    "src/app/services/hippograph_db.py": 0,
    "src/app/services/hippograph_feedback.py": 0,
    "src/app/services/adaptive_action_gate.py": 0,
    "src/app/services/fulfillment/domain.py": 0,
    "src/app/services/fulfillment/repository.py": 0,
    "src/app/services/fulfillment/workflow.py": 0,
    "src/app/services/fulfillment/draft.py": 0,
    "src/app/services/fulfillment/rfq_fanout.py": 0,
    "src/app/services/fulfillment/external_comms.py": 0,
    "src/app/services/fulfillment/sandbox_supplier.py": 0,
    "src/app/services/fulfillment/transport.py": 0,
    "src/app/services/fulfillment/po_transport.py": 0,
    "src/app/services/fulfillment/options.py": 0,
    "src/app/services/fulfillment/purchase_order.py": 0,
    "src/app/services/fulfillment/economics.py": 0,
    "src/app/services/commerce_catalog.py": 0,
    "src/app/services/inventory_source.py": 0,
    "src/app/services/supplier_inbox_reader.py": 0,
    "src/app/services/catalog_entities.py": 0,
    "src/app/services/shopify_catalog_adapter.py": 0,
    "src/app/services/magento_catalog_adapter.py": 0,
    "src/app/services/recommend_fulfillment_stage.py": 0,
    "src/app/services/market_replay.py": 0,
    "src/app/services/market_pipeline.py": 0,
    "src/app/services/market_warehouse.py": 0,
    "src/app/services/competitor_source.py": 0,
    "src/app/services/support_objection_source.py": 0,
    "src/app/services/funnel_source.py": 0,
    "src/app/services/supplier_catalog.py": 0,
    "src/app/services/async_safe.py": 0,
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
