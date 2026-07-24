"""Deterministic, model-backed conversational soak for the V2 commerce core.

This is synthetic TRAFFIC, not synthetic ground truth. It measures routing, bounded
extraction, session continuity, catalog/budget safety, cart-plan safety and latency.
Whether a shown product is genuinely useful still belongs in relevance_labels.json.

Run serially against the local model (parallel model-backed suites contend on Ollama):

    python tests/characterization/synthetic_conversation_soak.py --turns 200

No cart, procurement, supplier, return or payment side effect is executed.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import statistics
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from sqlalchemy.orm import sessionmaker

from src.app.models.db import get_engine
from src.app.services.recommendation_core.cart_resolver import resolve_cart_mutation
from src.app.services.recommendation_core.core import recommend_turn
from src.app.services.recommendation_core.envelope import TurnEnvelope


@dataclass(frozen=True)
class TurnSpec:
    query: str
    kind: str = "recommend"
    budget_min: Optional[float] = None
    budget_max: Optional[float] = None
    lane_in: Sequence[str] = ()
    node_contains: Optional[str] = None
    quantity: Optional[int] = None
    total_budget_cents: Optional[int] = None
    excluded_brand: Optional[str] = None
    expect_products: Optional[bool] = None
    expect_cart_ops: Optional[int] = None
    budget_scope: Optional[str] = None
    calibration_class: Optional[str] = None


@dataclass(frozen=True)
class JourneySpec:
    family: str
    persona: str
    age_group: str
    turns: Sequence[TurnSpec]
    cart: Sequence[Dict[str, Any]] = field(default_factory=tuple)


_CART = (
    {"sku": "LAP-75988087", "name": "HP Envy x360 14-inch Laptop", "quantity": 15},
    {"sku": "LAP-A9A67AB9", "name": "Lenovo ThinkPad L13 Gen 6", "quantity": 20},
    {"sku": "LAP-433AB371", "name": "Lenovo IdeaPad Slim 3i", "quantity": 25},
)


def _base_journeys(variant: int) -> List[JourneySpec]:
    # Vary phrasing and values while keeping every expected invariant explicit.
    school_budget = (800, 900, 1000)[variant % 3]
    office_qty = (15, 20, 25)[variant % 3]
    total_budget = (14_000, 16_000, 19_000)[variant % 3]
    return [
        JourneySpec("high_school", "student-homework-and-light-games", "13-17", (
            TurnSpec(f"I'm in high school and need a laptop for homework under ${school_budget}",
                     budget_max=school_budget, lane_in=("SEARCH", "FILTER"),
                     node_contains="Laptop", expect_products=True),
            TurnSpec("I also want to play Minecraft after school", lane_in=("FILTER", "SEARCH"),
                     node_contains="Laptop", expect_products=True),
            TurnSpec("but not Apple", lane_in=("FILTER",), excluded_brand="Apple",
                     calibration_class="brand_refinement",
                     node_contains="Laptop", expect_products=True),
            TurnSpec("why is the first one suitable for me?", lane_in=("EXPLAIN",),
                     node_contains="Laptop", excluded_brand="Apple", expect_products=True),
            TurnSpec("raise the budget to $1200 but keep the homework and Minecraft needs",
                     lane_in=("FILTER", "SEARCH"), node_contains="Laptop",
                     budget_max=1200, excluded_brand="Apple", expect_products=True),
        )),
        JourneySpec("university", "engineering-student", "18-24", (
            TurnSpec("I need a university laptop for AutoCAD and engineering assignments under $1800",
                     budget_max=1800, lane_in=("SEARCH", "FILTER"), node_contains="Laptop",
                     expect_products=True),
            TurnSpec("only models with at least 16GB RAM", lane_in=("FILTER",),
                     node_contains="Laptop", expect_products=True),
            TurnSpec("show me the cheaper ones", lane_in=("FILTER",), node_contains="Laptop",
                     expect_products=True),
            TurnSpec("explain the tradeoff on the first option", lane_in=("EXPLAIN",),
                     node_contains="Laptop", expect_products=True),
            TurnSpec("I may also use Blender; keep the same budget", lane_in=("FILTER", "SEARCH"),
                     node_contains="Laptop", expect_products=True),
        )),
        JourneySpec("ai_creator", "local-ai-and-image-generation", "25-44", (
            TurnSpec("laptop for fine-tuning small language models locally, budget $2300",
                     budget_max=2300, lane_in=("SEARCH", "FILTER"), node_contains="Laptop",
                     expect_products=True),
            TurnSpec("it also needs to run local AI image generation", lane_in=("FILTER", "SEARCH"),
                     node_contains="Laptop", expect_products=True),
            TurnSpec("nothing from Apple", lane_in=("FILTER",), excluded_brand="Apple",
                     node_contains="Laptop", expect_products=True),
            TurnSpec("why is the first one better for that workload?", lane_in=("EXPLAIN",),
                     node_contains="Laptop", excluded_brand="Apple", expect_products=True),
            TurnSpec("I can use cloud training but want local 7B inference", lane_in=("FILTER", "SEARCH"),
                     node_contains="Laptop", excluded_brand="Apple", expect_products=True),
        )),
        JourneySpec("retiree", "simple-social-and-casual-games", "65+", (
            TurnSpec("I'm a grandmother and want a simple laptop for Facebook, video calls and Candy Crush under $700",
                     budget_max=700, lane_in=("SEARCH", "FILTER"), node_contains="Laptop",
                     expect_products=True),
            TurnSpec("a larger easy-to-read screen matters more than speed", lane_in=("FILTER", "SEARCH"),
                     node_contains="Laptop", expect_products=True),
            TurnSpec("not an Apple one please", lane_in=("FILTER",), excluded_brand="Apple",
                     calibration_class="brand_refinement",
                     node_contains="Laptop", expect_products=True),
            TurnSpec("why would the first one be easy for me to use?", lane_in=("EXPLAIN",),
                     node_contains="Laptop", excluded_brand="Apple", expect_products=True),
            TurnSpec("keep it under $700 and prioritise reliable video calls", lane_in=("FILTER", "SEARCH"),
                     node_contains="Laptop", budget_max=700, excluded_brand="Apple", expect_products=True),
        )),
        JourneySpec("graphics_tablet", "drawing-with-existing-computer", "mixed", (
            TurnSpec("I already have a computer and only want a Wacom graphics tablet for drawing under $500",
                     budget_max=500, lane_in=("SEARCH", "FILTER"), node_contains="Graphics Tablet",
                     expect_products=True),
            TurnSpec("show the cheapest drawing tablet", lane_in=("FILTER",),
                     calibration_class="sort_refinement",
                     node_contains="Graphics Tablet", expect_products=True),
            TurnSpec("why is the first one enough for a high school art student?", lane_in=("EXPLAIN",),
                     node_contains="Graphics Tablet", expect_products=True),
            TurnSpec("what if the class needs 10 of them with $4000 total?",
                     lane_in=("PROCUREMENT", "FILTER"), node_contains="Graphics Tablet",
                     quantity=10, total_budget_cents=400_000, budget_scope="total"),
            TurnSpec("actually make that 12 tablets but keep the $4000 total",
                     lane_in=("PROCUREMENT", "FILTER"), node_contains="Graphics Tablet",
                     quantity=12, total_budget_cents=400_000, budget_scope="total"),
        )),
        JourneySpec("office_per_unit", "small-business-office-manager", "35-54", (
            TurnSpec(f"We need {office_qty} business laptops for office work, ${1400 + variant * 50} each",
                     budget_max=1400 + variant * 50, lane_in=("PROCUREMENT", "SEARCH"),
                     node_contains="Laptop", quantity=office_qty, budget_scope="per_unit"),
            TurnSpec(f"actually make that {office_qty + 5} people", lane_in=("PROCUREMENT", "FILTER"),
                     node_contains="Laptop", quantity=office_qty + 5),
            TurnSpec("exclude Apple and keep the same budget", lane_in=("PROCUREMENT", "FILTER"),
                     node_contains="Laptop", excluded_brand="Apple"),
            TurnSpec("what is the delivery and sourcing tradeoff?",
                     lane_in=("POLICY_QUESTION", "PROCUREMENT", "EXPLAIN"),
                     calibration_class="active_procurement_explanation",
                     node_contains="Laptop"),
            TurnSpec("prepare the supplier quote for the current quantity", lane_in=("PROCUREMENT",),
                     node_contains="Laptop"),
        )),
        JourneySpec("office_total", "procurement-lead", "35-54", (
            TurnSpec(f"I need 20 work laptops with a total order budget of ${total_budget}",
                     lane_in=("PROCUREMENT", "SEARCH"), node_contains="Laptop", quantity=20,
                     total_budget_cents=total_budget * 100, budget_scope="total"),
            TurnSpec("reduce the order to 15 units", lane_in=("PROCUREMENT", "FILTER"),
                     node_contains="Laptop", quantity=15),
            TurnSpec("show a cheaper configuration but keep the total budget", lane_in=("PROCUREMENT", "FILTER"),
                     node_contains="Laptop"),
            TurnSpec("why is that allocation the best fit?", lane_in=("EXPLAIN", "PROCUREMENT"),
                     node_contains="Laptop"),
            TurnSpec("if we select a $3500 workstation, use the maximum quantity the same total can afford",
                     calibration_class="total_budget_affordability_action",
                     lane_in=("PROCUREMENT", "FILTER"), node_contains="Laptop"),
        )),
        JourneySpec("gaming", "enthusiast-gamer", "18-34", (
            TurnSpec("gaming laptop for Cyberpunk 2077 under $2300", budget_max=2300,
                     lane_in=("SEARCH", "FILTER"), node_contains="Laptop", expect_products=True),
            TurnSpec("it should also play Valorant at 144fps", lane_in=("FILTER", "SEARCH"),
                     node_contains="Laptop", expect_products=True),
            TurnSpec("show the more affordable capable ones", lane_in=("FILTER",),
                     node_contains="Laptop", expect_products=True),
            TurnSpec("explain the first one's minimum versus recommended fit", lane_in=("EXPLAIN",),
                     node_contains="Laptop", expect_products=True),
            TurnSpec("actually this is for developing games in Unreal and Blender, not only playing them",
                     lane_in=("FILTER", "SEARCH"), node_contains="Laptop", expect_products=True),
        )),
        JourneySpec("support", "post-purchase-customer", "mixed", (
            TurnSpec("what is the returns policy?", lane_in=("POLICY_QUESTION",)),
            TurnSpec("does the laptop warranty cover a failed screen?", lane_in=("POLICY_QUESTION", "SUPPORT_CLAIM")),
            TurnSpec("the charging port stopped working and I need a repair", lane_in=("SUPPORT_CLAIM",)),
            TurnSpec("it arrived damaged, how do I return it?", lane_in=("SUPPORT_CLAIM", "POLICY_QUESTION")),
            TurnSpec("what evidence do I need for a warranty repair?", lane_in=("POLICY_QUESTION", "SUPPORT_CLAIM")),
        )),
        JourneySpec("cart_changes", "buyer-changing-their-mind", "25-54", (
            TurnSpec("remove the HP Envy and reduce the IdeaPad Slim 3i to 20", kind="cart", expect_cart_ops=2),
            TurnSpec("actually set the ThinkPad to 15", kind="cart", expect_cart_ops=1),
            TurnSpec("keep only the IdeaPad", kind="cart", expect_cart_ops=1),
            TurnSpec("clear my cart", kind="cart", expect_cart_ops=1),
            TurnSpec("clear all items again", kind="cart", expect_cart_ops=1),
        ), cart=_CART),
        JourneySpec("cart_arithmetic", "bulk-game-development-buyer", "25-54", (
            TurnSpec('clear "Asus TUF Gaming F16 16-inch" please',
                     kind="cart", expect_cart_ops=1),
            TurnSpec("add 5 units to the IdeaPad", kind="cart", expect_cart_ops=1),
            TurnSpec("take 5 units off the IdeaPad", kind="cart", expect_cart_ops=1),
            TurnSpec("double the HP OMEN quantity", kind="cart", expect_cart_ops=1),
            TurnSpec("halve the HP OMEN quantity", kind="cart", expect_cart_ops=1),
        ), cart=(
            {"sku": "ASUS-TUF", "name": "Asus TUF Gaming F16 16-inch Laptop", "quantity": 20},
            {"sku": "HP-OMEN", "name": "HP OMEN MAX 16-inch Laptop", "quantity": 10},
            {"sku": "IDEAPAD", "name": "Lenovo IdeaPad Slim 3i Laptop", "quantity": 20},
        )),
    ]


def build_journeys(turn_target: int, seed: int = 20260713, *,
                   turns_per_journey: Optional[int] = None) -> List[JourneySpec]:
    if turn_target < 1:
        return []
    rng = random.Random(seed)
    pool: List[JourneySpec] = []
    variant = 0
    def _planned_turns(journey: JourneySpec) -> int:
        return min(len(journey.turns), int(turns_per_journey or len(journey.turns)))

    while sum(_planned_turns(j) for j in pool) < turn_target:
        batch = _base_journeys(variant)
        rng.shuffle(batch)
        pool.extend(batch)
        variant += 1
    # Preserve whole journeys where possible; truncate only the final journey.
    out: List[JourneySpec] = []
    remaining = turn_target
    for j in pool:
        if remaining <= 0:
            break
        take = min(remaining, int(turns_per_journey or len(j.turns)))
        turns = tuple(j.turns[:take])
        out.append(JourneySpec(j.family, j.persona, j.age_group, turns, j.cart))
        remaining -= len(turns)
    return out


def build_context_journeys(count: int = 20, seed: int = 20260720) -> List[JourneySpec]:
    """Ten-turn recommendation sessions that stress retained buyer constraints."""
    rng = random.Random(seed)
    source = [j for variant in range(3) for j in _base_journeys(variant)
              if j.family not in {"support", "cart_changes"}]
    rng.shuffle(source)
    out: List[JourneySpec] = []
    for index in range(count):
        base = source[index % len(source)]
        node = base.turns[0].node_contains
        extras = (
            TurnSpec("keep the same product type, budget and requirements",
                     lane_in=("FILTER", "SEARCH", "PROCUREMENT"), node_contains=node),
            TurnSpec("why is the first current option a fit?",
                     lane_in=("EXPLAIN",), node_contains=node),
            TurnSpec("show another option without changing my constraints",
                     lane_in=("FILTER", "SEARCH", "PROCUREMENT"), node_contains=node),
            TurnSpec("do not change the quantity or total budget",
                     lane_in=("FILTER", "SEARCH", "PROCUREMENT"), node_contains=node),
            TurnSpec("summarise what I asked for and the main tradeoff",
                     lane_in=("EXPLAIN", "FILTER", "PROCUREMENT"), node_contains=node),
        )
        out.append(JourneySpec(
            family=f"context_{base.family}", persona=base.persona, age_group=base.age_group,
            turns=tuple(base.turns) + extras, cart=base.cart,
        ))
    return out


def build_lifecycle_journeys(count: int = 14, seed: int = 20260720) -> List[JourneySpec]:
    """Fifteen-turn proposal-only procurement/support journeys.

    These turns verify routing, continuity and the no-send/no-persist boundary. Durable RFQ
    creation, channel selection and redraft are exercised by fulfillment integration tests.
    """
    rng = random.Random(seed)
    quantities = [15, 20, 25, 30]
    budgets = [22_000, 30_000, 41_000, 54_000]
    out: List[JourneySpec] = []
    for index in range(count):
        qty = quantities[index % len(quantities)]
        revised = max(5, qty - 5)
        budget = budgets[index % len(budgets)]
        turns = (
            TurnSpec(f"I need {qty} office laptops with a total order budget of ${budget}",
                     lane_in=("PROCUREMENT", "SEARCH"), node_contains="Laptop", quantity=qty,
                     total_budget_cents=budget * 100, budget_scope="total"),
            TurnSpec("prepare a supplier quote but do not send anything",
                     lane_in=("PROCUREMENT",), node_contains="Laptop"),
            TurnSpec(f"actually reduce the requirement to {revised} units",
                     lane_in=("PROCUREMENT", "FILTER"), node_contains="Laptop", quantity=revised),
            TurnSpec("revise the supplier quote for that current quantity",
                     lane_in=("PROCUREMENT",), node_contains="Laptop"),
            TurnSpec("which supplier communication channel would be used and why?",
                     lane_in=("PROCUREMENT", "EXPLAIN"), node_contains="Laptop"),
            TurnSpec("we need delivery by the end of next month",
                     lane_in=("PROCUREMENT", "FILTER"), node_contains="Laptop"),
            TurnSpec("what warranty applies to this business order?",
                     lane_in=("POLICY_QUESTION", "PROCUREMENT"), node_contains="Laptop"),
            TurnSpec("I am not ready to proceed; keep it as a draft",
                     lane_in=("PROCUREMENT", "POLICY_QUESTION"), node_contains="Laptop"),
            TurnSpec("what happens if some units arrive damaged?",
                     lane_in=("POLICY_QUESTION", "SUPPORT_CLAIM", "PROCUREMENT")),
            TurnSpec("what evidence would a warranty repair require?",
                     lane_in=("POLICY_QUESTION", "SUPPORT_CLAIM")),
            TurnSpec("resume the laptop sourcing draft with the same constraints",
                     lane_in=("PROCUREMENT", "FILTER", "SEARCH"), node_contains="Laptop"),
            TurnSpec(f"change it back to {qty} units but keep the total budget",
                     lane_in=("PROCUREMENT", "FILTER"), node_contains="Laptop", quantity=qty,
                     total_budget_cents=budget * 100, budget_scope="total"),
            TurnSpec("show the lower-cost capable option for that order",
                     lane_in=("PROCUREMENT", "FILTER", "SEARCH"), node_contains="Laptop"),
            TurnSpec("redraft the quote and identify any MOQ or delivery-date blocker",
                     lane_in=("PROCUREMENT",), node_contains="Laptop"),
            TurnSpec("confirm that no supplier message has been sent",
                     lane_in=("PROCUREMENT", "EXPLAIN"), node_contains="Laptop"),
        )
        out.append(JourneySpec(
            family="lifecycle_procurement", persona="procurement-lead",
            age_group=("25-44" if index % 2 else "45-64"), turns=turns,
        ))
    rng.shuffle(out)
    return out


def _percentile(values: List[float], p: float) -> float:
    if not values:
        return 0.0
    xs = sorted(values)
    rank = max(0, min(len(xs) - 1, math.ceil((p / 100) * len(xs)) - 1))
    return round(xs[rank], 1)


def _resume_checkpoint(
    path: Path,
    *,
    seed: int,
    suite: str,
    journeys: Sequence[JourneySpec],
) -> tuple[List[Dict[str, Any]], set[int]]:
    """Keep only complete journeys from a checkpoint belonging to this exact run."""
    if not path.exists():
        return [], set()
    parsed: List[Dict[str, Any]] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        if row.get("seed") != seed or row.get("suite") != suite:
            raise ValueError(f"checkpoint {path} belongs to a different seed or suite")
        parsed.append(row)

    complete: set[int] = set()
    kept: List[Dict[str, Any]] = []
    for journey_index, journey in enumerate(journeys):
        records = sorted(
            (row for row in parsed if row.get("journey") == journey_index),
            key=lambda row: int(row.get("turn", -1)),
        )
        if [row.get("turn") for row in records] == list(range(len(journey.turns))):
            complete.add(journey_index)
            kept.extend(records)

    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, default=str) + "\n" for row in kept),
        encoding="utf-8",
    )
    return kept, complete


def _session_from(core, prior: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    dec = core.extras.get("decision") or {}
    used = core.extras.get("constraints_used") or {}
    out = dict(prior or {})
    out["prior_lane"] = core.lane
    prior_workflow = out.get("active_workflow_lane")
    if core.lane == "PROCUREMENT":
        out["active_workflow_lane"] = "PROCUREMENT"
    elif dec.get("subject_action") == "switch":
        out.pop("active_workflow_lane", None)
    elif prior_workflow:
        out["active_workflow_lane"] = prior_workflow
    if dec.get("node_handle"):
        out["prior_node"] = dec["node_handle"]
    shortlist = [p.sku for p in core.products[:12]]
    if shortlist:
        out["shortlist_skus"] = shortlist
    accepted = dict(out.get("accepted_constraints") or {})
    updates = {
        "budget_min_cents": used.get("budget_min_cents"),
        "budget_max_cents": used.get("budget_max_cents"),
        "requirements": used.get("requirements") or dec.get("requirements"),
        "use_cases": dec.get("use_cases"),
        "quantity": dec.get("quantity"),
        "total_budget_cents": dec.get("total_budget_cents"),
        "budget_scope": dec.get("budget_scope"),
        "exclude_brand": dec.get("exclude_brand"),
        "brand_filter": dec.get("brand_filter"),
        "preferred_brand": dec.get("preferred_brand"),
    }
    for key, value in updates.items():
        if key == "budget_scope" and value in (None, "", "unknown"):
            continue
        if value is not None and value != [] and value != {}:
            accepted[key] = value
    out["accepted_constraints"] = accepted
    return out


def _error_dimension(error: str, *, turn: int) -> str:
    """Keep routing, catalog coverage, buyer safety and context continuity separate."""
    code = str(error or "").split(":", 1)[0]
    if code == "lane":
        return "routing_calibration"
    if code == "products":
        return "catalog_coverage"
    if turn > 0 and code in {
        "node", "quantity", "total_budget", "budget_scope", "excluded_brand_shown",
    }:
        return "continuity"
    return "semantic_safety"


def _dimension_summary(rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    dimensions: Dict[str, Any] = {}
    for name in ("semantic_safety", "catalog_coverage", "continuity", "routing_calibration"):
        flagged = []
        codes: Counter[str] = Counter()
        for row in rows:
            matching = [error for error in row.get("errors", [])
                        if _error_dimension(error, turn=int(row.get("turn") or 0)) == name]
            if matching:
                flagged.append(row)
                codes.update(error.split(":", 1)[0] for error in matching)
        dimensions[name] = {
            "measured": True,
            "passed_turns": len(rows) - len(flagged),
            "flagged_turns": len(flagged),
            "pass_rate": round((len(rows) - len(flagged)) / max(1, len(rows)), 4),
            "failures_by_code": dict(codes),
        }
    dimensions["relevance"] = {
        "measured": False,
        "reason": "synthetic traffic is not relevance ground truth; use sealed human labels",
    }
    return dimensions


def _routing_calibration_summary(rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Report authored routing expectations without re-parsing shopper language."""
    misses = [row for row in rows if any(
        str(error).startswith("lane:") for error in row.get("errors", []))]
    return {
        "misses": len(misses),
        "by_class": dict(Counter(
            str(row.get("calibration_class") or "unclassified") for row in misses)),
        "classes": [
            {
                "class": str(row.get("calibration_class") or "unclassified"),
                "query": row.get("query"),
                "actual_lane": row.get("lane"),
                "expected": [
                    str(error).split("expected:", 1)[1]
                    for error in row.get("errors", [])
                    if str(error).startswith("lane:") and "expected:" in str(error)
                ],
            }
            for row in misses
        ],
    }


