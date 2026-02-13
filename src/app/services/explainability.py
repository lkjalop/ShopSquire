from __future__ import annotations

from typing import Dict, Any, List


def explain_recommendation(features: Dict[str, float], model: Any | None = None) -> Dict[str, Any]:
    """Basic explainability: return normalized feature weights.

    If SHAP is available and a model is provided, attempt SHAP; otherwise,
    return a simple normalized dict of feature magnitudes.
    """
    try:
        import shap  # type: ignore
        if model is not None:
            try:
                explainer = shap.Explainer(model)
                vals = explainer([list(features.values())])
                # Flatten first sample
                shap_vals = list(vals.values)[0]
                names = list(features.keys())
                fi = {names[i]: float(abs(shap_vals[i])) for i in range(min(len(names), len(shap_vals)))}
                return {"method": "shap", "feature_importances": fi}
            except Exception:
                pass
    except Exception:
        pass
    # Fallback: magnitude-based importance
    mags = {k: abs(float(v)) for k, v in features.items()}
    total = sum(mags.values()) or 1.0
    norm = {k: float(v) / float(total) for k, v in mags.items()}
    return {"method": "magnitude", "feature_importances": norm}
