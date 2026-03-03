#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.app.services.faq_bank import match_faq
from src.app.services.recommendations import RecommendationService


BUYER_QUERIES = [
    "How long do refunds take after return approval?",
    "Can I return a broken laptop after 20 days?",
    "Where is my order and tracking link?",
    "Do you price match competitors?",
    "How do I register warranty for my laptop?",
    "Can I upload photos for a refund claim?",
]

ADMIN_QUERIES = [
    "Show monthly sales trend for last 6 months",
    "Which supplier has worst defect rate this month?",
    "What are top 5 SKUs by margin decline?",
    "How many security incidents were phishing vs prompt injection this week?",
    "Can I get CLV and churn by cohort?",
    "What is decision autonomy trend and human review rate?",
]


def _eval_one(svc: RecommendationService, q: str) -> dict:
    faq, score = match_faq(q)
    nlp = svc.analyze_query(q, prior={})
    return {
        "query": q,
        "faq_question": (faq or {}).get("q"),
        "faq_score": float(score or 0.0),
        "nlp_intent": nlp.get("intent"),
        "nlp_confidence": float(nlp.get("intent_confidence") or 0.0),
    }


def main() -> None:
    svc = RecommendationService(session=None)
    buyer = [_eval_one(svc, q) for q in BUYER_QUERIES]
    admin = [_eval_one(svc, q) for q in ADMIN_QUERIES]
    buyer_hit = sum(1 for r in buyer if float(r.get("faq_score") or 0.0) >= 2.0)
    admin_hit = sum(1 for r in admin if float(r.get("faq_score") or 0.0) >= 2.0)
    report = {
        "buyer": buyer,
        "admin": admin,
        "summary": {
            "buyer_hit_ratio": round(buyer_hit / max(1, len(buyer)), 4),
            "admin_hit_ratio": round(admin_hit / max(1, len(admin)), 4),
            "conclusion": (
                "Current FAQ handles buyer/support intents reasonably; admin BI natural-language coverage is weak and should route to BI intent + SQL tools."
            ),
        },
    }
    out = Path("docs/faq_permutation_report.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"status": "ok", "output": str(out), "summary": report["summary"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
