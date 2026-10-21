"""One evidence-bound set of qualified configurations and unresolved questions."""
from collections.abc import Mapping
import re


def _identity_name(value):
    # Preserve the whole name; normalize only punctuation and common sequel numbers.
    numbers = {'ii': '2', 'iii': '3', 'iv': '4', 'v': '5'}
    return tuple(numbers.get(word, word) for word in re.findall(r'\w+', str(value).casefold()))


def shelf_products(shelves):
    """Read only structurally valid product mappings from untrusted shelves."""
    if not isinstance(shelves, Mapping):
        return
    rows = shelves.get('shelves')
    if not isinstance(rows, (list, tuple)):
        return
    for shelf in rows:
        if not isinstance(shelf, Mapping):
            continue
        for page in ('initial', 'next_page'):
            items = shelf.get(page)
            if isinstance(items, (list, tuple)):
                yield from (item for item in items if isinstance(item, Mapping))


def qualified_configuration_ids(outcome, shelves):
    if (outcome.get('catalog_authority') != 'permitted'
            or outcome.get('requirement_completeness') != 'complete'):
        return []
    return sorted({str(item['identity_key'])
        for item in shelf_products(shelves)
        if item.get('fit_status') == 'qualified' and item.get('identity_key')})


def terminal_questions(questions, outcome):
    """Replace answered provider-absence questions with remaining obligations."""
    questions = list(questions or [])
    if outcome.get('catalog_authority') != 'permitted':
        questions = [q for q in questions if q.get('goal') != 'resolve_budget_capability_gap']
    if not outcome.get('identity') or not outcome.get('accepted_claim_count'):
        return questions
    missing = list(outcome.get('missing_requirement_attributes') or [])
    result = []
    for question in questions or []:
        if question.get('reason') != 'named_workload_evidence_unresolved':
            result.append(question)
            continue
        subjects = question.get('workload_subjects') or []
        identity = outcome.get('identity') or {}
        if not subjects or any(_identity_name(name) != _identity_name(identity.get('title')) for name in subjects):
            result.append(question)
            continue
        if outcome.get('requirement_completeness') == 'complete':
            continue
        result.append({**question, 'reason': 'remaining_requirement_obligations',
            'missing_slots': missing, 'obligation_ids': ['requirement:' + key for key in missing],
            'text': ('Requirements evidence is available, but I still need verified ' +
                     ', '.join(key.replace('_', ' ') for key in missing) + ' evidence.') if missing else
                    'Requirements evidence is available; its remaining source or compatibility obligations need review.'})
    return result
