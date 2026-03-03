from __future__ import annotations

import json
import os

from src.app.services.recommendation_als import train_recommend_als


def run() -> dict:
    lookback_days = int(os.getenv("RECO_ALS_LOOKBACK_DAYS", "120") or 120)
    topk_per_user = int(os.getenv("RECO_ALS_TOPK_PER_USER", "80") or 80)
    factors = int(os.getenv("RECO_ALS_FACTORS", "12") or 12)
    iters = int(os.getenv("RECO_ALS_ITERS", "6") or 6)
    return train_recommend_als(
        lookback_days=max(30, min(lookback_days, 365)),
        topk_per_user=max(20, min(topk_per_user, 200)),
        factors=max(6, min(factors, 64)),
        iters=max(2, min(iters, 25)),
    )


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False))
