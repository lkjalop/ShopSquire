from src.app.services.orchestrator import Orchestrator
from src.app.services.memory import Memory
from src.app.security.firewall import TransactionFirewall
from src.app.config import load_feature_flags, get_settings

flags = {}
try:
    flags = load_feature_flags(get_settings().feature_flags_path)
except Exception:
    pass

try:
    from src.app.deps import get_redis
    redis_client = None
    try:
        redis_client = get_redis()
    except Exception:
        redis_client = None
except Exception:
    redis_client = None
if redis_client is None:
    class _DummyRedis:
        def get(self, *_a, **_kw):
            return None

        def setex(self, *_a, **_kw):
            return None

    memory = Memory(_DummyRedis())
else:
    memory = Memory(redis_client)
firewall = TransactionFirewall(flags)
orch = Orchestrator(memory=memory, firewall=firewall, flags=flags)

payload = {"cart_total_cents": 10000, "sku": "sku-123", "tenant_id": "t1", "actor_id": "actor-1", "actor_role": "merchant"}
try:
    res = orch.run(uid="test-1", payload=payload, simulate_only=False, use_rules=False)
    print("OK", res)
except Exception as e:
    import traceback
    traceback.print_exc()
    print("Exception:", e)
