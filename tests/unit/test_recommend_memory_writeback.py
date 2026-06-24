"""Tests for recommend_memory_writeback — extracted memory persistence functions."""
import time
from unittest.mock import MagicMock, patch

import pytest

from src.app.services.recommend_memory_writeback import (
    build_envelope_snapshot,
    build_rolling_summary,
    persist_turn_state,
    update_pinned_context,
    TurnPersistenceInput,
    TurnPersistenceHooks,
)


class TestBuildEnvelopeSnapshot:
    def test_basic(self):
        snap = build_envelope_snapshot(
            constraints={"budget_min": 500, "budget_max": 1500, "brands": ["ASUS"], "specs": ["16GB"]},
            candidates_count=40,
            results_count=4,
            shortlist_locked=False,
            shortlist_size=4,
        )
        assert snap["budget_min"] == 500
        assert snap["budget_max"] == 1500
        assert snap["brands"] == ["ASUS"]
        assert snap["candidates_count"] == 40
        assert snap["results_count"] == 4
        assert snap["shortlist_locked"] is False

    def test_empty_constraints(self):
        snap = build_envelope_snapshot(
            constraints={}, candidates_count=0, results_count=0,
            shortlist_locked=False, shortlist_size=0,
        )
        assert snap["budget_min"] is None
        assert snap["brands"] == []


class TestUpdatePinnedContext:
    def test_pins_budget_and_use_case(self):
        kv: dict = {}
        result = update_pinned_context(
            kv=kv,
            constraints={"budget_min": 1000, "budget_max": 2000, "use_case": "gaming"},
            shortlist_skus=["SKU1", "SKU2"],
            turn_type="result_turn",
            ts=1000000,
        )
        pinned = result["pinned_context"]
        assert pinned["budget"]["value"] == {"min": 1000, "max": 2000}
        assert pinned["use_case"]["value"] == "gaming"
        assert pinned["selected_skus"]["value"] == ["SKU1", "SKU2"]
        assert pinned["budget"]["ts"] == 1000000

    def test_skips_none_values(self):
        kv: dict = {}
        result = update_pinned_context(
            kv=kv,
            constraints={"budget_min": None, "budget_max": None},
            shortlist_skus=None,
            turn_type="result_turn",
        )
        pinned = result["pinned_context"]
        # budget is pinned (dict value with None min/max), but use_case/gpu not pinned
        assert "use_case" not in pinned
        assert "gpu_preference" not in pinned


class TestBuildRollingSummary:
    def test_summary_shape(self):
        s = build_rolling_summary(
            kv={"pinned_context": {"budget": {"value": {"min": 1000, "max": 2000}}}},
            constraints={"budget_min": 1000, "budget_max": 2000, "use_case": "gaming", "brands": ["HP"]},
            results=[{"sku": "A"}, {"sku": "B"}],
            next_questions=[{"id": "q1", "text": "What specs?"}],
            turn_type="result_turn",
            referents={"has_reference": False, "source": "none", "skus": []},
        )
        assert s["turn_type"] == "result_turn"
        assert "gaming" in s["goals"]
        assert s["hard_constraints"]["budget_min"] == 1000
        assert s["current_shortlist"] == ["A", "B"]
        assert s["unresolved_questions"] == ["What specs?"]


