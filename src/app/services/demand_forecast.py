from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import text

from src.app.models.db import db_session


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

    def __init__(self):
        self._db_ok = True

    def _read_history(self, sku: str, lookback_days: int = 120) -> List[Dict[str, Any]]:
        rows = []
        try:
            with db_session() as db:
                rows = db.execute(
                    text(
                        """
                        SELECT substr(created_at, 1, 10) AS d,
                               SUM(COALESCE(quantity, 1)) AS qty
                        FROM order_items
                        WHERE sku = :sku
                          AND datetime(created_at) >= datetime('now', :window)
                        GROUP BY substr(created_at, 1, 10)
                        ORDER BY d ASC
                        """
                    ),
                    {"sku": sku, "window": f"-{max(7, int(lookback_days))} days"},
                ).fetchall()
        except Exception:
            rows = []
        out: List[Dict[str, Any]] = []
        for r in rows or []:
            try:
                out.append({"date": str(r[0]), "qty": float(r[1] or 0.0), "trust": 1.0, "source": "orders"})
            except Exception:
                continue
        return out

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
            },
        )
