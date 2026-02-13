from src.app.services.decision_log import log_decision

if __name__ == '__main__':
    dec_id = log_decision(
        agent_name='test_agent',
        input_data={'x': 1},
        retrieved_context={'ctx': {}},
        proposed_action={'action': 'ok'},
        agent_reasoning='test',
        policy_version='v1',
        approval_required=False,
        execution_status='executed',
    )
    print('decision_id=', dec_id)
