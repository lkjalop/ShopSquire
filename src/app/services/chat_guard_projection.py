"""Complete guard exits without granting case, catalog or commerce authority."""


def complete_guarded_response(response, *, operation_id=None):
    if response.get('blocked') is not True or response.get('terminal_outcome'):
        return response
    response = dict(response, products=[], action_executed=False,
                    catalog_authority='blocked', commerce_authority='none')
    response['terminal_outcome'] = {
        'schema_version':'turn-terminal-outcome-v1',
        'operation_id':operation_id,
        'decision_trace_id':response.get('decision_trace_id') or response.get('trace_id'),
        'case_id':response.get('case_id'), 'case_revision':response.get('case_revision'),
        'recommendation_status':'blocked', 'research_status':'not_attempted',
        'catalog_authority':'blocked', 'commerce_authority':'none',
        'catalog_scope':None, 'catalog_scope_status':'unavailable',
        'slate_disposition':'clear', 'products':[], 'product_shelves':None,
        'next_questions':list(response.get('next_questions') or []),
        'assistant_message':str(response.get('assistant_message') or ''),
        'retained_buyer_facts':response.get('retained_buyer_facts'),
    }
    return response
