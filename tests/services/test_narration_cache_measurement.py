from src.app.services.recommend_narration_jobs import (
    narration_decision_fingerprint,
    observe_narration_fingerprint,
)


class RedisStub:
    def __init__(self):
        self.values = {}

    def set(self, key, value, nx=False, ex=None):
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True


def test_narration_fingerprint_changes_for_commercially_material_inputs():
    base = {
        "tenant_id": "t1", "subject_id": "buyer-1", "session_epoch": "e1",
        "decision_id": "D1", "sku": "SKU-1", "quantity": 40, "currency": "AUD",
        "destination_token": "SYD", "required_by": "2026-09-18",
        "evidence_digest": "evidence-v1", "model_version": "m1", "prompt_version": "p1",
        "policy_version": "policy-1",
    }
    assert narration_decision_fingerprint(base) == narration_decision_fingerprint(dict(base))
    assert narration_decision_fingerprint(base) != narration_decision_fingerprint({**base, "quantity": 80})
    assert narration_decision_fingerprint(base) != narration_decision_fingerprint({**base, "evidence_digest": "evidence-v2"})


def test_narration_fingerprint_observation_measures_duplicates_without_reusing_prose():
    redis = RedisStub()
    first = observe_narration_fingerprint(redis, tenant_id="t1", subject_id="buyer-1",
                                          session_epoch="e1", fingerprint="abc")
    second = observe_narration_fingerprint(redis, tenant_id="t1", subject_id="buyer-1",
                                           session_epoch="e1", fingerprint="abc")

    assert first["outcome"] == "first_seen"
    assert second["outcome"] == "duplicate_candidate"
    assert second["prose_reused"] is False
