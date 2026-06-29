from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, List, Dict, Any
import uuid
import math
import json
from datetime import datetime, timezone

from sqlalchemy import text

from src.app.feature_flags import get_flags
from src.app.models.db import db_session
from src.app.services.decision_log import log_decision, log_trace_event
from src.app.security.observer import emit_security_event
from src.app.services.ticketing import TicketingAgent
from src.app.services.inventory_supplier_guard import (
    compute_supplier_trust_score,
    evaluate_dual_source_confirmation,
    evaluate_auto_po_policy,
)
from src.app.services.decision_bundle import write_immutable_decision_bundle
from src.app.security.authorization_engine import authorize_action
import os


def _get_inventory_thresholds() -> Dict[str, Any]:
    try:
        flags = get_flags()
        raw = flags.get("INVENTORY_THRESHOLDS", {}) if isinstance(flags.get("INVENTORY_THRESHOLDS"), dict) else {}
    except Exception:
        raw = {}

    def _f(key: str, default: float) -> float:
        try:
            return float(raw.get(key, default))
        except Exception:
            return default

    def _b(key: str, default: bool) -> bool:
        v = raw.get(key, default)
        if isinstance(v, bool):
            return v
        if isinstance(v, (int, float)):
            return bool(v)
        if isinstance(v, str):
            return v.strip().lower() in ("1", "true", "yes", "on")
        return default

    return {
        "reorder_cost_approval_usd": _f("reorder_cost_approval_usd", 5000.0),
        "reorder_cost_high_severity_usd": _f("reorder_cost_high_severity_usd", 10000.0),
        "data_readiness_min_score": _f("data_readiness_min_score", 0.8),
        "data_readiness_required": _b("data_readiness_required", True),
    }


@dataclass
class StockAlert:
    sku: str
    warehouse: str
    current_stock: int
    reorder_point: int
    alert_type: str  # 'low_stock' | 'out_of_stock' | 'overstock'


@dataclass
class ReorderRecommendation:
    sku: str
    supplier_id: Optional[str]
    quantity: int
    estimated_cost: float
    lead_time_days: int
    urgency: str  # 'normal' | 'urgent' | 'critical'
    forecast_daily_demand: float = 0.0
    forecast_variance: float = 0.0
    safety_stock: int = 0
    eoq_basis: str = "heuristic"
    requires_human_review_reason: Optional[str] = None
    supplier_trust_score: float = 0.7
    supplier_trust_band: str = "medium"
    anomaly_score: float = 0.0
    source_confirmations: Optional[Dict[str, Any]] = None