def _effective_decision(core, prior_session: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    dec = dict(core.extras.get("decision") or {})
    prior = dict(prior_session or {})
    accepted = dict(prior.get("accepted_constraints") or {})
    if not dec.get("node_path") and prior.get("prior_node"):
        try:
            from src.app.services.taxonomy_registry import get_node

            node = get_node(str(prior["prior_node"]))
            if node is not None:
                dec["node_path"] = node.full_path
                dec["node_handle"] = node.handle
        except Exception:
            pass
    for key in ("quantity", "total_budget_cents", "exclude_brand", "brand_filter"):
        if dec.get(key) is None and accepted.get(key) is not None:
            dec[key] = accepted[key]
    if dec.get("budget_scope") in (None, "", "unknown") and accepted.get("budget_scope"):
        dec["budget_scope"] = accepted["budget_scope"]
    return dec


def _recommend_checks(spec: TurnSpec, core,
                      prior_session: Optional[Dict[str, Any]] = None) -> List[str]:
    errors: List[str] = []
    dec = _effective_decision(core, prior_session)
    lane = str(core.lane or "")
    if spec.lane_in and lane not in spec.lane_in:
        errors.append(f"lane:{lane}:expected:{','.join(spec.lane_in)}")
    if spec.node_contains and spec.node_contains.lower() not in str(dec.get("node_path") or "").lower():
        errors.append(f"node:{dec.get('node_path')}:expected_contains:{spec.node_contains}")
    if spec.quantity is not None and dec.get("quantity") != spec.quantity:
        errors.append(f"quantity:{dec.get('quantity')}:expected:{spec.quantity}")
    if spec.total_budget_cents is not None and dec.get("total_budget_cents") != spec.total_budget_cents:
        errors.append(f"total_budget:{dec.get('total_budget_cents')}:expected:{spec.total_budget_cents}")
    if spec.budget_scope and dec.get("budget_scope") != spec.budget_scope:
        errors.append(f"budget_scope:{dec.get('budget_scope')}:expected:{spec.budget_scope}")
    if spec.expect_products is True and not core.products:
        errors.append("products:empty")
    if spec.expect_products is False and core.products:
        errors.append("products:unexpected")
    if spec.excluded_brand:
        bad = [p.sku for p in core.products if str(p.brand or "").lower() == spec.excluded_brand.lower()]
        if bad:
            errors.append(f"excluded_brand_shown:{spec.excluded_brand}:{','.join(bad)}")
    # A product must not recommend its own category as a complement.
    node = str(dec.get("node_handle") or "")
    for offer in core.extras.get("complement_offers") or []:
        comp = str(offer.get("node") or "")
        if node and comp and (node == comp or node.startswith(comp + "-") or comp.startswith(node + "-")):
            errors.append(f"self_complement:{node}:{comp}")
    # Supplier/RFQ actions in this soak must remain proposals only.
    blob = json.dumps(core.extras, default=str).lower()
    if '"sent": true' in blob or '"executed": true' in blob:
        errors.append("irreversible_action_executed")
    # These lanes are routing-only in V2 today. Do not let future enrollment claim persistence
    # until an idempotent handoff has actually committed the action.
    if core.lane == "SUPPORT_CLAIM" and (
            core.extras.get("claim_status") in {"received", "logged"}
            or "i've logged" in str(core.message or "").lower()):
        errors.append("unpersistence_claim:support")
    return errors


def _apply_cart_plan(cart: List[Dict[str, Any]], plan) -> List[Dict[str, Any]]:
    out = [dict(x) for x in cart]
    for op in plan.ops:
        targets = set(op.target_skus)
        if op.action == "clear_all":
            out = []
        elif op.action == "remove_items":
            out = [x for x in out if x.get("sku") not in targets]
        elif op.action == "keep_only":
            out = [x for x in out if x.get("sku") in targets]
        elif op.action == "set_quantity" and op.target_skus:
            for row in out:
                if row.get("sku") == op.target_skus[0]:
                    row["quantity"] = int(op.quantity or 0)
    return out


def run_soak(turn_target: int, seed: int, only_family: Optional[str] = None, *,
             turns_per_journey: Optional[int] = None,
             checkpoint_path: Optional[Path] = None,
             resume: bool = False,
             journeys_override: Optional[Sequence[JourneySpec]] = None,
             suite: str = "breadth") -> Dict[str, Any]:
    journeys = (list(journeys_override) if journeys_override is not None else
                build_journeys(turn_target, seed, turns_per_journey=turns_per_journey))
    if only_family:
        journeys = [j for j in journeys if j.family == only_family]
    session_factory = sessionmaker(bind=get_engine())
    db = session_factory()
    rows: List[Dict[str, Any]] = []
    completed_journeys: set[int] = set()
    started = time.time()
    if checkpoint_path:
        checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        if resume:
            rows, completed_journeys = _resume_checkpoint(
                checkpoint_path, seed=seed, suite=suite, journeys=journeys,
            )
        else:
            checkpoint_path.unlink(missing_ok=True)
    try:
        for ji, journey in enumerate(journeys):
            if ji in completed_journeys:
                continue
            session: Dict[str, Any] = {}
            cart = [dict(x) for x in journey.cart]
            for ti, spec in enumerate(journey.turns):
                uid = f"synthetic-{seed}-{ji}"
                env = TurnEnvelope.from_suggest_params(
                    query=spec.query, uid=uid, tenant_id="default",
                    budget_min=spec.budget_min, budget_max=spec.budget_max,
                    session=session, cart=cart,
                )
                t0 = time.perf_counter()
                errors: List[str] = []
                record: Dict[str, Any] = {
                    "seed": seed, "suite": suite,
                    "journey": ji, "turn": ti, "family": journey.family,
                    "persona": journey.persona, "age_group": journey.age_group,
                    "kind": spec.kind, "query": spec.query,
                    "calibration_class": spec.calibration_class,
                }
                try:
                    if spec.kind == "cart":
                        plan = resolve_cart_mutation(env)
                        errors.extend([] if len(plan.ops) == int(spec.expect_cart_ops or 0) else
                                      [f"cart_ops:{len(plan.ops)}:expected:{spec.expect_cart_ops}"])
                        if plan.needs_clarification:
                            errors.append("cart_unexpected_clarification")
                        cart = _apply_cart_plan(cart, plan)
                        record.update({"lane": "CART_MUTATE", "ops": plan.as_dict(),
                                       "cart_size": len(cart)})
                    else:
                        core = recommend_turn(db, env)
                        errors.extend(_recommend_checks(spec, core, session))
                        dec = core.extras.get("decision") or {}
                        session = _session_from(core, session)
                        effective = _effective_decision(core, session)
                        record.update({
                            "lane": core.lane, "node": effective.get("node_path"),
                            "quantity": effective.get("quantity"),
                            "total_budget_cents": effective.get("total_budget_cents"),
                            "budget_scope": effective.get("budget_scope"),
                            "product_skus": [p.sku for p in core.products],
                            "product_brands": [p.brand for p in core.products],
                            "message": str(core.message or "")[:500],
                            "extras": sorted(core.extras.keys()),
                        })
                except Exception as exc:
                    errors.append(f"exception:{type(exc).__name__}:{str(exc)[:120]}")
                record["latency_ms"] = round((time.perf_counter() - t0) * 1000, 1)
                record["errors"] = errors
                record["error_dimensions"] = sorted({
                    _error_dimension(error, turn=ti) for error in errors
                })
                rows.append(record)
                if checkpoint_path:
                    with checkpoint_path.open("a", encoding="utf-8") as fh:
                        fh.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
                print(f"[{len(rows):03d}] {journey.family}/{ti} {record.get('lane','ERROR')} "
                      f"{record['latency_ms']:.0f}ms errors={len(errors)}", flush=True)
    finally:
        db.close()

    latencies = [float(r["latency_ms"]) for r in rows]
    failures = [r for r in rows if r["errors"]]
    return {
        "meta": {"seed": seed, "suite": suite, "requested_turns": turn_target,
                 "completed_turns": len(rows), "journeys": len(journeys),
                 "started_at": datetime.fromtimestamp(started, timezone.utc).isoformat(),
                 "duration_seconds": round(time.time() - started, 1),
                 "synthetic_is_not_human_ground_truth": True},
        "summary": {
            "passed": len(rows) - len(failures), "failed": len(failures),
            "invariant_pass_rate": round((len(rows) - len(failures)) / max(1, len(rows)), 4),
            "latency_ms": {"p50": _percentile(latencies, 50),
                           "p95": _percentile(latencies, 95),
                           "max": round(max(latencies), 1) if latencies else 0.0,
                           "mean": round(statistics.mean(latencies), 1) if latencies else 0.0},
            "lanes": dict(Counter(str(r.get("lane") or "ERROR") for r in rows)),
            "failures_by_code": dict(Counter(e.split(":", 1)[0] for r in failures for e in r["errors"])),
            "failures_by_family": dict(Counter(r["family"] for r in failures)),
            "dimensions": _dimension_summary(rows),
            "routing_calibration": _routing_calibration_summary(rows),
            "aggregate_invariant_rate_deprecated": True,
        },
        "failures": failures,
        "turns": rows,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--turns", type=int, default=200)
    ap.add_argument("--seed", type=int, default=20260713)
    ap.add_argument("--only-family")
    ap.add_argument("--turns-per-journey", type=int)
    ap.add_argument("--suite", choices=("breadth", "context", "lifecycle"), default="breadth")
    ap.add_argument("--output")
    ap.add_argument(
        "--resume", action="store_true",
        help="resume complete journeys from the matching partial JSONL checkpoint",
    )
    ap.add_argument("--fail-on-invariant", action="store_true")
    args = ap.parse_args()
    out = Path(args.output) if args.output else (
        ROOT / "tmp" / "synthetic_soak" / f"review10_{args.seed}_{args.turns}.json")
    checkpoint = out.with_suffix(out.suffix + ".partial.jsonl")
    if args.suite == "breadth":
        report = run_soak(max(1, args.turns), args.seed, args.only_family,
                          turns_per_journey=args.turns_per_journey,
                          checkpoint_path=checkpoint, resume=args.resume)
    else:
        journeys = (build_context_journeys(max(1, args.turns // 10), args.seed)
                    if args.suite == "context"
                    else build_lifecycle_journeys(max(1, args.turns // 15), args.seed))
        report = run_soak(args.turns, args.seed, checkpoint_path=checkpoint,
                          resume=args.resume, journeys_override=journeys, suite=args.suite)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    checkpoint.unlink(missing_ok=True)
    print(json.dumps({"report": str(out), **report["summary"]}, ensure_ascii=False), flush=True)
    return 1 if args.fail_on_invariant and report["summary"]["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
