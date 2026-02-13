from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class ForecastResult:
    sku: str
    daily: List[Dict[str, Any]]  # [{date: str, mean: float, lo: float, hi: float}]


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
        try:
            from src.app.models.db import db_session  # noqa: F401
            self._db_ok = True
        except Exception:
            self._db_ok = False

    def forecast_sku(self, sku: str, horizon_days: int = 90) -> ForecastResult:
        # Placeholder: return flat baseline until model is implemented
        import datetime as _dt
        today = _dt.date.today()
        daily = []
        for i in range(horizon_days):
            d = today + _dt.timedelta(days=i)
            daily.append({"date": d.isoformat(), "mean": 1.0, "lo": 0.5, "hi": 1.5})
        return ForecastResult(sku=sku, daily=daily)
