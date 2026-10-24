"""Opt-in checks against a separately owned loopback Redis, never a developer cache."""
import os
from dataclasses import replace
from urllib.parse import urlsplit
from uuid import uuid4
import pytest
from src.app.services.semantic_cache import CacheContract, SemanticCache


@pytest.fixture
def backend():
    url=os.getenv('ROADMAP_OWNED_REDIS_URL')
    if not url:pytest.skip('separately owned Redis required')
    assert urlsplit(url).hostname in {'127.0.0.1','localhost'}
    import redis
    client=redis.Redis.from_url(url,decode_responses=True,socket_timeout=1)
    assert client.ping()
    yield client
    client.close()


@pytest.fixture
def contract():
    return CacheContract.resolve(tenant_id='test-'+uuid4().hex,subject_id='buyer',
        corpus_version='c1',policy_version='p1',model_version='m1',evidence_cutoff='2026-10-05')


def put(cache,contract,value):
    return cache.set_versioned(namespace='recall',request='same-query',contract=contract,
        value=value,source_id='synthetic:test',trust_score=1,ex=60)


def get(cache,contract):
    return cache.get_versioned(namespace='recall',request='same-query',contract=contract)


def test_separate_instances_share_only_exact_scope_and_observe_erasure(backend,contract):
    first=SemanticCache(redis_client=backend)
    second=SemanticCache(redis_client=backend)
    try:
        put(first,contract,{'canary':'PRIVATE_SCOPED_VALUE'})
        assert get(second,contract)=={'canary':'PRIVATE_SCOPED_VALUE'}
        for key,value in [('tenant_id','foreign'),('subject_id','other'),('policy_version','p2')]:
            assert get(second,replace(contract,**{key:value})) is None
        assert second.erase_scope(contract)==1
        assert get(first,contract) is None
        assert get(SemanticCache(redis_client=backend),contract) is None
    finally:
        second.erase_scope(contract)


def test_partitioned_worker_cannot_reveal_locally_retained_erased_value(backend,contract):
    class Partition:
        offline=False
        def __getattr__(self,name):
            if self.offline:raise ConnectionError('isolated_worker_partition')
            return getattr(backend,name)
    connection=Partition()
    first=SemanticCache(redis_client=connection)
    second=SemanticCache(redis_client=backend)
    try:
        put(first,contract,{'canary':'SHARED'})
        connection.offline=True
        put(first,contract,{'canary':'LOCAL_PRIVATE'})
        assert second.erase_scope(contract)==1
        assert get(first,contract) is None
        connection.offline=False
        assert get(first,contract) is None
    finally:
        connection.offline=False
        second.erase_scope(contract)


def test_semantic_registration_failure_does_not_publish_an_orphan(backend, contract):
    cache = SemanticCache(redis_client=backend)
    key = contract.cache_key('recall', 'same-query')
    backend.set(contract.erasure_index_key, 'wrong-type', ex=60)
    try:
        put(cache, contract, {'canary': 'MUST_NOT_PUBLISH'})
        assert not backend.exists(key)
        assert get(SemanticCache(redis_client=backend), contract) is None
        with pytest.raises(RuntimeError, match='cache_erasure_incomplete'):
            cache.erase_scope(contract)
    finally:
        backend.delete(contract.erasure_index_key, key)


def test_semantic_short_write_cannot_shorten_longer_erasure_index(backend, contract):
    cache = SemanticCache(redis_client=backend)
    long_key = cache.set_versioned(namespace='recall', request='long', contract=contract,
        value='private-long', source_id='owned', trust_score=1, ex=100 * 86400)
    try:
        before = backend.ttl(contract.erasure_index_key)
        put(cache, contract, 'short')
        assert backend.ttl(contract.erasure_index_key) >= before - 1
        assert cache.erase_scope(contract) == 2
        assert not backend.exists(long_key)
    finally:
        cache.erase_scope(contract)


def test_semantic_index_lifetime_tracks_live_values_without_ninety_day_retention(backend, contract):
    cache = SemanticCache(redis_client=backend)
    key = put(cache, contract, 'private')
    try:
        value_lifetime = backend.pttl(key)
        index_lifetime = backend.pttl(contract.erasure_index_key)
        assert value_lifetime > 0
        assert value_lifetime <= index_lifetime <= value_lifetime + 1500
    finally:
        cache.erase_scope(contract)


def test_semantic_concurrent_write_and_erasure_leave_no_unindexed_values(backend, contract):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    ready = Barrier(3)

    def write(worker):
        cache = SemanticCache(redis_client=backend)
        ready.wait(timeout=5)
        for number in range(60):
            cache.set_versioned(namespace='race', request=[worker, number], contract=contract,
                value='PRIVATE', source_id='owned', trust_score=1, ex=60)

    def erase():
        cache = SemanticCache(redis_client=backend)
        ready.wait(timeout=5)
        for _ in range(60):
            cache.erase_scope(contract)

    try:
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = [pool.submit(write, n) for n in range(2)] + [pool.submit(erase)]
            for future in futures:
                future.result(timeout=20)
        SemanticCache(redis_client=backend).erase_scope(contract)
        pattern = contract.cache_key('race', [0, 0]).rsplit(':', 1)[0] + ':*'
        assert list(backend.scan_iter(pattern)) == []
    finally:
        SemanticCache(redis_client=backend).erase_scope(contract)