class TestPersistTurnState:
    def _make_mem(self):
        mem = MagicMock()
        mem.get_kv.return_value = {}
        mem.get_structured_state.return_value = {}
        return mem

    def _make_input(self, **overrides):
        defaults = dict(
            uid="user1",
            query="gaming laptop",
            constraints={"budget_max": 1500, "use_case": "gaming"},
            results=[{"sku": "SKU-A", "name": "Laptop A"}],
            payload={},
            kv={},
            structured_state={},
            product_memory_bank={},
            image_context={},
            trace_id="trace-123",
            turn_type="result_turn",
            turn_intent="SEARCH",
            referents={"has_reference": False, "source": "none", "skus": []},
            followup_contract={},
            intent_execution_plan=None,
            candidates=[],
            shortlist_lock_active=False,
            llm_model="qwen3:30b",
            assistant_message="Here are some options",
            flags={"POLICY_VERSION": "v1"},
            ctx_summary=None,
        )
        defaults.update(overrides)
        return TurnPersistenceInput(**defaults)

    def test_persists_kv_and_state(self):
        mem = self._make_mem()
        ctx = MagicMock()
        hooks = TurnPersistenceHooks(
            mem=mem,
            suggest_ctx=ctx,
            log_trace_event=MagicMock(),
            trace_meta_payload=lambda **kw: {"recorded_at": "now"},
        )
        inp = self._make_input()
        persist_turn_state(inp, hooks)

        mem.set_kv.assert_called_once()
        mem.set_structured_state.assert_called_once()
        mem.set_product_memory_bank.assert_called_once()
        mem.touch_session.assert_called_once()
        # ctx should have kv_out/structured_state_out bound
        assert ctx.kv_out is not None
        assert ctx.structured_state_out is not None

    def test_shortlist_preserved_on_zero_results(self):
        mem = self._make_mem()
        mem.get_kv.return_value = {"last_shortlist_skus": ["OLD-SKU"]}
        ctx = MagicMock()
        hooks = TurnPersistenceHooks(
            mem=mem, suggest_ctx=ctx,
            log_trace_event=MagicMock(),
            trace_meta_payload=lambda **kw: {},
        )
        inp = self._make_input(results=[], turn_type="zero_result_turn")
        persist_turn_state(inp, hooks)

        # kv_out should NOT have overwritten last_shortlist_skus
        call_args = mem.set_kv.call_args[0]
        kv_saved = call_args[1]
        assert kv_saved["last_shortlist_skus"] == ["OLD-SKU"]

    def test_confirmed_slots_merged(self):
        mem = self._make_mem()
        ctx = MagicMock()
        hooks = TurnPersistenceHooks(
            mem=mem, suggest_ctx=ctx,
            log_trace_event=MagicMock(),
            trace_meta_payload=lambda **kw: {},
        )
        inp = self._make_input(
            constraints={"budget_max": 2000, "use_case": "creative", "brands": ["Apple"]},
        )
        persist_turn_state(inp, hooks)

        kv_saved = mem.set_kv.call_args[0][1]
        assert kv_saved["confirmed_slots"]["budget_max"] == 2000
        assert kv_saved["confirmed_slots"]["use_case"] == "creative"
        assert kv_saved["confirmed_slots"]["brands"] == ["Apple"]

    def test_never_raises(self):
        """persist_turn_state must never propagate exceptions (mirrors original try/except: pass)."""
        mem = MagicMock()
        mem.get_kv.side_effect = RuntimeError("DB down")
        ctx = MagicMock()
        hooks = TurnPersistenceHooks(
            mem=mem, suggest_ctx=ctx,
            log_trace_event=MagicMock(),
            trace_meta_payload=lambda **kw: {},
        )
        inp = self._make_input()
        # Should not raise
        persist_turn_state(inp, hooks)

    def test_summary_checkpoint_on_first_turn(self):
        mem = self._make_mem()
        ctx = MagicMock()
        log_fn = MagicMock()
        hooks = TurnPersistenceHooks(
            mem=mem, suggest_ctx=ctx,
            log_trace_event=log_fn,
            trace_meta_payload=lambda **kw: {"recorded_at": "now"},
        )
        # ctx_summary=None triggers checkpoint
        inp = self._make_input(ctx_summary=None)
        persist_turn_state(inp, hooks)

        mem.set_summary.assert_called_once()
        assert inp.payload.get("session_summary") is not None

    def test_nqe_asked_tracking(self):
        mem = self._make_mem()
        ctx = MagicMock()
        hooks = TurnPersistenceHooks(
            mem=mem, suggest_ctx=ctx,
            log_trace_event=MagicMock(),
            trace_meta_payload=lambda **kw: {},
        )
        inp = self._make_input(
            payload={"next_questions": [{"id": "ask_budget", "text": "What's your budget?"}]},
        )
        persist_turn_state(inp, hooks)

        kv_saved = mem.set_kv.call_args[0][1]
        assert "ask_budget" in kv_saved.get("nqe_asked", [])
