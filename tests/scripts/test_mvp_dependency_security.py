"""The shipped lock must not silently restore the unpatched evaluator stack."""
from pathlib import Path
import tomllib

from packaging.version import Version


ROOT = Path(__file__).resolve().parents[2]


def test_unpatched_evaluator_and_unused_framework_chain_are_not_shipped():
    packages = tomllib.loads((ROOT / 'poetry.lock').read_text(encoding='utf-8'))['package']
    names = {row['name'] for row in packages}
    assert not names.intersection({'ragas', 'diskcache', 'langchain', 'langchain-community', 'langgraph-sdk'})
    locks = [row for row in packages if row['name'] == 'filelock']
    assert locks and all(Version(row['version']) >= Version('4.2.1') for row in locks)


def test_unavailable_evaluation_remains_unmeasured(monkeypatch):
    import sys
    from src.app.services.evaluation_contract import evaluate_sample
    monkeypatch.setitem(sys.modules, 'ragas', None)
    result = evaluate_sample('question', {'chunks': ['source'], 'ground_truth': 'reference'}, 'answer')
    assert result['status'] == 'unavailable'
    assert result['error_code'] == 'evaluator_unavailable'
    assert all(value is None for value in result['metrics'].values())
