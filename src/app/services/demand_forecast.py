from __future__ import annotations

import os
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
import math

from sqlalchemy import text

from src.app.models.db import db_session

logger = logging.getLogger(__name__)


def rolling_origin_evaluation(
    values: List[float], *, seasonal_period: int = 7, min_train_points: int = 14,
    horizon_days: int = 1,
) -> Dict[str, Any]:
    """Walk-forward comparison over the decision horizon.

    A supplier-lead-time decision consumes aggregate demand across the lead
    time, not a one-day forecast multiplied after evaluation.
    """
    clean = [max(0.0, float(value)) for value in values if math.isfinite(float(value))]
    minimum = max(3, int(min_train_points))
    horizon = max(1, int(horizon_days))
    if len(clean) < minimum + horizon:
        return {
            "status": "insufficient_history",
            "history_points": len(clean),
            "origins": 0,
            "models": {},
            "winner": None,
            "kind": "rolling_origin_lead_time_demand",
            "horizon_days": horizon,
        }
    errors: Dict[str, list[tuple[float, float, float]]] = {
        "zero": [],
        "naive": [],
        "seasonal_naive": [],
        "ewma": [],
        "croston_sba": [],
        "tsb": [],
    }
    for index in range(minimum, len(clean) - horizon + 1):
        train = clean[:index]
        actual = sum(clean[index:index + horizon])
        seasonal_cycle = (
            train[-seasonal_period:]
            if len(train) >= seasonal_period
            else [train[-1]]
        )
        predictions = {
            "zero": 0.0,
            "naive": train[-1] * horizon,
            "seasonal_naive": sum(
                seasonal_cycle[step % len(seasonal_cycle)]
                for step in range(horizon)
            ),
            "ewma": _ewma_one(train) * horizon,
            "croston_sba": _croston_sba_one(train) * horizon,
            "tsb": _tsb_one(train) * horizon,
        }
        for name, prediction in predictions.items():
            errors[name].append((actual, max(0.0, prediction), actual - prediction))
    windows = [
        sum(clean[index:index + horizon])
        for index in range(0, len(clean) - horizon + 1)
    ]
    scale_errors = [
        abs(windows[index] - windows[index - seasonal_period])
        for index in range(seasonal_period, len(windows))
    ]
    mase_scale = sum(scale_errors) / len(scale_errors) if scale_errors else 0.0
    models: Dict[str, Any] = {}
    for name, rows in errors.items():
        absolute = sum(abs(actual - prediction) for actual, prediction, _ in rows)
        actual_total = sum(actual for actual, _, _ in rows)
        signed = sum(error for _, _, error in rows)
        models[name] = {
            "status": "observed",
            "origins": len(rows),
            "wape": round(absolute / actual_total, 6) if actual_total > 0 else None,
            "wape_status": "available" if actual_total > 0 else "undefined_zero_actual",
            "mase": round((absolute / len(rows)) / mase_scale, 6) if mase_scale > 0 else None,
            "mase_status": "available" if mase_scale > 0 else "undefined_zero_scale",
            "bias": round(signed / actual_total, 6) if actual_total > 0 else None,
        }
    candidates = [
        (metrics["wape"], name)
        for name, metrics in models.items()
        if metrics["wape"] is not None
    ]
    winner = min(candidates)[1] if candidates else None
    return {
        "status": "observed" if winner else "undefined",
        "history_points": len(clean),
        "origins": len(errors["zero"]),
        "models": models,
        "winner": winner,
        "kind": "rolling_origin_lead_time_demand",
        "horizon_days": horizon,
        "authority": "shadow_evaluation_only",
    }


def _ewma_one(values: List[float], alpha: float = 0.28) -> float:
    level = float(values[0]) if values else 0.0
    for value in values[1:]:
        level = alpha * float(value) + (1.0 - alpha) * level
    return level


def _croston_sba_one(values: List[float], alpha: float = 0.2) -> float:
    nonzero = [(index, value) for index, value in enumerate(values) if value > 0]
    if not nonzero:
        return 0.0
    demand = float(nonzero[0][1])
    interval = float(nonzero[0][0] + 1)
    previous_index = nonzero[0][0]
    for index, value in nonzero[1:]:
        demand += alpha * (float(value) - demand)
        gap = float(index - previous_index)
        interval += alpha * (gap - interval)
        previous_index = index
    return (1.0 - alpha / 2.0) * demand / max(interval, 1e-9)


