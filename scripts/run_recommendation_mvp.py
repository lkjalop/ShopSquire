"""Small runner to exercise the RecommendationService locally.
Usage: python scripts/run_recommendation_mvp.py [query]
"""
import logging
import sys
from src.app.services.recommendations import RecommendationService


def main(argv):
    logging.basicConfig(level=logging.INFO)
    query = argv[1] if len(argv) > 1 else "gaming laptop"
    svc = RecommendationService()
    constraints = svc.parse_constraints(query)
    constraints["query"] = query
    candidates = svc.retrieve_candidates(query, limit=8)
    ranked = svc.rerank_candidates(candidates, constraints)
    print("Top recommendations:")
    for i, r in enumerate(ranked[:5], start=1):
        print(f"{i}. {r.get('sku')} - {r.get('name')} (${(r.get('price_cents') or 0)/100:.2f})")


if __name__ == "__main__":
    main(sys.argv)
