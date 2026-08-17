from src.app.services.recommendation_core.router_parser import (
    parse_clarification_relation,
    parse_router_payload,
)
from src.app.services.recommendation_core.router_policy_clamp import clamp_lane
from src.app.services.recommendation_core.router_prompt import compose_router_prompt


def test_router_parser_rejects_non_object_or_malformed_output():
    assert parse_router_payload("[]") is None
    assert parse_router_payload("not-json") is None
    assert parse_router_payload('{"lane":"SEARCH"}') == {"lane": "SEARCH"}


def test_clarification_parser_and_lane_clamp_are_closed_vocabularies():
    assert parse_clarification_relation('{"clarification_relation":"answer"}') == "answer"
    assert parse_clarification_relation('{"clarification_relation":"execute_cart"}') == "ambiguous"
    assert clamp_lane("rfq") == "PROCUREMENT"
    assert clamp_lane("execute_payment") is None


def test_prompt_composer_preserves_section_order_and_bounds_message():
    prompt = compose_router_prompt(
        instruction_prefix="RULES", guide="GUIDE\n", variants="VARIANTS\n",
        prior_context="PRIOR\n", pending_context="PENDING\n", message="x" * 500,
        budget="BUDGET\n", image="IMAGE\n", research="RESEARCH\n",
        candidate_lines="  el-6 : Electronics",
    )
    assert prompt.index("RULES") < prompt.index("PRIOR") < prompt.index("MESSAGE")
    assert "x" * 401 not in prompt
    assert prompt.endswith("JSON:")
