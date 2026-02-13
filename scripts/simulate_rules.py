"""Simulation harness to run a labeled corpus against the rule engine and compute precision/recall.

Usage:
    python scripts/simulate_rules.py path/to/corpus.jsonl

Corpus format: JSON lines with {"text": "show me laptops", "label": "product_search", "tenant_id": null}
"""

import json
import sys
from collections import Counter
from src.app.services.rule_store import RuleStore
from src.app.services.expanded_rules import ExpandedRuleEngine


def load_corpus(path):
    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            if not line.strip():
                continue
            yield json.loads(line)


def evaluate(corpus_path):
    store = RuleStore()
    engine = ExpandedRuleEngine(rule_store=store)
    tp = Counter()
    fp = Counter()
    fn = Counter()
    total = 0
    for rec in load_corpus(corpus_path):
        text = rec.get('text')
        label = rec.get('label')
        tenant = rec.get('tenant_id')
        res = engine.evaluate(text, {'memory': {'tenant_id': tenant}, 'live': {}})
        predicted = res.get('intent') if res.get('handled') else None
        total += 1
        if predicted == label:
            tp[label] += 1
        else:
            if predicted is None:
                fn[label] += 1
            else:
                fp[predicted] += 1
    # compute per-label precision/recall
    labels = set(list(tp.keys()) + list(fp.keys()) + list(fn.keys()))
    out = {}
    for l in labels:
        p = tp[l] / (tp[l] + fp[l]) if (tp[l] + fp[l]) > 0 else 0.0
        r = tp[l] / (tp[l] + fn[l]) if (tp[l] + fn[l]) > 0 else 0.0
        out[l] = {'precision': p, 'recall': r, 'tp': tp[l], 'fp': fp[l], 'fn': fn[l]}
    summary = {'total': total, 'labels': out}
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('Usage: python scripts/simulate_rules.py corpus.jsonl')
        sys.exit(2)
    evaluate(sys.argv[1])
