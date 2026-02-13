"""Simple risk helper implementing exposure formula used by CV flows.

Provides a function to compute likelihood, impact and exposure in cents
using product price as the primary impact proxy.
"""
from __future__ import annotations

from typing import Any, Dict, Optional
import math


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


def quantify_exposure(
    *,
    price_cents: Optional[float] = None,
    likelihood: Optional[float] = None,
    dread_modifier: Optional[float] = 0.0,
    stride_modifier: Optional[float] = 0.0,
    control_maturity: Optional[float] = 0.0,
) -> Dict[str, Any]:
    """Compute risk exposure using a compact formula.

    Args:
      price_cents: monetary value of product (cents)
      likelihood: 0..1
      dread_modifier: 0..1 (mapped from DREAD)
      stride_modifier: 0..1
      control_maturity: 0..1 (higher is better -> reduces risk)

    Returns: dict with likelihood, impact (0..1), risk R (0..1), exposure_cents
    """
    # Defaults
    p = float(price_cents or 0.0)
    L = _clamp(float(likelihood or 0.0))

    # Impact scaling: log with saturation to compress large prices
    try:
        I = _clamp(min(1.0, math.log10((p / 100.0) + 10.0) / 3.0))
    except Exception:
        I = 0.0

    # modifiers: expected in 0..1; combine as additive adjustments
    mod = 1.0 + 0.3 * float(dread_modifier or 0.0) + 0.2 * float(stride_modifier or 0.0) - 0.2 * float(control_maturity or 0.0)
    mod = max(0.2, min(2.0, mod))

    R = _clamp(I * L * mod)
    exposure_cents = int(round(R * p))

    # Translate to bands
    band = "low"
    if exposure_cents >= 20000:
        band = "high"
    elif exposure_cents >= 5000:
        band = "medium"

    return {
        "price_cents": int(p),
        "likelihood": round(L, 3),
        "impact": round(I, 3),
        "modifiers": {"dread": dread_modifier, "stride": stride_modifier, "control_maturity": control_maturity},
        "components": {"L": round(L, 3), "I": round(I, 3), "mod": round(mod, 3)},
        "risk": round(R, 3),
        "exposure_cents": exposure_cents,
        "risk_band": band,
    }