def test_conversation_erasure_reaches_another_local_store(backend,contract):
    from src.app.services.memory import Memory
    first=Memory(backend,tenant_id=contract.tenant_id)
    second=Memory(backend,tenant_id=contract.tenant_id)
    first._LOCAL_STORE={};first._LOCAL_INDEX={}
    second._LOCAL_STORE={};second._LOCAL_INDEX={}
    try:
        first.set_kv('buyer',{'canary':'REAL_REDIS_CONVERSATION'})
        assert second.get_kv('buyer')=={'canary':'REAL_REDIS_CONVERSATION'}
        second.erase_subject('buyer')
        assert first.get_kv('buyer')=={}
    finally:
        second.erase_subject('buyer')


def test_failed_index_command_never_persists_an_orphan_conversation(backend, contract):
    from src.app.services.memory import Memory
    writer = Memory(backend, tenant_id=contract.tenant_id)
    scope = writer.scope('buyer')
    # Redis command errors do not roll back earlier script commands. Verify
    # registration failure with the real server, rather than a successful mock.
    backend.set(scope.subject_index_key, 'wrong-type', ex=60)
    try:
        writer.set_kv('buyer', {'private': 'INDEX_FAILURE_CANARY'})
        assert not backend.exists(scope.key('kv_state'))
    finally:
        backend.delete(scope.subject_index_key)
        writer.erase_subject('buyer')


def test_concurrent_writes_and_subject_erasure_leave_no_unindexed_values(backend, contract):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from src.app.services.memory import Memory
    ready = Barrier(3)
    def write(worker):
        memory = Memory(backend, tenant_id=contract.tenant_id)
        ready.wait(timeout=5)
        for n in range(60):
            memory.set_kv('buyer', {'worker': worker, 'turn': n}, session_epoch=f'{worker}-{n}')
    def erase():
        memory = Memory(backend, tenant_id=contract.tenant_id)
        ready.wait(timeout=5)
        for _ in range(60):
            memory.erase_subject('buyer')
    try:
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = [pool.submit(write, n) for n in range(2)] + [pool.submit(erase)]
            for future in futures:
                future.result(timeout=20)
        replacement = Memory(backend, tenant_id=contract.tenant_id)
        replacement._LOCAL_STORE = {}; replacement._LOCAL_INDEX = {}
        replacement.erase_subject('buyer')
        scope = replacement.scope('buyer')
        assert list(backend.scan_iter(f'memory:v2:{scope.tenant_segment}:{scope.subject_segment}:*')) == []
    finally:
        Memory(backend, tenant_id=contract.tenant_id).erase_subject('buyer')


def _memory_process(pipe, url, tenant):
    import redis
    from src.app.services.memory import Memory
    client=redis.Redis.from_url(url,decode_responses=True,socket_timeout=1)
    class Connection:
        offline=False
        def __getattr__(self,name):
            if self.offline:raise ConnectionError('test_partition')
            return getattr(client,name)
    connection=Connection();memory=Memory(connection,tenant_id=tenant)
    try:
        while True:
            command=pipe.recv()
            if command=='stop':break
            if command=='partition':connection.offline=True;value=True
            elif command=='reconnect':connection.offline=False;value=True
            elif command=='write':memory.set_kv('buyer',{'canary':'PROCESS_SCOPED'});value=True
            elif command=='read':value=memory.get_kv('buyer')
            elif command=='erase':memory.erase_subject('buyer');value=True
            else:raise ValueError('unknown_test_command')
            pipe.send(value)
    finally:
        client.close();pipe.close()


def test_real_worker_processes_observe_erasure_through_partition_and_restart(backend,contract):
    import multiprocessing
    context=multiprocessing.get_context('spawn');workers=[]
    def worker(tenant):
        parent,child=context.Pipe()
        process=context.Process(target=_memory_process,args=(child,os.environ['ROADMAP_OWNED_REDIS_URL'],tenant))
        process.start();child.close();workers.append((process,parent))
        return parent
    def ask(pipe,command):
        pipe.send(command)
        assert pipe.poll(15),'memory worker did not respond'
        return pipe.recv()
    try:
        first=worker(contract.tenant_id);eraser=worker(contract.tenant_id)
        foreign=worker(contract.tenant_id+'-foreign')
        assert ask(first,'write')
        assert ask(first,'read')=={'canary':'PROCESS_SCOPED'}
        assert ask(foreign,'read')=={}
        assert ask(first,'partition')
        assert ask(eraser,'erase')
        assert ask(first,'read')=={}
        assert ask(first,'reconnect')
        assert ask(first,'read')=={}
        first.send('stop');workers[0][0].join(5)
        assert not workers[0][0].is_alive()
        restarted=worker(contract.tenant_id)
        assert ask(restarted,'read')=={}
    finally:
        for process,pipe in workers:
            if process.is_alive():
                try:pipe.send('stop')
                except (BrokenPipeError,EOFError,OSError):pass
                process.join(5)
            if process.is_alive():process.terminate();process.join(5)
            pipe.close()
        from src.app.services.memory import Memory
        Memory(backend,tenant_id=contract.tenant_id).erase_subject('buyer')
