"""Separate owned API processes must agree on erasure and retryable failure.

This covers indexed Redis memory/cache and the deletion-job ledger. It does not
certify every SQL business record, attachment, backup or historical data plane.
"""
from contextlib import ExitStack
import os
import secrets
from uuid import uuid4

import pytest
import requests

from tests.owned_security_runtime import _owned_runtime
from src.app.services.memory import Memory
from src.app.services.semantic_cache import CacheContract, SemanticCache


@pytest.mark.integration
@pytest.mark.parametrize("partition_first_instance", [False, True], ids=["shared-erasure", "partition-recovery"])
def test_erasure_is_visible_from_another_api_process_and_never_hides_partition(
        pytestconfig, tmp_path, partition_first_instance):
    redis_url = os.getenv("TEST_OWNED_PRIVACY_REDIS_URL")
    if not redis_url:
        pytest.skip("Explicit owned Redis required; no inherited backend is contacted")
    from urllib.parse import urlsplit
    import redis
    assert urlsplit(redis_url).hostname == "127.0.0.1"
    client = redis.Redis.from_url(redis_url, socket_timeout=1, socket_connect_timeout=1)
    assert client.ping()
    uid = "privacy-http-" + uuid4().hex
    subject_canary = "OWNED-MEMORY-" + uuid4().hex
    foreign_canary = "RETAIN-OTHER-CONTROLLER-" + uuid4().hex
    own = Memory(client, tenant_id="default")
    foreign = Memory(client, tenant_id="other-controller")
    cache = SemanticCache(redis_client=client)
    contracts = [CacheContract.resolve(tenant_id=tenant, subject_id=uid,
        corpus_version="owned-http-v1", policy_version="owned-v1", model_version="none",
        evidence_cutoff="2026-10-24") for tenant in ("default", "other-controller")]
    database_url = "sqlite:///" + (tmp_path / "shared.sqlite3").as_posix()
    owner_key, merchant_key = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    overrides = {"DATABASE_URL": database_url, "DATABASE_URL_RO": database_url,
                 "OWNER_API_KEY": owner_key, "MERCHANT_API_KEY": merchant_key,
                 "REDIS_URL": redis_url, "ROUTER_MODEL_ENABLED": "0"}
    try:
        own.set_kv(uid, {"quantity": 40, "private_canary": subject_canary})
        foreign.set_kv(uid, {"quantity": 90, "private_canary": foreign_canary})
        for contract, value in zip(contracts, (subject_canary, foreign_canary)):
            cache.set_versioned(namespace="owned-http-erasure", request={"intent": "recall"},
                contract=contract, value={"private_canary": value}, source_id="owned-native-fixture",
                trust_score=1, ex=120)
        with ExitStack() as stack, requests.Session() as http:
            http.trust_env = False
            first = stack.enter_context(_owned_runtime(pytestconfig,
                artifact_directory=tmp_path / "instance-a", publish_base_url=False,
                env_overrides={**overrides, "REDIS_URL": "redis://127.0.0.1:1/0"}
                    if partition_first_instance else overrides))
            second = stack.enter_context(_owned_runtime(pytestconfig,
                artifact_directory=tmp_path / "instance-b", publish_base_url=False,
                env_overrides=overrides))
            assert first["process_id"] != second["process_id"]
            owner = {"x-api-key": owner_key, "x-tenant-id": "default"}
            path = "/api/v1/privacy/data/" + uid
            assert http.delete(second["base_url"] + path, timeout=10).status_code == 401
            assert http.delete(second["base_url"] + path,
                headers={**owner, "x-api-key": merchant_key}, timeout=10).status_code == 403
            exported = http.get(second["base_url"] + "/api/v1/privacy/export/" + uid,
                                headers=owner, timeout=10)
            # This raw export route is deliberately denied by PII-01, even to
            # an owner. Do not disable that gate to qualify deletion. Positive
            # approved-DSR export remains a separate acceptance requirement.
            assert exported.status_code == 403, exported.text
            assert exported.json()["detail"]["error"] == "policy_gate_denied"
            assert subject_canary not in exported.text
            assert foreign_canary not in exported.text
            assert own.get_kv(uid)["private_canary"] == subject_canary

            erased = http.delete(first["base_url"] + path, headers=owner, timeout=15)
            assert erased.status_code == 200, erased.text
            result = erased.json()
            expected = "action_required" if partition_first_instance else "completed"
            assert result["status"] == expected, result
            job = http.get(second["base_url"] + "/api/v1/privacy/deletion-jobs/" + result["job_id"],
                           headers=owner, timeout=10)
            assert job.status_code == 200 and job.json()["status"] == expected
            assert uid not in job.text
            if partition_first_instance:
                assert "redis_or_cache_erasure_incomplete" in result["action_required"]
                assert own.get_kv(uid)["private_canary"] == subject_canary
                # Recovery is a new explicit request, not a relabelled successful
                # first attempt or an invisible process-local deletion.
                retried = http.delete(second["base_url"] + path, headers=owner, timeout=15)
                assert retried.status_code == 200 and retried.json()["status"] == "completed"
                assert retried.json()["job_id"] != result["job_id"]
            assert own.get_kv(uid) == {}
            assert foreign.get_kv(uid)["private_canary"] == foreign_canary
            replacement = SemanticCache(redis_client=client)
            assert replacement.get_versioned(namespace="owned-http-erasure", request={"intent": "recall"},
                                             contract=contracts[0]) is None
            assert replacement.get_versioned(namespace="owned-http-erasure", request={"intent": "recall"},
                contract=contracts[1])["private_canary"] == foreign_canary
            remaining = http.get(second["base_url"] + "/api/v1/privacy/export/" + uid,
                                 headers=owner, timeout=10)
            assert remaining.status_code == 403 and subject_canary not in remaining.text
            repeated = http.delete(second["base_url"] + path, headers=owner, timeout=15)
            assert repeated.status_code == 200 and repeated.json()["status"] == "completed"
    finally:
        own.erase_subject(uid)
        foreign.erase_subject(uid)
        for contract in contracts:
            cache.erase_scope(contract)
        client.close()
