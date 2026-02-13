from __future__ import annotations

from typing import Dict, Any, List


def demographic_parity(y_true: List[int], y_pred: List[int], sensitive: List[int]) -> Dict[str, Any]:
    """Compute a simple demographic parity difference across a binary sensitive attribute.

    Returns group-positive rates and absolute difference.
    """
    if not (len(y_true) == len(y_pred) == len(sensitive)):
        return {"error": "length_mismatch"}
    g0 = [i for i, s in enumerate(sensitive) if int(s) == 0]
    g1 = [i for i, s in enumerate(sensitive) if int(s) == 1]
    def _pos_rate(indices):
        if not indices:
            return None
        pos = sum(1 for i in indices if int(y_pred[i]) == 1)
        return float(pos) / float(max(1, len(indices)))
    r0 = _pos_rate(g0)
    r1 = _pos_rate(g1)
    diff = None
    if r0 is not None and r1 is not None:
        diff = abs(float(r0) - float(r1))
    return {
        "group0_positive_rate": r0,
        "group1_positive_rate": r1,
        "demographic_parity_diff": diff,
    }
