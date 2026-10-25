"""Bounded, read-only category bundles; no compatibility or purchase authority.

Only a complete literal category/quantity/total-budget request qualifies. Unknown
prose falls through to the ordinary semantic path rather than dropping a workload.
"""
from dataclasses import dataclass
import re

from sqlalchemy import text

from src.app.services.budget_grammar import classify_budget_scope, parse_budget
from src.app.services.commercial_terms import stated_currency
from src.app.services.taxonomy_registry import get_node, sold_nodes


@dataclass(frozen=True)
class BundleLine:
    category: str
    quantity: int


@dataclass(frozen=True)
class BundleBrowse:
    lines: tuple[BundleLine, ...]
    budget_cents: int
    currency: str


def parse_bundle_browse(query: str) -> BundleBrowse | None:
    match = re.fullmatch(
        r"(?:suggest|show|find)(?: me)? (?:a )?bundle (?:with|of) "
        r"(?P<lines>.+?)\.\s*(?P<terms>.+)", query.strip(), re.I,
    )
    if not match:
        return None
    terms = match['terms']
    budget = parse_budget(terms)
    currency = stated_currency(terms, money_only=True)
    if (not budget or not budget.source_span or budget.budget_max is None or budget.budget_min is not None
            or not currency or classify_budget_scope(terms) != 'total'):
        return None
    start, end = budget.source_span
    remainder = terms[:start] + ' ' + terms[end:]
    # These are commerce grammar words, never product or workload vocabulary.
    allowed = set('aud usd eur gbp cad nzd sgd total for the complete bundle show choices '
                  'only do not add anything to my cart please'.split())
    if set(re.findall(r'[a-z0-9]+', remainder.lower())) - allowed:
        return None
    amount = budget.budget_max * 100
    if not 0 < amount <= 1_000_000_000:
        return None
    parts = re.split(r'\s*(?:,|\band\b|\+)\s*', match['lines'], flags=re.I)
    lines = []
    for part in parts:
        line = re.fullmatch(r'(one|a|an|\d{1,3})\s+([a-z][a-z -]{1,70})', part.strip(), re.I)
        if not line:
            return None
        quantity = 1 if line[1].lower() in {'one', 'a', 'an'} else int(line[1])
        if not 1 <= quantity <= 500:
            return None
        lines.append(BundleLine(line[2].lower().strip(), quantity))
    if not 2 <= len(lines) <= 6 or len({line.category for line in lines}) != len(lines):
        return None
    return BundleBrowse(tuple(lines), int(amount), currency)


def _words(value):
    return tuple(word[:-1] if len(word) > 3 and word.endswith('s') else word
                 for word in re.findall(r'[a-z0-9]+', value.lower()))


def bundle_nodes(db, *, plan, tenant_id):
    nodes = [get_node(handle) for handle in sold_nodes(db, tenant_id=tenant_id)]
    selected = []
    for line in plan.lines:
        wanted = _words(line.category)
        matches = [node for node in nodes if node and wanted
                   and _words(node.name)[-len(wanted):] == wanted]
        if not matches:
            return None
        size = min(len(_words(node.name)) for node in matches)
        best = [node for node in matches if len(_words(node.name)) == size]
        if len(best) != 1:
            return None
        selected.append(best[0])
    return selected if len({node.handle for node in selected}) == len(selected) else None


def bundle_variants(db, *, tenant_id, nodes):
    from src.app.services.catalog_read_model import get_variants
    from src.app.services.case_catalog_candidates import catalog_categories_related

    # Legacy products have global identities: admission must precede facade
    # retrieval and use this tenant's approved classifications, never a global
    # active-product scan. Canonical mode retains its own tenant predicate too.
    admitted = db.execute(text(
        "SELECT sku,node_handle FROM product_classification "
        "WHERE tenant_id=:tenant AND status='approved' ORDER BY sku LIMIT 2000"
    ), {'tenant': tenant_id}).all()
    groups = [[str(sku) for sku, handle in admitted
               if catalog_categories_related(str(handle), node.handle)] for node in nodes]
    return [[row for row in get_variants(db, skus, tenant_id=tenant_id) if row.active] for skus in groups]


def bundle_browse_response(db, envelope):
    from src.app.services.recommendation_core.envelope import CoreResponse, ProductCard
    from src.app.services.recommendation_core.gates import evaluate_text_gates

    plan = parse_bundle_browse(envelope.buyer_query or envelope.query)
    if (plan is None or envelope.has_image
            or (envelope.session or {}).get('accepted_constraints')
            or (envelope.pre_gate is not None and envelope.pre_gate.get('verdict', 'allow') != 'allow')
            or evaluate_text_gates(envelope.query)['policy_route'] != 'allow'):
        return None
    response = CoreResponse(envelope=envelope)
    response.extras.update(
        decision={'lane': 'SEARCH', 'request_scope': 'product', 'subject_action': 'switch',
                  'relationship': 'buy', 'source': 'literal_catalog_bundle', 'budget_scope': 'total'},
        semantic_resolution={'outcome': 'catalog_browse', 'catalog_authority': 'permitted',
                             'qualification_authority': 'none', 'commerce_authority': 'none',
                             'scope': 'category_and_price', 'requirements_status': 'not_requested',
                             'bundle_browse': True},
        qualification_authority='none',
    )
    nodes = bundle_nodes(db, plan=plan, tenant_id=envelope.tenant_id)
    if not nodes:
        return None
    groups = bundle_variants(db, tenant_id=envelope.tenant_id, nodes=nodes) if nodes else []
    selected = [min((row for row in group if row.currency == plan.currency and row.price_cents > 0),
                    key=lambda row: (row.price_cents, row.sku), default=None) for group in groups]
    complete = bool(selected and all(row is not None for row in selected))
    subtotal = sum(line.quantity * row.price_cents for line, row in zip(plan.lines, selected)) if complete else None
    within = subtotal is not None and subtotal <= plan.budget_cents
    response.extras['catalog_bundle'] = {
        'schema_version': 'catalog-bundle-browse-v1', 'currency': plan.currency,
        'budget_cents': plan.budget_cents, 'budget_scope': 'total', 'subtotal_cents': subtotal,
        'status': 'within_listed_budget' if within else 'over_budget' if complete else 'missing_candidates',
        'price_basis': 'listed_unit_price', 'tax_and_freight': 'not_established',
        'compatibility': 'not_assessed', 'commerce_authority': 'none',
        'lines': [dict(category=line.category, quantity=line.quantity,
                       taxonomy_handle=nodes[i].handle if nodes else None,
                       sku=selected[i].sku if complete else None,
                       unit_price_cents=selected[i].price_cents if complete else None)
                  for i, line in enumerate(plan.lines)],
    }
    if within:
        response.products = [ProductCard(sku=row.sku, title=row.title, price_cents=row.price_cents,
                                         currency=row.currency, brand=row.brand,
                                         why=['Listed category choice; compatibility not assessed']) for row in selected]
        response.message = (f'These category choices have a listed subtotal of {plan.currency} {subtotal / 100:.2f} '
                            f'for the requested quantities, within your {plan.currency} {plan.budget_cents / 100:.2f} total. '
                            'Compatibility, current stock, tax and freight still need verification. Nothing was added to your cart.')
    else:
        response.message = ('A complete bundle within the stated currency and total budget is not established. '
                            'Please revise the total or categories; I have not substituted a currency or added anything to your cart.')
    response.record_stage('catalog_bundle_browse', status='ok' if within else 'clarify',
                          retrieval_count=len(response.products), commerce_authority='none')
    return response.finalize()
