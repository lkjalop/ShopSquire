from __future__ import annotations

import os
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import text

from src.app.models.db import db_session

logger = logging.getLogger(__name__)


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
                "poison_guard": {"enabled": True, "trust_weighted": True},
                "evidence_status": (
                    "degraded" if self._last_history_error else ("available" if history else "no_data")
                ),
                "evidence_error": self._last_history_error,
                "tenant_id": self.tenant_id,
            },
        )
