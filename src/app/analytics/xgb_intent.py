from __future__ import annotations

"""XGBoost-based intent classifier with safe fallbacks.

Tries to load a pre-trained model from models/xgb_intent.pkl.
Provides train and infer helpers. Falls back to a simple rules stub when unavailable.
"""

from typing import Any, Dict, List, Tuple
import os

MODEL_PATH = os.getenv("XGB_INTENT_MODEL_PATH", os.path.join("models", "xgb_intent.pkl"))


def _tokenize(text: str) -> List[str]:
    return [t for t in (text or "").lower().split() if t]


def _build_features(text: str) -> Dict[str, Any]:
    toks = _tokenize(text)
    feats: Dict[str, Any] = {}
    # Simple n-gram presence features
    for t in toks:
        feats[f"w_{t}"] = 1
    # Entity flags
    num_tokens = sum(c.isdigit() for c in text)
    feats["has_number"] = 1 if num_tokens > 0 else 0
    feats["has_compare"] = 1 if any(k in toks for k in ("compare", "vs", "versus")) else 0
    feats["has_price"] = 1 if "$" in text or any(k in toks for k in ("price", "under")) else 0
    feats["has_cv"] = 1 if any(k in toks for k in ("complaint", "refund", "damage", "return")) else 0
    return feats


def _vec_dict(feats: Dict[str, Any], vocab: Dict[str, int]) -> List[float]:
    import numpy as np  # type: ignore
    x = np.zeros((len(vocab),), dtype=float)
    for k, v in feats.items():
        idx = vocab.get(k)
        if idx is not None:
            try:
                x[idx] = float(v)
            except Exception:
                x[idx] = 0.0
    return x.tolist()


def load_model():
    try:
        import joblib  # type: ignore
        if os.path.exists(MODEL_PATH):
            obj = joblib.load(MODEL_PATH)
            return obj
    except Exception:
        return None
    return None


def infer_intent(text: str) -> Dict[str, Any]:
    """Infer intent label and probabilities.

    Returns: {"intent": <str>, "proba": {label: prob}}
    """
    model = load_model()
    if model is None:
        # Fallback heuristic
        toks = _tokenize(text)
        if any(k in toks for k in ("refund", "return", "damage", "complaint")):
            return {"intent": "support", "proba": {"support": 0.7}}
        if any(k in toks for k in ("compare", "vs", "versus")):
            return {"intent": "compare", "proba": {"compare": 0.6}}
        return {"intent": "browse", "proba": {"browse": 0.5}}
    try:
        feats = _build_features(text)
        vocab = model.get("vocab")
        clf = model.get("clf")
        labels = model.get("labels")
        x = _vec_dict(feats, vocab)
        import numpy as np  # type: ignore
        arr = np.array([x])
        proba = None
        try:
            proba = clf.predict_proba(arr)[0]
        except Exception:
            # xgboost returns raw scores; normalize
            s = clf.predict(arr)
            proba = s / (abs(s).sum() + 1e-6)
        best_idx = int(proba.argmax()) if hasattr(proba, "argmax") else int(max(range(len(proba)), key=lambda i: proba[i]))
        intent = labels[best_idx]
        return {"intent": intent, "proba": {labels[i]: float(proba[i]) for i in range(len(labels))}}
    except Exception:
        import logging

        logging.getLogger("shopsquire.analytics.xgb_intent").exception("Failed inferring intent; falling back to default")
        return {"intent": "browse", "proba": {"browse": 0.5}}


def train(dataset: List[Tuple[str, str]]) -> Dict[str, Any]:
    """Train a small intent classifier.

    dataset: list of (text, label)
    """
    try:
        import numpy as np  # type: ignore
        try:
            import xgboost as xgb  # type: ignore
            use_xgb = True
        except Exception:
            from sklearn.ensemble import GradientBoostingClassifier  # type: ignore
            use_xgb = False
        texts = [t for t, _ in dataset]
        labels = sorted(list(set([y for _, y in dataset])))
        label_to_idx = {l: i for i, l in enumerate(labels)}
        # Build vocab from features
        vocab_keys = set()
        feats_list = []
        for t in texts:
            f = _build_features(t)
            feats_list.append(f)
            vocab_keys.update(f.keys())
        vocab = {k: i for i, k in enumerate(sorted(list(vocab_keys)))}
        X = np.array([_vec_dict(f, vocab) for f in feats_list])
        y = np.array([label_to_idx[l] for _, l in dataset])
        if use_xgb:
            clf = xgb.XGBClassifier(max_depth=3, n_estimators=100, learning_rate=0.1, subsample=0.9, colsample_bytree=0.9)
            clf.fit(X, y)
        else:
            clf = GradientBoostingClassifier()
            clf.fit(X, y)
        obj = {"clf": clf, "vocab": vocab, "labels": labels}
        try:
            import joblib  # type: ignore
            os.makedirs(os.path.dirname(MODEL_PATH), exist_ok=True)
            joblib.dump(obj, MODEL_PATH)
        except Exception:
            import logging

            logging.getLogger("shopsquire.analytics.xgb_intent").exception("Failed saving trained xgb intent model")
        return {"labels": labels, "vocab_size": len(vocab)}
    except Exception:
        import logging

        logging.getLogger("shopsquire.analytics.xgb_intent").exception("Failed training xgb intent model")
        return {"error": True}