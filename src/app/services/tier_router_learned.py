from __future__ import annotations

"""
LearnedTierRouter: optional lightweight classifier for model tier routing.

When available, uses scikit-learn (LogisticRegression) or XGBoost to predict
text/vision tiers from simple features. Falls back to heuristic selection when
no model is loaded.

Usage:
  router = LearnedTierRouter(flags)
  decision = router.route(query, context, intent_result, security_analysis)
  -> decision: { tier: int, tool_budget: int, model: str, reason: str }
"""

from typing import Any, Dict, Optional


class LearnedTierDecision:
    def __init__(self, tier: int, tool_budget: int, model: Optional[str], reason: str):
        self.tier = tier
        self.tool_budget = tool_budget
        self.model = model
        self.reason = reason


class LearnedTierRouter:
    def __init__(self, flags: Dict[str, Any] | None = None):
        self.flags = flags or {}
        self.model = None
        self.model_type = None
        self._load_model()

    def _load_model(self) -> None:
        path = str(self.flags.get("TIER_ROUTER_MODEL_PATH") or "").strip()
        if not path:
            return
        try:
            # Try XGBoost first
            import xgboost as xgb  # type: ignore
            self.model = xgb.XGBClassifier()
            self.model.load_model(path)
            self.model_type = "xgb"
            return
        except Exception:
            pass
        try:
            # Fallback to scikit-learn joblib
            import joblib  # type: ignore
            self.model = joblib.load(path)
            self.model_type = "sklearn"
        except Exception:
            self.model = None
            self.model_type = None

    def _features(self, *, query: str, context: Dict[str, Any], intent_result: Dict[str, Any], security: Dict[str, Any]) -> Dict[str, float]:
        amt = float(context.get("amount", 0.0) or 0.0)
        multi_turn = 1.0 if bool(context.get("multi_turn", False)) else 0.0
        image_present = 1.0 if bool(context.get("image_present", False)) else 0.0
        intent_conf = float(intent_result.get("confidence", intent_result.get("intent_confidence", 1.0)) or 1.0)
        risk_adj = float(security.get("risk_adj", 0.0) or 0.0)
        return {
            "amount": amt,
            "multi_turn": multi_turn,
            "image_present": image_present,
            "intent_confidence": intent_conf,
            "risk_adj": risk_adj,
            "query_len": float(len(query or "")),
        }

    def route(self, *, query: str, context: Dict[str, Any], intent_result: Dict[str, Any], security_analysis: Dict[str, Any]) -> LearnedTierDecision:
        # Derive basic features
        feats = self._features(query=query, context=context, intent_result=intent_result, security=security_analysis)
        tier = 1
        tool_budget = int(self.flags.get("DEFAULT_TOOL_BUDGET", 4) or 4)
        model = None
        reason = "heuristic"
        # If we have a trained model, try to predict
        try:
            if self.model is not None:
                X = [[
                    feats["amount"],
                    feats["multi_turn"],
                    feats["image_present"],
                    feats["intent_confidence"],
                    feats["risk_adj"],
                    feats["query_len"],
                ]]
                y = None
                if self.model_type == "xgb":
                    y = self.model.predict(X)[0]
                else:
                    y = int(self.model.predict(X)[0])
                tier = int(y or 1)
                reason = f"learned:{self.model_type}"
        except Exception:
            tier = 1
            reason = "heuristic_fallback"
        # Heuristic fallbacks / constraints
        if feats["image_present"] >= 1.0 or feats["risk_adj"] >= 40.0:
            tier = max(tier, 2)
        if feats["amount"] >= 250.0 or feats["multi_turn"] >= 1.0:
            tier = max(tier, 2)
        if feats["risk_adj"] >= 70.0:
            tier = 3
        # Budget scaling by tier
        if tier == 1:
            tool_budget = int(self.flags.get("BUDGET_T1", 3) or 3)
            model = self.flags.get("MODEL_T1", "qwen2-small")
        elif tier == 2:
            tool_budget = int(self.flags.get("BUDGET_T2", 5) or 5)
            model = self.flags.get("MODEL_T2", "qwen2-medium")
        else:
            tool_budget = int(self.flags.get("BUDGET_T3", 6) or 6)
            model = self.flags.get("MODEL_T3", "qwen2-large")

        return LearnedTierDecision(tier=tier, tool_budget=tool_budget, model=model, reason=reason)
