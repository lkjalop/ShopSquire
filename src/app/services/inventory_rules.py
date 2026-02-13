from __future__ import annotations

import uuid
from typing import Any, Dict, List
from dataclasses import dataclass

from src.app.services.decision_log import log_trace_event, log_decision


@dataclass
class RuleResult:
    rule_id: int
    triggered: bool
    action: str | None
    message: str | None


def _emit_event(trace_id: str, rule: RuleResult, context: Dict[str, Any]):
    try:
        log_trace_event(
            trace_id=trace_id,
            event_type="rule_evaluated",
            source_type="inventory_rules",
            source_id=f"rule_{rule.rule_id}",
            target_type="sku",
            target_id=context.get("sku") or None,
            payload={"rule": rule.rule_id, "triggered": rule.triggered, "action": rule.action, "message": rule.message},
        )
    except Exception:
        pass


def evaluate_stock_rules(context: Dict[str, Any]) -> Dict[str, Any]:
    """Evaluate deterministic inventory rules and return decision + trace info.

    context expected keys: sku, stock, reserved, reorder_in_progress(bool), discontinued(bool), warehouses(list), pre_order(bool), backorder(bool), discrepancy(bool), customer (dict), product (dict)
    """
    decision_id = str(uuid.uuid4())
    trace_id = decision_id
    results: List[RuleResult] = []

    sku = context.get("sku")
    stock = int(context.get("stock") or 0)
    reserved = int(context.get("reserved") or 0)
    reorder = bool(context.get("reorder_in_progress"))
    discontinued = bool(context.get("discontinued"))
    warehouses = context.get("warehouses") or []
    pre_order = bool(context.get("pre_order"))
    backorder = bool(context.get("backorder"))
    discrepancy = bool(context.get("discrepancy"))
    customer = context.get("customer") or {}
    product = context.get("product") or {}

    # Category 1: Stock Availability (Rules 1-10)
    # 1: Stock > 10
    r1 = RuleResult(1, stock > 10, "in_stock" if stock > 10 else None, f"{stock} units available")
    results.append(r1)
    _emit_event(trace_id, r1, context)

    # 2: Stock 1-10
    r2 = RuleResult(2, 1 <= stock <= 10, "limited_stock" if 1 <= stock <= 10 else None, f"Limited stock: {stock} remaining")
    results.append(r2)
    _emit_event(trace_id, r2, context)

    # 3: Stock == 0 and reorder in progress
    r3 = RuleResult(3, stock == 0 and reorder, "back_soon" if stock == 0 and reorder else None, "Temporarily out - reorder in progress")
    results.append(r3)
    _emit_event(trace_id, r3, context)

    # 4: Stock ==0 and no reorder
    r4 = RuleResult(4, stock == 0 and not reorder and not discontinued, "unavailable" if stock == 0 and not reorder and not discontinued else None, "Currently unavailable")
    results.append(r4)
    _emit_event(trace_id, r4, context)

    # 5: discontinued
    r5 = RuleResult(5, discontinued, "discontinued" if discontinued else None, "No longer available")
    results.append(r5)
    _emit_event(trace_id, r5, context)

    # 6: reserved stock
    avail = max(0, stock - reserved)
    r6 = RuleResult(6, reserved > 0, "adjust_display" if reserved > 0 else None, f"Reserved {reserved}, available {avail}")
    results.append(r6)
    _emit_event(trace_id, r6, context)

    # 7: multiple warehouses
    r7 = RuleResult(7, len(warehouses) > 1, "show_nearest" if len(warehouses) > 1 else None, "Show nearest warehouse availability")
    results.append(r7)
    _emit_event(trace_id, r7, context)

    # 8: pre-order
    r8 = RuleResult(8, pre_order, "pre_order" if pre_order else None, "Available for pre-order")
    results.append(r8)
    _emit_event(trace_id, r8, context)

    # 9: backorder accepted
    r9 = RuleResult(9, backorder, "backorder" if backorder else None, "Backorder available")
    results.append(r9)
    _emit_event(trace_id, r9, context)

    # 10: stock discrepancy detected
    r10 = RuleResult(10, discrepancy, "hold_and_verify" if discrepancy else None, "Stock discrepancy detected - verification required")
    results.append(r10)
    _emit_event(trace_id, r10, context)

    # Category 2: Customer Context (11-20)
    vip = customer.get("vip") or False
    repeat = customer.get("repeat") or False
    b2b = customer.get("type") == "b2b"
    guest = customer.get("guest") or False
    fraud_region = customer.get("high_fraud_region") or False
    timezone_off = customer.get("off_hours") or False
    preferred_wh = customer.get("preferred_warehouse")
    open_return = customer.get("open_return") or False
    query_count = customer.get("query_count", 0)
    segment = customer.get("segment") or ""

    r11 = RuleResult(11, vip and avail > 0 and avail <= 1, "reserve_for_vip" if vip and avail > 0 and avail <= 1 else None, "Reserve 1 unit for VIP")
    results.append(r11); _emit_event(trace_id, r11, context)

    r12 = RuleResult(12, repeat, "notify_when_arrive" if repeat else None, "Proactive restock notification")
    results.append(r12); _emit_event(trace_id, r12, context)

    r13 = RuleResult(13, b2b, "route_to_account_manager" if b2b else None, "Route to account manager")
    results.append(r13); _emit_event(trace_id, r13, context)

    r14 = RuleResult(14, guest and product.get("price",0) > 1000, "require_email" if guest and product.get("price",0) > 1000 else None, "Require email for stock alerts")
    results.append(r14); _emit_event(trace_id, r14, context)

    r15 = RuleResult(15, fraud_region, "log_only" if fraud_region else None, "Log but no restriction")
    results.append(r15); _emit_event(trace_id, r15, context)

    r16 = RuleResult(16, timezone_off, "defer_ship" if timezone_off else None, "Adjust ship date to next business day")
    results.append(r16); _emit_event(trace_id, r16, context)

    r17 = RuleResult(17, bool(preferred_wh), "prioritize_warehouse" if preferred_wh else None, "Prioritize preferred warehouse")
    results.append(r17); _emit_event(trace_id, r17, context)

    r18 = RuleResult(18, open_return, "flag_potential_abuse" if open_return else None, "Flag potential abuse")
    results.append(r18); _emit_event(trace_id, r18, context)

    r19 = RuleResult(19, query_count > 5, "offer_subscription" if query_count > 5 else None, "Offer stock alert subscription")
    results.append(r19); _emit_event(trace_id, r19, context)

    r20 = RuleResult(20, segment == "price_sensitive", "include_restock_sale_option" if segment=="price_sensitive" else None, "Include restock sale alert option")
    results.append(r20); _emit_event(trace_id, r20, context)

    # Category 3: Product Context (21-30)
    perishable = product.get("perishable") or False
    serial_tracked = product.get("serial_tracked") or False
    bundle = product.get("bundle") or False
    made_to_order = product.get("made_to_order") or False
    drop_ship = product.get("drop_ship") or False
    hazmat = product.get("hazmat") or False
    high_theft = product.get("high_theft") or False
    recall = product.get("under_recall") or False
    promotion = product.get("promotion") or False
    newly_launched = product.get("new_launch") or False

    r21 = RuleResult(21, perishable, "expiry_adjusted" if perishable else None, "Show expiry-adjusted availability")
    results.append(r21); _emit_event(trace_id, r21, context)

    r22 = RuleResult(22, serial_tracked, "confirm_serial" if serial_tracked else None, "Confirm serial availability")
    results.append(r22); _emit_event(trace_id, r22, context)

    r23 = RuleResult(23, bundle, "check_components" if bundle else None, "Check component availability")
    results.append(r23); _emit_event(trace_id, r23, context)

    r24 = RuleResult(24, made_to_order, "show_lead_time" if made_to_order else None, "Show lead time")
    results.append(r24); _emit_event(trace_id, r24, context)

    r25 = RuleResult(25, drop_ship, "query_supplier_api" if drop_ship else None, "Query supplier API (cached)")
    results.append(r25); _emit_event(trace_id, r25, context)

    r26 = RuleResult(26, hazmat, "check_restrictions" if hazmat else None, "Check destination restrictions")
    results.append(r26); _emit_event(trace_id, r26, context)

    r27 = RuleResult(27, high_theft, "hide_exact_count" if high_theft else None, "Don't show exact stock counts")
    results.append(r27); _emit_event(trace_id, r27, context)

    r28 = RuleResult(28, recall, "block_and_explain" if recall else None, "Product under recall")
    results.append(r28); _emit_event(trace_id, r28, context)

    r29 = RuleResult(29, promotion, "adjust_allocation" if promotion else None, "Promotion-adjusted allocation")
    results.append(r29); _emit_event(trace_id, r29, context)

    r30 = RuleResult(30, newly_launched, "limited_initial_stock" if newly_launched else None, "Limited initial stock messaging")
    results.append(r30); _emit_event(trace_id, r30, context)

    # Category 4: Timing and Urgency (31-40)
    urgent = context.get("mentions_urgent") or False
    flash_sale = context.get("flash_sale") or False
    demand_velocity = context.get("demand_velocity") or 0
    end_quarter = context.get("end_quarter") or False
    replenishment_secs = context.get("replenishment_secs") or 999999
    weekend = context.get("weekend") or False
    holiday = context.get("holiday") or False
    concurrent_queries = context.get("concurrent_queries") or 0
    waiting_days = context.get("waiting_days") or 0
    promo_ending = context.get("promo_ending") or False

    r31 = RuleResult(31, urgent, "offer_expedited" if urgent else None, "Offer expedited shipping")
    results.append(r31); _emit_event(trace_id, r31, context)

    r32 = RuleResult(32, flash_sale, "rate_limit" if flash_sale else None, "Rate-limit stock API calls")
    results.append(r32); _emit_event(trace_id, r32, context)

    r33 = RuleResult(33, stock < 3 and demand_velocity > 5, "selling_fast" if stock < 3 and demand_velocity > 5 else None, "Selling fast - few left")
    results.append(r33); _emit_event(trace_id, r33, context)

    r34 = RuleResult(34, end_quarter and b2b, "highlight_deadline" if end_quarter and b2b else None, "Highlight volume discount deadlines")
    results.append(r34); _emit_event(trace_id, r34, context)

    r35 = RuleResult(35, replenishment_secs < 86400, "arriving_tomorrow" if replenishment_secs < 86400 else None, "More arriving tomorrow")
    results.append(r35); _emit_event(trace_id, r35, context)

    r36 = RuleResult(36, weekend, "adjust_ship_dates" if weekend else None, "Adjust ship dates for Monday")
    results.append(r36); _emit_event(trace_id, r36, context)

    r37 = RuleResult(37, holiday, "extend_lead_times" if holiday else None, "Extend lead times")
    results.append(r37); _emit_event(trace_id, r37, context)

    r38 = RuleResult(38, stock == 1 and concurrent_queries > 1, "first_come_queue" if stock == 1 and concurrent_queries > 1 else None, "First-come-first-serve queue")
    results.append(r38); _emit_event(trace_id, r38, context)

    r39 = RuleResult(39, replenishment_secs < 86400 and waiting_days > 3, "notify_on_arrival" if replenishment_secs < 86400 and waiting_days > 3 else None, "Proactive notification")
    results.append(r39); _emit_event(trace_id, r39, context)

    r40 = RuleResult(40, promo_ending, "last_chance" if promo_ending else None, "Last chance messaging")
    results.append(r40); _emit_event(trace_id, r40, context)

    # Category 5: Alternatives (41-50)
    similar_in_stock = context.get("similar_in_stock") or False
    higher_model = context.get("higher_model_available") or False
    lower_model = context.get("lower_model_available") or False
    competitor_price_match = context.get("competitor_price_match") or False
    rental_available = context.get("rental_available") or False
    refurbished_available = context.get("refurbished_available") or False
    variant_available = context.get("variant_available") or False
    component_standalone = context.get("component_standalone") or False
    accessory_main_ok = context.get("accessory_main_ok") or False
    all_variants_out = context.get("all_variants_out") or False

    r41 = RuleResult(41, stock == 0 and similar_in_stock, "suggest_alternative" if stock==0 and similar_in_stock else None, "Suggest alternative product")
    results.append(r41); _emit_event(trace_id, r41, context)

    r42 = RuleResult(42, stock == 0 and higher_model, "upsell" if stock==0 and higher_model else None, "Upsell higher model")
    results.append(r42); _emit_event(trace_id, r42, context)

    r43 = RuleResult(43, stock == 0 and lower_model, "downgrade_suggest" if stock==0 and lower_model else None, "Suggest lower model with savings")
    results.append(r43); _emit_event(trace_id, r43, context)

    r44 = RuleResult(44, stock == 0 and competitor_price_match, "note_price_match" if stock==0 and competitor_price_match else None, "Note price match policy")
    results.append(r44); _emit_event(trace_id, r44, context)

    r45 = RuleResult(45, stock == 0 and rental_available, "suggest_rental" if stock==0 and rental_available else None, "Suggest rental/lease")
    results.append(r45); _emit_event(trace_id, r45, context)

    r46 = RuleResult(46, stock == 0 and refurbished_available, "suggest_refurbished" if stock==0 and refurbished_available else None, "Suggest refurbished")
    results.append(r46); _emit_event(trace_id, r46, context)

    r47 = RuleResult(47, stock == 0 and variant_available, "suggest_variant" if stock==0 and variant_available else None, "Suggest available variants")
    results.append(r47); _emit_event(trace_id, r47, context)

    r48 = RuleResult(48, stock == 0 and component_standalone, "suggest_component" if stock==0 and component_standalone else None, "Suggest standalone component")
    results.append(r48); _emit_event(trace_id, r48, context)

    r49 = RuleResult(49, accessory_main_ok, "proceed_main_backorder_accessory" if accessory_main_ok else None, "Proceed main, backorder accessory")
    results.append(r49); _emit_event(trace_id, r49, context)

    r50 = RuleResult(50, all_variants_out, "notify_on_restock" if all_variants_out else None, "Notify when any variant restocks")
    results.append(r50); _emit_event(trace_id, r50, context)

    # Category 6: Guardrails (51-60)
    max_qty = context.get("max_order_qty") or 100
    request_qty = context.get("request_qty") or 1
    pricing_error = context.get("pricing_error") or False
    reserve_entire = context.get("reserve_entire") or False
    unusual_bulk = context.get("unusual_bulk") or False
    customer_claims_mismatch = context.get("customer_claims_mismatch") or False
    stale_secs = context.get("stock_age_seconds") or 0
    api_timeout = context.get("api_timeout") or False
    conflicting = context.get("conflicting_stock") or False
    sanctioned = customer.get("sanctioned") or False
    high_fraud_combo = context.get("high_fraud_combo") or False

    r51 = RuleResult(51, request_qty > max_qty, "enforce_limit" if request_qty > max_qty else None, "Enforce max order quantity")
    results.append(r51); _emit_event(trace_id, r51, context)

    r52 = RuleResult(52, pricing_error, "hold_and_alert_pricing" if pricing_error else None, "Hold and alert pricing team")
    results.append(r52); _emit_event(trace_id, r52, context)

    r53 = RuleResult(53, reserve_entire, "limit_fair_use" if reserve_entire else None, "Limit to fair-use quantity")
    results.append(r53); _emit_event(trace_id, r53, context)

    r54 = RuleResult(54, unusual_bulk, "flag_review" if unusual_bulk else None, "Flag for review")
    results.append(r54); _emit_event(trace_id, r54, context)

    r55 = RuleResult(55, customer_claims_mismatch, "trigger_reconciliation" if customer_claims_mismatch else None, "Trigger reconciliation audit")
    results.append(r55); _emit_event(trace_id, r55, context)

    r56 = RuleResult(56, stale_secs > 3600, "show_verify_at_checkout" if stale_secs > 3600 else None, "Stock data stale")
    results.append(r56); _emit_event(trace_id, r56, context)

    r57 = RuleResult(57, api_timeout, "inform_unavailable" if api_timeout else None, "Stock information temporarily unavailable")
    results.append(r57); _emit_event(trace_id, r57, context)

    r58 = RuleResult(58, conflicting, "use_most_conservative" if conflicting else None, "Use most conservative number")
    results.append(r58); _emit_event(trace_id, r58, context)

    r59 = RuleResult(59, sanctioned, "block_order" if sanctioned else None, "Block order - compliance")
    results.append(r59); _emit_event(trace_id, r59, context)

    r60 = RuleResult(60, high_fraud_combo, "require_verification" if high_fraud_combo else None, "Require verification for high fraud risk")
    results.append(r60); _emit_event(trace_id, r60, context)

    # Build a primary decision: prefer highest-priority escalation rule or a basic respond
    escalate_actions = {"hold_and_verify", "block_and_explain", "flag_for_review", "trigger_reconciliation", "block_order", "require_verification", "hold_and_alert_pricing"}
    primary = {
        "decision_id": decision_id,
        "sku": sku,
        "action": None,
        "message": None,
        "triggered_rules": [r.rule_id for r in results if r.triggered],
        "confidence": 1.0,
    }

    for r in results:
        if r.triggered and r.action in escalate_actions:
            primary["action"] = r.action
            primary["message"] = r.message
            break

    if not primary["action"]:
        for r in results:
            if r.triggered and r.action:
                primary["action"] = r.action
                primary["message"] = r.message
                break

    try:
        log_decision(
            agent_name="inventory_agent",
            input_data=context,
            retrieved_context={"rules_triggered": primary["triggered_rules"]},
            proposed_action={"action": primary["action"], "message": primary["message"]},
            agent_reasoning="deterministic_rules_v1",
        )
    except Exception:
        pass

    return {"trace_id": trace_id, "decision": primary, "rules": [r.__dict__ for r in results]}
