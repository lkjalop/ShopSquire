from __future__ import annotations

"""Contextual Bandit Trainer for Policy Optimization.

Consumes analytics/rl_traces/traces.jsonl with entries:
  { trace_id, state, action, reward }

State fields used (best-effort):
  - intent, tier_decision.tier, model_choice.model, evidence_tags

Actions considered:
  - increase_tool_budget
  - downgrade_text_tier
  - prefer_cache

Outputs learned policy to analytics/rl_traces/recommendations.json mapping
contexts to best actions via epsilon-greedy value estimates.
"""

import json
import os
from typing import Dict, Any, Tuple


def _load_jsonl(path: str) -> list[dict]:
    out = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except Exception:
                    pass
    except Exception:
        out = []
    return out


def _context_key(state: Dict[str, Any]) -> str:
    # Compact key for simple bandit contexts
    try:
        intent = (state.get("intent") or {}).get("intent") or ""
    except Exception:
        intent = ""
    try:
        tier = str((state.get("tier_decision") or {}).get("tier") or "")
    except Exception:
        tier = ""
    try:
        model = (state.get("model_choice") or {}).get("model") or ""
    except Exception:
        model = ""
    try:
        tags = sorted(list(state.get("evidence_tags") or []))
    except Exception:
        tags = []
    return json.dumps({"intent": intent, "tier": tier, "model": model, "tags": tags}, ensure_ascii=False, separators=(",", ":"))


def train_bandit(
    traces_path: str = "analytics/rl_traces/traces.jsonl",
    output_path: str = "analytics/rl_traces/recommendations.json",
    epsilon: float = 0.1,
) -> str:
    traces = _load_jsonl(traces_path)
    # Q-values: context -> action -> [sum_reward, count]
    Q: Dict[str, Dict[str, Tuple[float, int]]] = {}
    actions = ["increase_tool_budget", "downgrade_text_tier", "prefer_cache"]
    for t in traces:
        state = t.get("state") or {}
        reward = float(t.get("reward") or 0.0)
        ctx = _context_key(state)
        if ctx not in Q:
            Q[ctx] = {a: (0.0, 0) for a in actions}
        # If an action was taken, update its value; else distribute reward uniformly
        a_taken = (t.get("action") or {}).get("type") or None
        if a_taken in Q[ctx]:
            s, c = Q[ctx][a_taken]
            Q[ctx][a_taken] = (s + reward, c + 1)
        else:
            # No explicit action: attribute to a reasonable default (prefer_cache on high reward)
            default = "prefer_cache" if reward > 0 else "increase_tool_budget"
            s, c = Q[ctx][default]
            Q[ctx][default] = (s + reward, c + 1)

    # Derive policy: pick best action per context by average reward (epsilon-greedy for exploration hint)
    policy: Dict[str, Dict[str, Any]] = {}
    for ctx, acts in Q.items():
        best_a = None
        best_avg = -9999.0
        for a, (s, c) in acts.items():
            avg = (s / c) if c > 0 else 0.0
            if avg > best_avg:
                best_avg = avg
                best_a = a
        policy[ctx] = {"action": best_a or "prefer_cache", "expected_reward": best_avg}

    try:
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump({"policy": policy, "epsilon": epsilon, "contexts": len(policy)}, f, indent=2)
    except Exception:
        pass
    return output_path


if __name__ == "__main__":
    out = train_bandit()
    print(json.dumps({"status": "ok", "output": out}))