def _tsb_one(values: List[float], alpha: float = 0.2, beta: float = 0.2) -> float:
    if not values:
        return 0.0
    probability = 1.0 if values[0] > 0 else 0.0
    demand = float(values[0]) if values[0] > 0 else 0.0
    for value in values[1:]:
        occurred = 1.0 if value > 0 else 0.0
        probability += beta * (occurred - probability)
        if value > 0:
            demand += alpha * (float(value) - demand)
    return probability * demand


@dataclass
class ForecastResult:
    sku: str
    daily: List[Dict[str, Any]]  # [{date: str, mean: float, lo: float, hi: float}]
    meta: Dict[str, Any] | None = None


class DemandForecaster:
    """MVP: 3-month rolling forecast by SKU/category.

    Features (planned):
    - Historical sales (30/60/90 day)
    - Price changes, active promotions
    - Seasonality (day of week, month)
    - Stockout history

    Output:
    - demand_forecast_daily (materialized view)
    - confidence intervals
    - anomaly flags
    """

    def __init__(self, *, tenant_id: str = "default"):
        self._db_ok = True
        self._last_history_error: str | None = None
        self.tenant_id = str(tenant_id or "").strip()
        if not self.tenant_id:
            raise ValueError("tenant_id is required")

    def _read_history(self, sku: str, lookback_days: int = 120) -> List[Dict[str, Any]]:
        rows = []
        cutoff = datetime.now(timezone.utc) - timedelta(
            days=max(7, int(lookback_days))
        )
        try:
            with db_session() as db:
                rows = db.execute(
                    text(
                        """
                        SELECT occurred_at, quantity, confidence, source_system
                        FROM marketing_event_fact
                        WHERE tenant_id = :tenant
                          AND sku = :sku
                          AND event_type = 'purchase'
                          AND status = 'active'
                          AND occurred_at >= :cutoff
                        ORDER BY occurred_at ASC
                        """
                    ),
                    {
                        "tenant": self.tenant_id,
                        "sku": str(sku),
                        "cutoff": cutoff,
                    },
                ).fetchall()
        except Exception:
            self._last_history_error = "canonical_purchase_history_unavailable"
            logger.warning(
                "forecast history unavailable tenant=%s sku=%s",
                self.tenant_id,
                str(sku),
                exc_info=True,
            )
            rows = []
        daily: Dict[str, Dict[str, float]] = {}
        for r in rows or []:
            try:
                day = str(r[0] or "")[:10]
                if not day:
                    continue
                quantity = max(0.0, float(r[1] or 0.0))
                confidence = max(0.0, min(1.0, float(r[2] or 0.0)))
                bucket = daily.setdefault(
                    day, {"qty": 0.0, "weighted_confidence": 0.0}
                )
                bucket["qty"] += quantity
                bucket["weighted_confidence"] += quantity * confidence
            except Exception:
                continue
        return [
            {
                "date": day,
                "qty": round(values["qty"], 4),
                "trust": round(
                    values["weighted_confidence"] / values["qty"], 4
                ) if values["qty"] > 0 else 0.0,
                "source": "canonical_purchase",
            }
            for day, values in sorted(daily.items())
        ]

    def _quarantine_and_weight(self, series: List[Dict[str, Any]]) -> Dict[str, Any]:
        if not series:
            return {"clean_values": [], "quarantined": [], "weights": []}
        vals = [max(0.0, float(x.get("qty") or 0.0)) for x in series]
        med = sorted(vals)[len(vals) // 2] if vals else 0.0
        base = max(1.0, med)
        quarantined_idx: List[int] = []
        clean: List[float] = []
        weights: List[float] = []
        for i, row in enumerate(series):
            qty = max(0.0, float(row.get("qty") or 0.0))
            trust = max(0.1, min(1.0, float(row.get("trust") or 1.0)))
            source = str(row.get("source") or "orders").strip().lower()
            # Anti-poison: quarantine low-trust spikes and attachment-like noisy sources.
            suspicious_spike = qty > (base * 4.5) and trust < 0.75
            noisy_source = source in ("email_attachment", "supplier_email", "unverified_supplier_feed") and qty > (base * 3.0)
            if suspicious_spike or noisy_source:
                quarantined_idx.append(i)
                continue
            clean.append(qty * trust)
            weights.append(trust)
        return {"clean_values": clean, "quarantined": quarantined_idx, "weights": weights}

    def _forecast_ewma(self, values: List[float], horizon_days: int) -> tuple[List[float], str]:
        if not values:
            return [1.0] * horizon_days, "ewma_default"
        alpha = 0.28
        x = float(values[0])
        for v in values[1:]:
            x = (alpha * float(v)) + ((1.0 - alpha) * x)
        pred = max(0.1, x)
        return [pred for _ in range(horizon_days)], "ewma"

    def _forecast_arima(self, values: List[float], horizon_days: int) -> tuple[List[float], str] | None:
        if len(values) < 12:
            return None
        try:
            from statsmodels.tsa.arima.model import ARIMA  # type: ignore

            fit = ARIMA(values, order=(1, 1, 1)).fit()
            out = fit.forecast(steps=horizon_days)
            preds = [max(0.1, float(v)) for v in out]
            return preds, "arima"
        except Exception:
            return None

    def _forecast_prophet(self, values: List[float], horizon_days: int, start_day: date) -> tuple[List[float], str] | None:
        if len(values) < 14:
            return None
        try:
            from prophet import Prophet  # type: ignore
            import pandas as pd  # type: ignore

            ds = [start_day - timedelta(days=len(values) - i) for i in range(len(values))]
            df = pd.DataFrame({"ds": ds, "y": values})
            m = Prophet(daily_seasonality=True, weekly_seasonality=True, yearly_seasonality=False)
            m.fit(df)
            fut = m.make_future_dataframe(periods=horizon_days, freq="D", include_history=False)
            fc = m.predict(fut)
            preds = [max(0.1, float(v)) for v in fc["yhat"].tolist()[:horizon_days]]
            return preds, "prophet"
        except Exception:
            return None

    def _mape(self, values: List[float]) -> Optional[float]:
        if len(values) < 3:
            return None
        err: List[float] = []
        alpha = 0.28
        sm = float(values[0])
        for actual in values[1:]:
            pred = max(0.1, sm)
            if actual > 0:
                err.append(abs(float(actual) - pred) / float(actual))
            sm = (alpha * float(actual)) + ((1.0 - alpha) * sm)
        if not err:
            return None
        return float(sum(err) / float(len(err)))

    def forecast_sku(self, sku: str, horizon_days: int = 90) -> ForecastResult:
        today = date.today()
        history = self._read_history(sku, lookback_days=180)
        prep = self._quarantine_and_weight(history)
        clean = prep.get("clean_values") or []
        quarantined = prep.get("quarantined") or []

        model_chain = str((os.environ.get("FORECAST_MODEL_CHAIN") or "arima,prophet,ewma")).lower()
        preds: List[float] | None = None
        method = "ewma_default"
        if "arima" in model_chain:
            ar = self._forecast_arima(clean, horizon_days)
            if ar is not None:
                preds, method = ar
        if preds is None and "prophet" in model_chain:
            pr = self._forecast_prophet(clean, horizon_days, today)
            if pr is not None:
                preds, method = pr
        if preds is None:
            preds, method = self._forecast_ewma(clean, horizon_days)

        mape = self._mape(clean)
        evaluation = rolling_origin_evaluation(clean)
        daily = []
        for i in range(horizon_days):
            d = today + timedelta(days=i)
            mean = float(preds[i]) if i < len(preds) else float(preds[-1] if preds else 1.0)
            lo = max(0.0, mean * 0.75)
            hi = max(lo + 0.1, mean * 1.25)
            daily.append({"date": d.isoformat(), "mean": round(mean, 4), "lo": round(lo, 4), "hi": round(hi, 4)})
        return ForecastResult(
            sku=sku,
            daily=daily,
            meta={
                "method": method,
                "history_points": len(history),
                "clean_points": len(clean),
                "quarantined_points": len(quarantined),
                "mape_proxy": round(float(mape), 4) if mape is not None else None,
                "mape_proxy_status": "deprecated_in_sample_diagnostic",
                "rolling_origin": evaluation,
                "forecast_quality_status": evaluation.get("status"),
                "poison_guard": {"enabled": True, "trust_weighted": True},
                "evidence_status": (
                    "degraded" if self._last_history_error else ("available" if history else "no_data")
                ),
                "evidence_error": self._last_history_error,
                "tenant_id": self.tenant_id,
            },
        )