class InventoryAgent:
    """Inventory management agent responsible for monitoring and reorder decisions.

    This service is intentionally lightweight and uses the project's existing
    decision logging utilities so all recommendations are auditable.
    """

    def __init__(self):
        pass

    # STOCK_RULES: deterministic stock interaction rules (simplified)
    STOCK_RULES = {
        "R001": {"condition": "stock > 10", "action": "in_stock_message", "escalate": False},
        "R002": {"condition": "1 <= stock <= 10", "action": "limited_stock_message", "escalate": False},
        "R003": {"condition": "stock == 0 and reorder_active", "action": "backorder_message", "escalate": False},
        "R004": {"condition": "stock == 0 and not reorder_active", "action": "unavailable_suggest_alt", "escalate": False},
        "R005": {"condition": "product_status == 'discontinued'", "action": "discontinued_message", "escalate": False},
        "R006": {"condition": "reserved_for_orders", "action": "reserved_message", "escalate": False},
        "R007": {"condition": "in_transit", "action": "in_transit_message", "escalate": False},
        "R008": {"condition": "supplier_delay", "action": "supplier_delay_message", "escalate": True},
        "R009": {"condition": "promotion_active", "action": "promotion_limited_stock", "escalate": False},
        "R010": {"condition": "bundle_component", "action": "bundle_component_unavailable", "escalate": False},
        "R011": {"condition": "perishable and expiration_soon", "action": "expiration_notice", "escalate": False},
        "R012": {"condition": "fragile and low_stock", "action": "fragile_limited", "escalate": False},
        "R013": {"condition": "high_return_rate", "action": "quality_hold", "escalate": True},
        "R014": {"condition": "warehouse_capacity_low", "action": "warehouse_capacity_alert", "escalate": True},
        "R015": {"condition": "recall_active", "action": "recall_notice", "escalate": True},
        "R016": {"condition": "mislabelled_batch", "action": "qas_hold", "escalate": True},
        "R017": {"condition": "variant_discontinued", "action": "variant_discontinued_message", "escalate": False},
        "R018": {"condition": "reserved_for_b2b", "action": "b2b_reserved_message", "escalate": False},
        "R019": {"condition": "limited_edition", "action": "limited_edition_notice", "escalate": False},
        "R020": {"condition": "high_demand_forecast", "action": "preemptive_reorder", "escalate": False},
        "R021": {"condition": "customs_delay", "action": "customs_delay_message", "escalate": True},
        "R022": {"condition": "damaged_in_transit", "action": "damaged_notice", "escalate": True},
        "R023": {"condition": "expiration_passed", "action": "remove_from_sale", "escalate": True},
        "R024": {"condition": "high_reorder_cost", "action": "approval_required", "escalate": True},
        "R025": {"condition": "crossdock_only", "action": "crossdock_notice", "escalate": False},
        "R026": {"condition": "return_to_supplier", "action": "return_to_supplier", "escalate": True},
        "R027": {"condition": "allocated_to_project", "action": "allocated_notice", "escalate": False},
        "R028": {"condition": "preorder", "action": "preorder_message", "escalate": False},
        "R029": {"condition": "dropship_only", "action": "dropship_message", "escalate": False},
        "R030": {"condition": "manual_hold", "action": "manual_hold_notice", "escalate": True},
        "R031": {"condition": "fraud_hold", "action": "fraud_hold_notice", "escalate": True},
        "R032": {"condition": "high_value", "action": "high_value_approval", "escalate": True},
        "R033": {"condition": "requires_authorization", "action": "authorization_required", "escalate": True},
        "R034": {"condition": "restricted_item", "action": "restricted_item_message", "escalate": True},
        "R035": {"condition": "hazmat", "action": "hazmat_handling", "escalate": True},
        "R036": {"condition": "temperature_sensitive", "action": "temperature_handling", "escalate": True},
        "R037": {"condition": "assembled_on_demand", "action": "assembly_lead_time", "escalate": False},
        "R038": {"condition": "made_to_order", "action": "mto_message", "escalate": False},
        "R039": {"condition": "special_packaging", "action": "special_packaging_notice", "escalate": False},
        "R040": {"condition": "dangerous_goods", "action": "dangerous_goods_hold", "escalate": True},
        "R041": {"condition": "bulk_pack_only", "action": "bulk_pack_notice", "escalate": False},
        "R042": {"condition": "sample_only", "action": "sample_only_notice", "escalate": False},
        "R043": {"condition": "clearance", "action": "clearance_pricing", "escalate": False},
        "R044": {"condition": "flash_sale_only", "action": "flash_sale_reservation", "escalate": False},
        "R045": {"condition": "online_only", "action": "online_only_message", "escalate": False},
        "R046": {"condition": "high_return_rate_recent", "action": "inspect_recent_returns", "escalate": True},
        "R047": {"condition": "low_turnover", "action": "clearance_suggestion", "escalate": False},
        "R048": {"condition": "obsolete_variant", "action": "phase_out_notice", "escalate": False},
        "R049": {"condition": "supplier_on_hold", "action": "supplier_on_hold_message", "escalate": True},
        "R050": {"condition": "allocated_for_promotion", "action": "promo_allocation", "escalate": False},
    }

    def evaluate_stock_rule(self, sku: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """Evaluate a stock rule deterministically and return a small result dict.

        Returns: { rule_id, action, escalate, response }
        """
        stock = int(context.get("stock", 0) or 0)
        reorder_active = bool(context.get("reorder_active"))
        status = context.get("product_status", "active")

        # Check more specific flags first (Phase-3 deterministic rules)
        if status == "discontinued":
            return {"rule_id": "R005", "action": "discontinued_message", "escalate": False, "response": "This product is no longer available."}

        # Context-driven flags
        if context.get("reserved_for_orders"):
            return {"rule_id": "R006", "action": "reserved_message", "escalate": False, "response": "Stock reserved for outstanding orders."}
        if context.get("in_transit"):
            return {"rule_id": "R007", "action": "in_transit_message", "escalate": False, "response": "Stock is currently in transit to warehouse."}
        if context.get("supplier_delay"):
            return {"rule_id": "R008", "action": "supplier_delay_message", "escalate": True, "response": "Supplier delay detected; consider escalation."}
        if context.get("promotion_active") and stock <= 20:
            return {"rule_id": "R009", "action": "promotion_limited_stock", "escalate": False, "response": "Promotion active with limited stock."}
        if context.get("bundle_component") and stock <= 5:
            return {"rule_id": "R010", "action": "bundle_component_unavailable", "escalate": False, "response": "Bundle component low or unavailable."}
        if context.get("perishable") and context.get("expiration_soon"):
            return {"rule_id": "R011", "action": "expiration_notice", "escalate": False, "response": "Product expires soon; prioritize fulfillment."}
        if context.get("fragile") and stock <= 2:
            return {"rule_id": "R012", "action": "fragile_limited", "escalate": False, "response": "Fragile item with limited stock."}
        if context.get("high_return_rate"):
            return {"rule_id": "R013", "action": "quality_hold", "escalate": True, "response": "High return rate; quality check recommended."}
        if context.get("warehouse_capacity_low"):
            return {"rule_id": "R014", "action": "warehouse_capacity_alert", "escalate": True, "response": "Warehouse capacity low; consider redistribution."}
        if context.get("recall_active"):
            return {"rule_id": "R015", "action": "recall_notice", "escalate": True, "response": "Active recall; remove from sale."}
        if context.get("mislabelled_batch"):
            return {"rule_id": "R016", "action": "qas_hold", "escalate": True, "response": "Mislabel detected; QA hold."}
        if context.get("variant_discontinued"):
            return {"rule_id": "R017", "action": "variant_discontinued_message", "escalate": False, "response": "Variant has been discontinued."}
        if context.get("reserved_for_b2b"):
            return {"rule_id": "R018", "action": "b2b_reserved_message", "escalate": False, "response": "Stock reserved for B2B commitments."}
        if context.get("limited_edition"):
            return {"rule_id": "R019", "action": "limited_edition_notice", "escalate": False, "response": "Limited edition item; special handling."}
        if context.get("high_demand_forecast"):
            return {"rule_id": "R020", "action": "preemptive_reorder", "escalate": False, "response": "High forecast; consider preemptive reorder."}
        if context.get("customs_delay"):
            return {"rule_id": "R021", "action": "customs_delay_message", "escalate": True, "response": "Customs delay expected."}
        if context.get("damaged_in_transit"):
            return {"rule_id": "R022", "action": "damaged_notice", "escalate": True, "response": "Items damaged in transit."}
        if context.get("expiration_passed"):
            return {"rule_id": "R023", "action": "remove_from_sale", "escalate": True, "response": "Expired - remove from sale."}
        if context.get("high_reorder_cost"):
            return {"rule_id": "R024", "action": "approval_required", "escalate": True, "response": "High reorder cost; approval required."}
        if context.get("crossdock_only"):
            return {"rule_id": "R025", "action": "crossdock_notice", "escalate": False, "response": "Crossdock-only fulfillment."}
        if context.get("return_to_supplier"):
            return {"rule_id": "R026", "action": "return_to_supplier", "escalate": True, "response": "Returning stock to supplier."}
        if context.get("allocated_to_project"):
            return {"rule_id": "R027", "action": "allocated_notice", "escalate": False, "response": "Stock allocated to internal project."}
        if context.get("preorder"):
            return {"rule_id": "R028", "action": "preorder_message", "escalate": False, "response": "Product available for preorder."}
        if context.get("dropship_only"):
            return {"rule_id": "R029", "action": "dropship_message", "escalate": False, "response": "Dropship-only product."}
        if context.get("manual_hold"):
            return {"rule_id": "R030", "action": "manual_hold_notice", "escalate": True, "response": "Manual hold placed on this SKU."}
        if context.get("fraud_hold"):
            return {"rule_id": "R031", "action": "fraud_hold_notice", "escalate": True, "response": "Fraud hold on SKU; block fulfillment."}
        if context.get("high_value"):
            return {"rule_id": "R032", "action": "high_value_approval", "escalate": True, "response": "High value item - approval required."}
        if context.get("requires_authorization"):
            return {"rule_id": "R033", "action": "authorization_required", "escalate": True, "response": "Authorization required for sale."}
        if context.get("restricted_item"):
            return {"rule_id": "R034", "action": "restricted_item_message", "escalate": True, "response": "Restricted item - verify buyer eligibility."}
        if context.get("hazmat"):
            return {"rule_id": "R035", "action": "hazmat_handling", "escalate": True, "response": "Hazmat handling required."}
        if context.get("temperature_sensitive"):
            return {"rule_id": "R036", "action": "temperature_handling", "escalate": True, "response": "Temperature-sensitive item; special logistics."}
        if context.get("assembled_on_demand"):
            return {"rule_id": "R037", "action": "assembly_lead_time", "escalate": False, "response": "Assembled on demand - longer lead time."}
        if context.get("made_to_order"):
            return {"rule_id": "R038", "action": "mto_message", "escalate": False, "response": "Made-to-order item - lead time applies."}
        if context.get("special_packaging"):
            return {"rule_id": "R039", "action": "special_packaging_notice", "escalate": False, "response": "Special packaging requested."}
        if context.get("dangerous_goods"):
            return {"rule_id": "R040", "action": "dangerous_goods_hold", "escalate": True, "response": "Dangerous goods - compliance hold."}
        if context.get("bulk_pack_only"):
            return {"rule_id": "R041", "action": "bulk_pack_notice", "escalate": False, "response": "Sold in bulk packs only."}
        if context.get("sample_only"):
            return {"rule_id": "R042", "action": "sample_only_notice", "escalate": False, "response": "Sample-only item."}
        if context.get("clearance"):
            return {"rule_id": "R043", "action": "clearance_pricing", "escalate": False, "response": "Clearance pricing applies."}
        if context.get("flash_sale_only"):
            return {"rule_id": "R044", "action": "flash_sale_reservation", "escalate": False, "response": "Reserved for flash sale."}
        if context.get("online_only"):
            return {"rule_id": "R045", "action": "online_only_message", "escalate": False, "response": "Available online only."}
        if context.get("high_return_rate_recent"):
            return {"rule_id": "R046", "action": "inspect_recent_returns", "escalate": True, "response": "Recent high return rate - inspect stock."}
        if context.get("low_turnover"):
            return {"rule_id": "R047", "action": "clearance_suggestion", "escalate": False, "response": "Low turnover - consider clearance."}
        if context.get("obsolete_variant"):
            return {"rule_id": "R048", "action": "phase_out_notice", "escalate": False, "response": "Obsolete variant - phase out."}
        if context.get("supplier_on_hold"):
            return {"rule_id": "R049", "action": "supplier_on_hold_message", "escalate": True, "response": "Supplier is on hold - delay expected."}
        if context.get("allocated_for_promotion"):
            return {"rule_id": "R050", "action": "promo_allocation", "escalate": False, "response": "Allocated for upcoming promotion."}

        # Fallback to original stock-based rules
        if stock > 10:
            return {"rule_id": "R001", "action": "in_stock_message", "escalate": False, "response": f"In stock - ships within {context.get('lead_time', 2)} days"}
        if 1 <= stock <= 10:
            return {"rule_id": "R002", "action": "limited_stock_message", "escalate": False, "response": f"Limited stock - only {stock} remaining"}
        if stock == 0 and reorder_active:
            return {"rule_id": "R003", "action": "backorder_message", "escalate": False, "response": f"Temporarily out of stock - back in ~{context.get('eta_days',7)} days"}
        return {"rule_id": "R004", "action": "unavailable_suggest_alt", "escalate": False, "response": "Currently unavailable"}

    def monitor_stock_levels(self) -> List[StockAlert]:
        alerts: List[StockAlert] = []
        try:
            with db_session() as db:
                default_reorder_point = int(os.getenv("INVENTORY_DEFAULT_REORDER_POINT", "3") or 3)
                try:
                    rows = db.execute(
                        text(
                            """
                            SELECT p.sku, i.warehouse, i.stock, COALESCE(p.reorder_point, :default_rp) AS reorder_point, i.updated_at
                            FROM inventory i
                            JOIN products p ON i.product_id = p.id
                            WHERE i.stock <= COALESCE(p.reorder_point, :default_rp)
                            """
                        ),
                        {"default_rp": default_reorder_point},
                    ).fetchall()
                except Exception:
                    # Some deployments use product schemas without reorder_point.
                    rows = db.execute(
                        text(
                            """
                            SELECT p.sku, i.warehouse, i.stock, :default_rp AS reorder_point, i.updated_at
                            FROM inventory i
                            JOIN products p ON i.product_id = p.id
                            WHERE i.stock <= :default_rp
                            """
                        ),
                        {"default_rp": default_reorder_point},
                    ).fetchall()
                for r in rows:
                    sku = r[0]
                    warehouse = r[1]
                    stock = int(r[2] or 0)
                    reorder_point = int(r[3] or 0)
                    updated_at = r[4]
                    alert_type = "out_of_stock" if stock <= 0 else "low_stock"
                    alerts.append(StockAlert(sku=sku, warehouse=warehouse, current_stock=stock, reorder_point=reorder_point, alert_type=alert_type))
                    try:
                        from src.app.observability.metrics import record_inventory_alert
                        record_inventory_alert(alert_type)
                    except Exception:
                        pass
                    try:
                        if alert_type == "out_of_stock" and updated_at:
                            from src.app.observability.metrics import record_inventory_stockout_duration_hours
                            ts = self._coerce_datetime(updated_at)
                            if ts is not None:
                                hours = max(0.0, (datetime.now(timezone.utc) - ts).total_seconds() / 3600.0)
                                record_inventory_stockout_duration_hours(hours)
                    except Exception:
                        pass
                    # IsolationForest inventory anomaly (best-effort)
                    try:
                        from src.app.analytics.isolation_forest import score_inventory
                        # Extended features: stock velocity trend, daily variance, days-of-cover
                        feats = self._compute_inventory_features(sku, stock, reorder_point)
                        isf = score_inventory(feats)
                        if isinstance(isf, dict):
                            cal = self._calibrate_inventory_anomaly(float(isf.get("score") or 0.0))
                            label = str(isf.get("label") or "")
                            sev = cal.get("severity")
                            if label in ("medium", "high") or sev in ("high", "critical"):
                                try:
                                    from src.app.observability.metrics import record_inventory_anomaly_severity
                                    record_inventory_anomaly_severity(str(sev or label or "unknown"))
                                except Exception:
                                    pass
                                try:
                                    log_trace_event(
                                        trace_id=str(uuid.uuid4()),
                                        event_type="inventory_anomaly",
                                        source_type="agent",
                                        source_id="inventory_agent",
                                        target_type="sku",
                                        target_id=sku,
                                        payload={
                                            "score": isf.get("score"),
                                            "label": isf.get("label"),
                                            "features": feats,
                                            "calibrated_confidence": cal.get("calibrated_confidence"),
                                            "severity": sev,
                                        },
                                    )
                                except Exception:
                                    pass
                    except Exception:
                        pass
        except Exception:
            # Best-effort: return what we have
            pass
        return alerts

    def _coerce_datetime(self, raw: Any) -> Optional[datetime]:
        try:
            if isinstance(raw, datetime):
                dt = raw
            else:
                txt = str(raw or "").strip()
                if not txt:
                    return None
                dt = datetime.fromisoformat(txt.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except Exception:
            return None

    def _calibrate_inventory_anomaly(self, raw_score: float) -> Dict[str, Any]:
        # Logistic calibration: p_hat = sigma(a * p + b)
        a = float(os.environ.get("INV_ANOMALY_CAL_A", "1.0") or 1.0)
        b = float(os.environ.get("INV_ANOMALY_CAL_B", "0.0") or 0.0)
        p = 1.0 / (1.0 + math.exp(-(a * float(raw_score) + b)))
        if p >= 0.90:
            sev = "critical"
        elif p >= 0.75:
            sev = "high"
        elif p >= 0.50:
            sev = "medium"
        else:
            sev = "low"
        return {"calibrated_confidence": p, "severity": sev}

    def _compute_inventory_features(self, sku: str, current_stock: int, reorder_point: int) -> Dict[str, float]:
        # Compute EWMA daily sales, velocity trend (last-first), variance, and days-of-cover
        days = int(os.environ.get("INV_EWMA_DAYS", "30") or 30)
        alpha = float(os.environ.get("INV_EWMA_ALPHA", "0.3") or 0.3)
        sales: List[int] = []
        try:
            with db_session() as db:
                dialect = str(getattr(getattr(db, "bind", None), "dialect", None).name or "").lower()
                if "postgres" in dialect:
                    sql = (
                        "SELECT date(o.created_at) as d, count(*) as daily_sales "
                        "FROM order_items oi JOIN orders o ON o.id = oi.order_id "
                        "WHERE oi.sku = :sku AND o.created_at >= (CURRENT_DATE - (:days * INTERVAL '1 day')) "
                        "GROUP BY date(o.created_at) ORDER BY date(o.created_at) ASC"
                    )
                    rows = db.execute(text(sql), {"sku": sku, "days": max(1, int(days))}).fetchall()
                else:
                    sql = (
                        "SELECT date(o.created_at) as d, count(*) as daily_sales "
                        "FROM order_items oi JOIN orders o ON o.id = oi.order_id "
                        "WHERE oi.sku = :sku AND datetime(o.created_at) >= datetime('now', :window) "
                        "GROUP BY date(o.created_at) ORDER BY date(o.created_at) ASC"
                    )
                    rows = db.execute(text(sql), {"sku": sku, "window": f"-{max(1, int(days))} days"}).fetchall()
                sales = [int(r[1] or 0) for r in rows] if rows else []
        except Exception:
            sales = []
        # EWMA average
        avg_daily = 1.0
        if sales:
            s = float(sales[0])
            for x in sales[1:]:
                s = alpha * float(x) + (1.0 - alpha) * s
            avg_daily = max(0.1, s)
        # Trend and variance
        try:
            velocity_trend = float((sales[-1] - sales[0])) if len(sales) >= 2 else 0.0
        except Exception:
            velocity_trend = 0.0
        try:
            import statistics as _st
            daily_variance = float(_st.pvariance(sales)) if len(sales) >= 2 else 0.0
        except Exception:
            daily_variance = 0.0
        days_of_cover = float(current_stock) / float(avg_daily or 0.1)
        ratio = float(current_stock) / float(reorder_point or 1)
        return {
            "current_stock": float(current_stock),
            "reorder_point": float(reorder_point),
            "ratio": ratio,
            "avg_daily_sales_ewma": float(avg_daily),
            "velocity_trend": float(velocity_trend),
            "daily_variance": float(daily_variance),
            "days_of_cover": float(days_of_cover),
        }

    def _get_sales_series(self, sku: str, days: int = 45) -> List[int]:
        try:
            with db_session() as db:
                dialect = str(getattr(getattr(db, "bind", None), "dialect", None).name or "").lower()
                if "postgres" in dialect:
                    sql = (
                        "SELECT date(o.created_at) as d, count(*) as daily_sales "
                        "FROM order_items oi JOIN orders o ON o.id = oi.order_id "
                        "WHERE oi.sku = :sku AND o.created_at >= (CURRENT_DATE - (:days * INTERVAL '1 day')) "
                        "GROUP BY date(o.created_at) ORDER BY date(o.created_at) ASC"
                    )
                    rows = db.execute(text(sql), {"sku": sku, "days": max(1, int(days))}).fetchall()
                else:
                    sql = (
                        "SELECT date(o.created_at) as d, count(*) as daily_sales "
                        "FROM order_items oi JOIN orders o ON o.id = oi.order_id "
                        "WHERE oi.sku = :sku AND datetime(o.created_at) >= datetime('now', :window) "
                        "GROUP BY date(o.created_at) ORDER BY date(o.created_at) ASC"
                    )
                    rows = db.execute(text(sql), {"sku": sku, "window": f"-{max(1, int(days))} days"}).fetchall()
                return [int(r[1] or 0) for r in rows] if rows else []
        except Exception:
            return []

    def _forecast_daily_demand(self, sku: str) -> Dict[str, Any]:
        import statistics as _st

        use_hardened_pipeline = str(os.environ.get("INV_FORECAST_PIPELINE", "0")).strip().lower() in ("1", "true", "yes", "on")
        if use_hardened_pipeline:
            try:
                from src.app.services.demand_forecast import DemandForecaster

                fc = DemandForecaster().forecast_sku(sku, horizon_days=14)
                means = [float((d or {}).get("mean") or 0.0) for d in (fc.daily or [])]
                if means:
                    avg = float(sum(means) / float(max(1, len(means))))
                    std = float(_st.pstdev(means)) if len(means) >= 2 else 0.0
                    cv = float(std / max(0.1, avg))
                    mape = ((fc.meta or {}).get("mape_proxy") if isinstance(fc.meta, dict) else None)
                    return {
                        "method": str((fc.meta or {}).get("method") or "hardened_pipeline"),
                        "daily_demand": avg,
                        "std_daily": std,
                        "variance": float(std * std),
                        "high_variance": bool(cv > float(os.environ.get("INV_FORECAST_MAX_CV", "1.2") or 1.2)),
                        "cv": cv,
                        "mape": mape,
                        "quarantined_points": int(((fc.meta or {}).get("quarantined_points") or 0)),
                        "poison_guard": (fc.meta or {}).get("poison_guard"),
                    }
            except Exception:
                pass

        days = int(os.environ.get("INV_FORECAST_DAYS", "45") or 45)
        alpha = float(os.environ.get("INV_EWMA_ALPHA", "0.3") or 0.3)
        max_cv = float(os.environ.get("INV_FORECAST_MAX_CV", "1.2") or 1.2)
        series = self._get_sales_series(sku, days=days)
        if not series:
            return {
                "method": "default",
                "daily_demand": 1.0,
                "std_daily": 1.0,
                "variance": 1.0,
                "high_variance": False,
                "mape": None,
            }

        ewma = float(series[0])
        for x in series[1:]:
            ewma = alpha * float(x) + (1.0 - alpha) * ewma
        avg_daily = max(0.1, float(ewma))
        std_daily = float(_st.pstdev(series)) if len(series) >= 2 else 0.0
        variance = float(std_daily * std_daily)
        method = "ewma"

        use_arima = str(os.environ.get("INV_FORECAST_ARIMA", "0")).strip().lower() in ("1", "true", "yes", "on")
        if use_arima and len(series) >= 12:
            try:
                from statsmodels.tsa.arima.model import ARIMA  # type: ignore

                m = ARIMA(series, order=(1, 1, 1))
                fit = m.fit()
                pred = float(fit.forecast(steps=1)[0])
                avg_daily = max(0.1, pred)
                method = "arima"
            except Exception:
                pass

        try:
            mape_vals: List[float] = []
            smoothed = float(series[0])
            for actual in series[1:]:
                forecast = max(0.1, smoothed)
                if actual > 0:
                    mape_vals.append(abs(float(actual) - forecast) / float(actual))
                smoothed = alpha * float(actual) + (1.0 - alpha) * smoothed
            mape = (sum(mape_vals) / len(mape_vals)) if mape_vals else None
        except Exception:
            mape = None
        try:
            if mape is not None:
                from src.app.observability.metrics import record_inventory_forecast_error_mape
                record_inventory_forecast_error_mape(float(mape))
        except Exception:
            pass

        cv = float(std_daily / max(0.1, avg_daily))
        high_variance = bool(cv > max_cv)
        return {
            "method": method,
            "daily_demand": float(avg_daily),
            "std_daily": float(std_daily),
            "variance": float(variance),
            "high_variance": high_variance,
            "cv": cv,
            "mape": mape,
        }

    def _get_best_supplier(self, sku: str) -> Dict[str, Any]:
        # Enhanced supplier ranking: score suppliers by cost, lead time, MOQ, on-time rate, reliability and SLA penalties.
        try:
            with db_session() as db:
                try:
                    rows = db.execute(
                        text(
                            """
                            SELECT s.id, s.unit_cost, s.lead_time_days, COALESCE(s.moq, 0) as moq,
                                   COALESCE(s.on_time_rate,0) as on_time_rate,
                                   COALESCE(s.reliability_score,0) as reliability,
                                   COALESCE(s.recent_sla_breaches, 0) as recent_sla_breaches,
                                   COALESCE(s.late_deliveries_30d, 0) as late_deliveries_30d
                            FROM suppliers s
                            JOIN supplier_products sp ON sp.supplier_id = s.id
                            WHERE sp.sku = :sku AND COALESCE(s.active,1)=1 AND COALESCE(sp.active,1)=1
                            """
                        ),
                        {"sku": sku},
                    ).fetchall()
                except Exception:
                    rows = db.execute(
                        text(
                            """
                            SELECT s.id, s.unit_cost, s.lead_time_days, COALESCE(s.moq, 0) as moq,
                                   COALESCE(s.on_time_rate,0) as on_time_rate,
                                   COALESCE(s.reliability_score,0) as reliability,
                                   0 as recent_sla_breaches, 0 as late_deliveries_30d
                            FROM suppliers s
                            JOIN supplier_products sp ON sp.supplier_id = s.id
                            WHERE sp.sku = :sku AND COALESCE(s.active,1)=1 AND COALESCE(sp.active,1)=1
                            """
                        ),
                        {"sku": sku},
                    ).fetchall()
                if not rows:
                    return {"id": None, "unit_cost": 0.0, "lead_time": 7}

                # Normalize and score
                costs = [float(r[1] or 0.0) for r in rows]
                leads = [int(r[2] or 7) for r in rows]
                moqs = [int(r[3] or 0) for r in rows]

                min_cost, max_cost = min(costs), max(costs)
                min_lead, max_lead = min(leads), max(leads)
                min_moq, max_moq = min(moqs), max(moqs) if moqs else (0, 0)

                best = None
                best_score = -9999.0
                # weights (configurable later)
                w_cost = 0.4
                w_lead = 0.25
                w_on_time = 0.2
                w_reliability = 0.1
                w_moq = 0.05
                w_penalty = 0.15

                for idx, r in enumerate(rows):
                    sid = r[0]
                    cost = float(r[1] or 0.0)
                    lead = int(r[2] or 7)
                    moq = int(r[3] or 0)
                    on_time = float(r[4] or 0.0)
                    rel = float(r[5] or 0.0)
                    sla_breaches = int(r[6] or 0)
                    late_deliveries = int(r[7] or 0)

                    # normalize (avoid divide by zero)
                    norm_cost = 1.0 if max_cost == min_cost else (cost - min_cost) / (max_cost - min_cost)
                    norm_lead = 1.0 if max_lead == min_lead else (lead - min_lead) / (max_lead - min_lead)
                    norm_moq = 1.0 if max_moq == min_moq else (moq - min_moq) / (max_moq - min_moq) if max_moq > 0 else 0.0
                    norm_on_time = max(0.0, min(1.0, on_time))
                    norm_rel = max(0.0, min(1.0, rel))
                    penalty = min(1.0, 0.15 * float(sla_breaches) + 0.05 * float(late_deliveries))

                    # lower cost/lead/moq is better, higher on_time/reliability is better
                    score = (
                        w_cost * (1.0 - norm_cost)
                        + w_lead * (1.0 - norm_lead)
                        + w_on_time * norm_on_time
                        + w_reliability * norm_rel
                        + w_moq * (1.0 - norm_moq)
                        - w_penalty * penalty
                    )
                    self._persist_supplier_score_audit(
                        sku=sku,
                        supplier_id=str(sid),
                        score=score,
                        payload={
                            "unit_cost": cost,
                            "lead_time": lead,
                            "moq": moq,
                            "on_time_rate": on_time,
                            "reliability": rel,
                            "recent_sla_breaches": sla_breaches,
                            "late_deliveries_30d": late_deliveries,
                            "penalty": penalty,
                        },
                    )
                    if score > best_score:
                        trust = compute_supplier_trust_score(
                            signature_validity=1.0 if rel >= 0.5 else 0.5,
                            historical_defect_rate=max(0.0, min(1.0, 1.0 - max(0.0, min(1.0, rel)))),
                            lead_time_variance=max(0.0, min(1.0, float(late_deliveries) / 20.0)),
                            invoice_mismatch_rate=max(0.0, min(1.0, float(sla_breaches) / 15.0)),
                        )
                        best_score = score
                        best = {
                            "id": sid,
                            "unit_cost": cost,
                            "lead_time": lead,
                            "moq": moq,
                            "on_time_rate": on_time,
                            "reliability": rel,
                            "score": score,
                            "recent_sla_breaches": sla_breaches,
                            "late_deliveries_30d": late_deliveries,
                            "penalty": penalty,
                            "supplier_trust_score": trust.get("supplier_trust_score"),
                            "supplier_trust_band": trust.get("band"),
                            "supplier_trust_components": trust.get("components"),
                        }
                if best:
                    return best
        except Exception:
            pass
        return {"id": None, "unit_cost": 0.0, "lead_time": 7}

    def _rank_suppliers(self, sku: str, top_n: int = 3) -> List[Dict[str, Any]]:
        """Read-only top-N approved suppliers for a SKU, scored with the same weights as
        _get_best_supplier (no audit write — this is a review PREVIEW, not the draft path). Returns [] when
        no supplier carries the SKU. Used by the supplier-contact candidates agent."""
        try:
            with db_session() as db:
                rows = db.execute(
                    text("SELECT s.id, s.unit_cost, s.lead_time_days, COALESCE(s.moq,0), "
                         "COALESCE(s.on_time_rate,0), COALESCE(s.reliability_score,0), "
                         "COALESCE(s.recent_sla_breaches,0), COALESCE(s.late_deliveries_30d,0) "
                         "FROM suppliers s JOIN supplier_products sp ON sp.supplier_id=s.id "
                         "WHERE sp.sku=:sku AND COALESCE(s.active,1)=1 AND COALESCE(sp.active,1)=1"),
                    {"sku": str(sku)},
                ).fetchall()
        except Exception:
            return []
        if not rows:
            return []
        costs = [float(r[1] or 0.0) for r in rows]
        leads = [int(r[2] or 7) for r in rows]
        moqs = [int(r[3] or 0) for r in rows]
        min_cost, max_cost = min(costs), max(costs)
        min_lead, max_lead = min(leads), max(leads)
        min_moq, max_moq = min(moqs), max(moqs)
        out: List[Dict[str, Any]] = []
        for r in rows:
            cost, lead, moq = float(r[1] or 0.0), int(r[2] or 7), int(r[3] or 0)
            on_time, rel = float(r[4] or 0.0), float(r[5] or 0.0)
            sla, late = int(r[6] or 0), int(r[7] or 0)
            nc = 1.0 if max_cost == min_cost else (cost - min_cost) / (max_cost - min_cost)
            nl = 1.0 if max_lead == min_lead else (lead - min_lead) / (max_lead - min_lead)
            nm = 0.0 if max_moq == min_moq else (moq - min_moq) / (max_moq - min_moq)
            pen = min(1.0, 0.15 * sla + 0.05 * late)
            score = (0.4 * (1.0 - nc) + 0.25 * (1.0 - nl) + 0.2 * max(0.0, min(1.0, on_time))
                     + 0.1 * max(0.0, min(1.0, rel)) + 0.05 * (1.0 - nm) - 0.15 * pen)
            out.append({"id": r[0], "unit_cost": cost, "lead_time": lead, "moq": moq,
                        "on_time_rate": on_time, "reliability": rel, "recent_sla_breaches": sla,
                        "late_deliveries_30d": late, "score": round(score, 4)})
        out.sort(key=lambda c: -c["score"])
        return out[: max(1, int(top_n))]

    def _persist_supplier_score_audit(self, sku: str, supplier_id: str, score: float, payload: Dict[str, Any]) -> None:
        try:
            with db_session() as db:
                try:
                    db.execute(
                        text(
                            """
                            CREATE TABLE IF NOT EXISTS supplier_score_audits (
                                id TEXT PRIMARY KEY,
                                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                                sku TEXT,
                                supplier_id TEXT,
                                score REAL,
                                payload TEXT
                            )
                            """
                        )
                    )
                except Exception:
                    pass
                db.execute(
                    text(
                        """
                        INSERT INTO supplier_score_audits (id, sku, supplier_id, score, payload)
                        VALUES (:id, :sku, :supplier_id, :score, :payload)
                        """
                    ),
                    {
                        "id": str(uuid.uuid4()),
                        "sku": sku,
                        "supplier_id": supplier_id,
                        "score": float(score),
                        "payload": str(payload),
                    },
                )
                try:
                    db.commit()
                except Exception:
                    pass
        except Exception:
            pass

    def _calculate_eoq(self, sku: str, supplier: Dict[str, Any], forecast: Dict[str, Any]) -> Dict[str, Any]:
        # EOQ with constraints:
        # Q* = sqrt(2 * K * D / h), SS = z * sigma_L
        order_cost_k = float(os.environ.get("INV_ORDER_COST_K", "60") or 60.0)
        holding_cost_h = float(os.environ.get("INV_HOLDING_COST_H", "8") or 8.0)
        service_level_z = float(os.environ.get("INV_SERVICE_LEVEL_Z", "1.65") or 1.65)

        avg_daily = float(forecast.get("daily_demand") or 1.0)
        std_daily = float(forecast.get("std_daily") or 1.0)
        lead = int(supplier.get("lead_time", 7) or 7)
        moq = int(supplier.get("moq", 0) or 0)
        annual_demand = max(1.0, avg_daily * 365.0)
        if holding_cost_h <= 0:
            base = avg_daily * float(max(1, lead))
        else:
            base = math.sqrt(max(1.0, (2.0 * order_cost_k * annual_demand) / max(0.01, holding_cost_h)))
        sigma_l = std_daily * math.sqrt(max(1.0, float(lead)))
        safety_stock = max(0, int(math.ceil(service_level_z * sigma_l)))
        qty = int(math.ceil(base + safety_stock))
        if moq > 0:
            qty = max(qty, moq)
        qty = max(1, qty)
        return {
            "qty": qty,
            "base": float(base),
            "safety_stock": int(safety_stock),
            "annual_demand": float(annual_demand),
            "method": str(forecast.get("method") or "eoq"),
        }

    def _determine_urgency(self, alert: StockAlert) -> str:
        if alert.current_stock == 0:
            return "critical"
        # If current_stock less than half of reorder_point -> urgent
        try:
            if alert.reorder_point and alert.current_stock <= (alert.reorder_point // 2):
                return "urgent"
        except Exception:
            pass
        return "normal"

    def generate_reorder_recommendations(self, alerts: List[StockAlert]) -> List[ReorderRecommendation]:
        thr = _get_inventory_thresholds()
        approval_min = float(thr["reorder_cost_approval_usd"])
        high_sev_min = float(thr["reorder_cost_high_severity_usd"])
        variance_gate = float(os.environ.get("INV_FORECAST_MAX_CV", "1.2") or 1.2)
        recs: List[ReorderRecommendation] = []
        for a in alerts:
            supplier = self._get_best_supplier(a.sku)
            forecast = self._forecast_daily_demand(a.sku)
            eoq = self._calculate_eoq(a.sku, supplier, forecast)
            qty = int(eoq.get("qty") or 1)
            urgency = self._determine_urgency(a)
            est_cost = float(qty * (supplier.get("unit_cost") or 0.0))
            variance_reason = None
            if bool(forecast.get("high_variance")) or float(forecast.get("cv") or 0.0) > variance_gate:
                variance_reason = "forecast_variance_high"
            anomaly_score = min(1.0, max(0.0, float(forecast.get("cv") or 0.0) / max(0.1, variance_gate)))
            supplier_trust_score = float(supplier.get("supplier_trust_score") or 0.7)
            supplier_trust_band = str(supplier.get("supplier_trust_band") or "medium")
            rec = ReorderRecommendation(
                sku=a.sku,
                supplier_id=supplier.get("id"),
                quantity=qty,
                estimated_cost=est_cost,
                lead_time_days=int(supplier.get("lead_time", 7)),
                urgency=urgency,
                forecast_daily_demand=float(forecast.get("daily_demand") or 0.0),
                forecast_variance=float(forecast.get("variance") or 0.0),
                safety_stock=int(eoq.get("safety_stock") or 0),
                eoq_basis=str(eoq.get("method") or "eoq"),
                requires_human_review_reason=variance_reason,
                supplier_trust_score=supplier_trust_score,
                supplier_trust_band=supplier_trust_band,
                anomaly_score=anomaly_score,
            )
            recs.append(rec)

            # Log decision in the central decision log for auditability
            try:
                approval_needed = rec.estimated_cost > approval_min or bool(variance_reason)
                auto_po_policy = evaluate_auto_po_policy(
                    amount=rec.estimated_cost,
                    supplier_risk=(1.0 - supplier_trust_score),
                    anomaly_score=anomaly_score,
                )
                if auto_po_policy.get("decision") in ("challenge", "escalate"):
                    approval_needed = True
                dec_id = log_decision(
                    agent_name="inventory_agent",
                    input_data={"sku": a.sku, "current_stock": a.current_stock, "reorder_point": a.reorder_point},
                    retrieved_context={
                        "warehouse": a.warehouse,
                        "forecast": forecast,
                        "supplier_score": supplier.get("score"),
                        "supplier_penalty": supplier.get("penalty"),
                        "supplier_trust_score": supplier_trust_score,
                        "supplier_trust_band": supplier_trust_band,
                        "supplier_trust_components": supplier.get("supplier_trust_components"),
                        "auto_po_policy": auto_po_policy,
                    },
                    proposed_action={"reorder": rec.__dict__},
                    agent_reasoning=f"EOQ policy: lead={rec.lead_time_days}, annual_demand={eoq.get('annual_demand')}",
                    policy_version="v1",
                    approval_required=approval_needed,
                )
                # Attach a trace event for the recommendation
                try:
                    if dec_id:
                        log_trace_event(trace_id=dec_id, event_type="reorder_recommendation", source_type="agent", source_id="inventory_agent", target_type="supplier", target_id=str(supplier.get("id")), payload={"recommendation": rec.__dict__})
                except Exception:
                    pass
                # If approval is required, auto-create a ticket and link it to the decision
                if approval_needed:
                    try:
                        tagent = TicketingAgent()
                        title = f"Approval request: reorder {rec.sku} qty={rec.quantity}"
                        desc = (
                            f"Auto-created approval request for reorder recommendation. estimated_cost={rec.estimated_cost}, "
                            f"supplier={rec.supplier_id}, urgency={rec.urgency}, reason={variance_reason or 'cost_threshold'}"
                        )
                        severity = "high" if rec.estimated_cost > high_sev_min else "medium"
                        ticket = tagent.create_ticket(title=title, description=desc, severity=severity, trace_id=dec_id, approval_required=True)
                        try:
                            if dec_id and ticket:
                                # attach ticket id to the recommendation for API consumers
                                try:
                                    setattr(rec, "ticket_id", ticket.id)
                                except Exception:
                                    rec.__dict__["ticket_id"] = ticket.id
                                log_trace_event(trace_id=dec_id, event_type="ticket_created", source_type="agent", source_id="inventory_agent", target_type="ticket", target_id=str(ticket.id), payload={"ticket_id": ticket.id, "status": ticket.status})
                        except Exception:
                            pass
                        try:
                            from src.app.observability.metrics import record_inventory_reorder_action
                            record_inventory_reorder_action("approval_required", variance_reason or "cost_threshold")
                        except Exception:
                            pass
                    except Exception:
                        pass
                # Supplier change candidate ticket (PB-INV-002 trigger)
                try:
                    if (supplier.get("on_time_rate", 1.0) or 1.0) < 0.6 or (supplier.get("reliability", 1.0) or 1.0) < 0.6:
                        tagent = TicketingAgent()
                        title = f"Supplier change candidate: {a.sku}"
                        desc = f"On-time={supplier.get('on_time_rate')}, reliability={supplier.get('reliability')}. Consider PB-INV-002 trigger."
                        severity = "medium"
                        t2 = tagent.create_ticket(title=title, description=desc, severity=severity, trace_id=dec_id, approval_required=False)
                        try:
                            if dec_id and t2:
                                log_trace_event(trace_id=dec_id, event_type="ticket_created", source_type="agent", source_id="inventory_agent", target_type="ticket", target_id=str(t2.id), payload={"ticket_id": t2.id, "topic": "supplier_change"})
                        except Exception:
                            pass
                except Exception:
                    pass
            except Exception:
                pass

            # Emit a security-observer event (best-effort) to surface large purchases
            try:
                if rec.estimated_cost and rec.estimated_cost > high_sev_min:
                    emit_security_event(path="/inventory/reorder", payload={"sku": a.sku, "estimated_cost": rec.estimated_cost, "quantity": rec.quantity})
            except Exception:
                pass
            try:
                from src.app.observability.metrics import record_inventory_reorder_action
                record_inventory_reorder_action("recommended", "ok")
            except Exception:
                pass

        return recs

    def suggest_rebalancing_transfers(self, max_suggestions: int = 10, min_days_cover_gap: float = 7.0) -> List[Dict[str, Any]]:
        suggestions: List[Dict[str, Any]] = []
        try:
            with db_session() as db:
                rows = db.execute(
                    text(
                        """
                        SELECT p.sku, COALESCE(i.warehouse, 'default') as warehouse, COALESCE(i.stock, 0) as stock
                        FROM inventory i
                        JOIN products p ON p.id = i.product_id
                        ORDER BY p.sku, warehouse
                        """
                    )
                ).fetchall()
        except Exception:
            rows = []

        by_sku: Dict[str, List[Dict[str, Any]]] = {}
        for r in rows or []:
            sku = str(r[0] or "")
            by_sku.setdefault(sku, []).append({"warehouse": str(r[1] or "default"), "stock": int(r[2] or 0)})

        for sku, items in by_sku.items():
            if len(items) < 2:
                continue
            demand = self._forecast_daily_demand(sku)
            daily = max(0.1, float(demand.get("daily_demand") or 0.1))
            sorted_items = sorted(items, key=lambda x: int(x["stock"]))
            low = sorted_items[0]
            high = sorted_items[-1]
            low_cover = float(low["stock"]) / daily
            high_cover = float(high["stock"]) / daily
            gap = high_cover - low_cover
            if gap < float(min_days_cover_gap) or int(high["stock"]) <= 1:
                continue

            transfer_qty = int(max(1, min(int(high["stock"]) // 3, math.ceil((gap * daily) / 2.0))))
            sug = {
                "sku": sku,
                "from_warehouse": str(high["warehouse"]),
                "to_warehouse": str(low["warehouse"]),
                "quantity": transfer_qty,
                "from_days_cover": round(high_cover, 2),
                "to_days_cover": round(low_cover, 2),
                "cover_gap_days": round(gap, 2),
                "reason": "days_of_cover_imbalance",
            }
            suggestions.append(sug)
            try:
                tid = str(uuid.uuid4())
                log_trace_event(
                    trace_id=tid,
                    event_type="inventory_rebalance_suggestion",
                    source_type="agent",
                    source_id="inventory_agent",
                    target_type="sku",
                    target_id=sku,
                    payload=sug,
                )
            except Exception:
                pass
            try:
                from src.app.observability.metrics import record_inventory_transfer_suggestion
                record_inventory_transfer_suggestion("suggested")
            except Exception:
                pass

            if len(suggestions) >= max_suggestions:
                break
        return suggestions

    def execute_reorder(self, recommendation: ReorderRecommendation, approval: Optional[str] = None) -> Dict[str, Any]:
        thr = _get_inventory_thresholds()
        approval_min = float(thr["reorder_cost_approval_usd"])
        trust_score = float(getattr(recommendation, "supplier_trust_score", 0.7) or 0.7)
        trust_band = str(getattr(recommendation, "supplier_trust_band", "medium") or "medium")
        anomaly_score = float(getattr(recommendation, "anomaly_score", 0.0) or 0.0)
        confirmations = getattr(recommendation, "source_confirmations", None) or {}
        dual_confirm = evaluate_dual_source_confirmation(confirmations)
        policy_gate = evaluate_auto_po_policy(
            amount=float(getattr(recommendation, "estimated_cost", 0.0) or 0.0),
            supplier_risk=(1.0 - trust_score),
            anomaly_score=anomaly_score,
        )

        # ── Unified Authorization Engine gate (Tier-1 control) ──
        # This is the genuinely AUTONOMOUS supplier-order decision, so it carries
        # an agent lane (requester="Inventory_Agent"). In shadow mode the verdict
        # is logged + traced but NOT enforced (should_block() is always False), so
        # the existing gates below remain authoritative until this action is flipped
        # to active via AUTHZ_ENGINE_MODE. authorize_action never raises.
        _est_cost = float(getattr(recommendation, "estimated_cost", 0.0) or 0.0)
        _conditions: List[str] = []
        if trust_band == "low" or trust_score < 0.5:
            _conditions.append("supplier_unverified")
        _authz = authorize_action(
            "supplier_order",
            requester="Inventory_Agent",
            value_usd=_est_cost,
            conditions=_conditions,
            subject_id=str(getattr(recommendation, "supplier_id", "") or getattr(recommendation, "sku", "") or ""),
            idempotency_key=f"reorder:{getattr(recommendation, 'sku', '')}:{_est_cost}",
            metadata={"urgency": getattr(recommendation, "urgency", ""), "anomaly_score": anomaly_score},
        )
        if _authz.should_block():  # inert in shadow; enforces once flipped to active
            return {
                "status": "blocked_by_authorization_engine",
                "reason": _authz.reason,
                "terminal_outcome": _authz.terminal_outcome,
                "residual": _authz.residual,
            }

        # Enforce supplier trust and policy gates before downstream execution/data thresholds.
        if trust_band == "low" or trust_score < 0.5:
            try:
                log_trace_event(
                    trace_id=str(uuid.uuid4()),
                    event_type="policy_gate",
                    source_type="agent",
                    source_id="Inventory_Supplier_Guard_Agent",
                    target_type="supplier",
                    target_id=str(getattr(recommendation, "supplier_id", "") or ""),
                    payload={
                        "decision": "quarantine",
                        "reason_codes": ["supplier_trust_low"],
                        "supplier_trust_score": trust_score,
                        "supplier_trust_band": trust_band,
                    },
                )
            except Exception:
                pass
            return {
                "status": "quarantined_supplier_update",
                "reason": "supplier_trust_low",
                "supplier_trust_score": trust_score,
                "supplier_trust_band": trust_band,
            }
        critical_restock = bool(
            getattr(recommendation, "urgency", "") == "critical"
            or float(getattr(recommendation, "estimated_cost", 0.0) or 0.0) > (approval_min * 1.5)
        )
        if critical_restock and not dual_confirm.get("ok"):
            return {
                "status": "challenge_required",
                "reason": "dual_source_confirmation_missing",
                "missing": dual_confirm.get("missing"),
                "confirmations_seen": dual_confirm.get("count"),
            }
        if policy_gate.get("decision") == "escalate":
            return {
                "status": "approval_required",
                "reason": "auto_po_policy_escalate",
                "risk_score": policy_gate.get("risk_score"),
                "reason_codes": policy_gate.get("reason_codes"),
                "supplier_trust_score": trust_score,
            }

        # Data readiness gate: block autonomous reorder when data is missing/stale/conflicting.
        required = bool(thr.get("data_readiness_required", True))
        min_score = float(thr.get("data_readiness_min_score", 0.8))

        # Back-compat env overrides (kept so ops can hotfix without editing JSON).
        try:
            env_required = os.getenv("INVENTORY_DATA_READINESS_REQUIRED")
            if env_required is not None:
                required = str(env_required).strip().lower() in ("1", "true", "yes", "on")
        except Exception:
            pass
        try:
            env_min = os.getenv("INVENTORY_DATA_READINESS_MIN_SCORE")
            if env_min is not None:
                min_score = float(env_min or min_score)
        except Exception:
            pass
        if required:
            try:
                from src.app.data_readiness.report import compute_inventory_readiness

                rep = compute_inventory_readiness()
                if float(rep.score) < float(min_score):
                    ticket_id = None
                    try:
                        tagent = TicketingAgent()
                        title = f"Data readiness not met for reorder: {recommendation.sku}"
                        desc = f"Readiness score={rep.score} level={rep.level}. Run PB-DATA-001. Summary={rep.summary}"
                        sev = "high" if rep.level == "bad" else "medium"
                        t = tagent.create_ticket(title=title, description=desc, severity=sev, trace_id=None, approval_required=False)
                        ticket_id = getattr(t, "id", None)
                    except Exception:
                        ticket_id = None
                    try:
                        log_decision(
                            agent_name="inventory_agent",
                            input_data={"recommendation": recommendation.__dict__},
                            retrieved_context={"data_readiness": {"score": rep.score, "level": rep.level, "checks": rep.checks, "summary": rep.summary}},
                            proposed_action={"action": "escalate_data_readiness", "ticket_id": ticket_id, "playbook_tag": "data_not_ready"},
                            agent_reasoning="blocked reorder due to insufficient data readiness",
                            policy_version="v1",
                            approval_required=False,
                            execution_status="escalated",
                        )
                    except Exception:
                        pass
                    return {
                        "status": "data_not_ready",
                        "readiness": {"score": rep.score, "level": rep.level, "checks": rep.checks, "summary": rep.summary},
                        "ticket_id": ticket_id,
                        "playbook_tag": "data_not_ready",
                    }
            except Exception:
                pass

        # If above threshold, require an approved ticket id
        needs_reason = getattr(recommendation, "requires_human_review_reason", None)
        if recommendation.estimated_cost > approval_min or needs_reason:
            if not approval:
                reason = str(needs_reason or "cost_exceeds_threshold")
                try:
                    from src.app.observability.metrics import record_inventory_reorder_action
                    record_inventory_reorder_action("approval_required", reason)
                except Exception:
                    pass
                try:
                    from src.app.observability.metrics import record_inventory_reorder_approval
                    record_inventory_reorder_approval("required")
                except Exception:
                    pass
                return {"status": "approval_required", "reason": reason, "threshold": approval_min, "cost": recommendation.estimated_cost}
            # approval provided: verify ticket is approved
            try:
                tagent = TicketingAgent()
                t = tagent.get_ticket(approval)
                if not t:
                    try:
                        from src.app.observability.metrics import record_inventory_reorder_approval
                        record_inventory_reorder_approval("ticket_missing")
                    except Exception:
                        pass
                    return {"status": "approval_required", "reason": "ticket_missing", "ticket": approval}
                if t.status != "approved":
                    try:
                        from src.app.observability.metrics import record_inventory_reorder_approval
                        record_inventory_reorder_approval("ticket_not_approved")
                    except Exception:
                        pass
                    return {"status": "approval_required", "reason": "ticket_not_approved", "ticket": approval, "ticket_status": t.status}
                try:
                    from src.app.observability.metrics import record_inventory_reorder_approval
                    record_inventory_reorder_approval("approved")
                except Exception:
                    pass
            except Exception:
                try:
                    from src.app.observability.metrics import record_inventory_reorder_approval
                    record_inventory_reorder_approval("verification_failed")
                except Exception:
                    pass
                return {"status": "approval_required", "reason": "ticket_verification_failed", "ticket": approval}
        else:
            try:
                from src.app.observability.metrics import record_inventory_reorder_approval
                record_inventory_reorder_approval("not_required")
            except Exception:
                pass
        try:
            po_number = str(uuid.uuid4())
            expected_days = recommendation.lead_time_days
            # Persist a simple PO record into purchase_orders table if present
            try:
                with db_session() as db:
                    db.execute(
                        text(
                            """
                            INSERT INTO purchase_orders (id, supplier_id, sku, quantity, unit_cost, status, expected_delivery)
                            VALUES (:id, :supplier_id, :sku, :qty, :unit_cost, :status, :expected)
                            """
                        ),
                        {
                            "id": po_number,
                            "supplier_id": recommendation.supplier_id,
                            "sku": recommendation.sku,
                            "qty": recommendation.quantity,
                            "unit_cost": float(recommendation.estimated_cost / max(1, recommendation.quantity)),
                            "status": "created",
                            "expected": f"in {expected_days} days",
                        },
                    )
                    try:
                        db.commit()
                    except Exception:
                        pass
            except Exception:
                pass

            # Log execution decision
            try:
                log_decision(
                    agent_name="inventory_agent",
                    input_data={"po": po_number, "recommendation": recommendation.__dict__},
                    retrieved_context={},
                    proposed_action={"po_created": po_number},
                    agent_reasoning="purchase order generated",
                    policy_version="v1",
                    approval_required=False,
                    execution_status="executed",
                )
            except Exception:
                pass
            try:
                bundle = write_immutable_decision_bundle(
                    trace_id=po_number,
                    actor_type="agent",
                    actor_id="inventory_agent",
                    tenant_id="default",
                    resource_id=str(recommendation.sku),
                    action="auto_po_create",
                    policy_version="v1",
                    decision="allow",
                    reason_codes=(policy_gate.get("reason_codes") or []) + (["dual_source_confirmed"] if dual_confirm.get("ok") else []),
                    confidence=max(0.0, min(1.0, 1.0 - float(policy_gate.get("risk_score") or 0.0))),
                    evidence_ids=[str(recommendation.supplier_id or ""), str(po_number)],
                    approval_chain=[str(approval)] if approval else [],
                    ticket_id=str(approval) if approval else None,
                    provider_ref=str(po_number),
                    model_inputs={
                        "estimated_cost": recommendation.estimated_cost,
                        "quantity": recommendation.quantity,
                        "supplier_trust_score": trust_score,
                        "anomaly_score": anomaly_score,
                    },
                    supplier_docs={"confirmations": confirmations},
                )
                log_trace_event(
                    trace_id=po_number,
                    event_type="execution_result",
                    source_type="agent",
                    source_id="Inventory_Decision_Bundle_Agent",
                    target_type="bundle",
                    target_id=str(bundle.get("bundle_id")),
                    payload={
                        "action": "immutable_decision_bundle_written",
                        "bundle_id": bundle.get("bundle_id"),
                        "bundle_hash": bundle.get("bundle_hash"),
                        "actor_type": "agent",
                        "actor_id": "inventory_agent",
                        "tenant_id": "default",
                        "resource_id": str(recommendation.sku),
                        "decision": "allow",
                        "policy_version": "v1",
                        "valid_from": (bundle.get("payload") or {}).get("valid_from"),
                        "valid_to": (bundle.get("payload") or {}).get("valid_to"),
                        "recorded_at": (bundle.get("payload") or {}).get("recorded_at"),
                    },
                )
            except Exception:
                pass
            # Close related tickets automatically if provided
            try:
                if approval:
                    tagent = TicketingAgent()
                    # Approve already required before execution; now close
                    if hasattr(tagent, "close_ticket"):
                        tagent.close_ticket(approval)
            except Exception:
                pass

            try:
                from src.app.observability.metrics import record_inventory_po_created, record_inventory_reorder_action
                record_inventory_po_created(getattr(recommendation, "urgency", "normal"))
                record_inventory_reorder_action("po_created", "executed")
            except Exception:
                pass
            return {"status": "po_created", "po_number": po_number, "expected_delivery_days": expected_days}
        except Exception:
            try:
                from src.app.observability.metrics import record_inventory_reorder_action
                record_inventory_reorder_action("failed", "execution_error")
            except Exception:
                pass
            return {"status": "failed"}

    def reconcile_stocktake(self, counted_stock: Dict[str, int]) -> Dict[str, Any]:
        variances: List[Dict[str, Any]] = []
        for sku, counted in (counted_stock or {}).items():
            try:
                with db_session() as db:
                    row = db.execute(text("SELECT SUM(stock) FROM inventory WHERE sku = :sku"), {"sku": sku}).fetchone()
                    system_stock = int(row[0] or 0) if row else 0
            except Exception:
                system_stock = 0
            if counted != system_stock:
                variance = counted - system_stock
                pct = (variance / system_stock * 100) if system_stock else 100.0
                variances.append({"sku": sku, "system": system_stock, "counted": counted, "variance": variance, "variance_pct": pct})

        significant = [v for v in variances if abs(v.get("variance_pct", 0)) > 5]
        if significant:
            try:
                # Log variance for review
                log_decision(
                    agent_name="inventory_agent",
                    input_data={"counted_summary": {"total_counted": len(counted_stock)}},
                    retrieved_context={"significant_variances": significant},
                    proposed_action={"action": "escalate_variance", "details": significant},
                    agent_reasoning="stocktake reconciliation flagged significant variances",
                    policy_version="v1",
                    approval_required=False,
                    execution_status="escalated",
                )
            except Exception:
                pass

            try:
                emit_security_event(path="/inventory/reconcile", payload={"variances": significant})
            except Exception:
                pass

        return {"total_items_counted": len(counted_stock or {}), "variances": len(variances), "significant_variances": len(significant), "details": variances}
