from src.app.services import chat_transport as transport


def test_replay_guard_does_not_block_another_tenant_or_temporary_session():
    args=dict(tenant_id='a',uid='buyer',session_id='session',source_ip='127.0.0.1',query='Recall my request',
        nonce='',shape={},memory_mode='standard',case_id='')
    key=transport.chat_replay_digest(**args)
    transport._CHAT_REPLAY_LOCAL.clear()
    assert transport._chat_replay_mark_once(None,replay_key=key,ttl_seconds=20)
    assert not transport._chat_replay_mark_once(None,replay_key=key,ttl_seconds=20)
    for changes in ({'tenant_id':'b'},{'memory_mode':'temporary'},{'case_id':'another-case'}):
        scoped=transport.chat_replay_digest(**{**args,**changes})
        assert transport._chat_replay_mark_once(None,replay_key=scoped,ttl_seconds=20)


def test_separator_characters_cannot_alias_replay_identity():
    args=dict(tenant_id='a',uid='buyer|session',session_id='tail',source_ip='',query='hi',nonce='',shape={},memory_mode='standard',case_id='')
    assert transport.chat_replay_digest(**args)!=transport.chat_replay_digest(**{**args,'uid':'buyer','session_id':'session|tail'})
