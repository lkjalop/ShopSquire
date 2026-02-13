"""Runner to exercise the new Orchestrator locally.
Usage: python scripts/run_orchestrator.py "recommend laptops"
"""
import sys
import logging
import json

class _SimpleRedis:
    def __init__(self):
        self._store = {}

    def get(self, key: str):
        return self._store.get(key)

    def setex(self, key: str, ttl: int, value: str):
        self._store[key] = value


def main(argv):
    logging.basicConfig(level=logging.INFO)
    query = argv[1] if len(argv) > 1 else "recommend laptops"
    from src.app.services.memory import Memory
    from src.app.security.firewall import TransactionFirewall
    from src.app.services.orchestrator import Orchestrator

    flags = {"POLICY_VERSION": "v1"}
    mem = Memory(redis_client=_SimpleRedis())
    fw = TransactionFirewall(flags)
    orch = Orchestrator(memory=mem, firewall=fw, flags=flags)

    payload = {"query": query, "cart_total_cents": 129999}
    res = orch.run(uid="cli-test", payload=payload)
    print(json.dumps({"proposal": res.proposal, "firewall": res.firewall}, ensure_ascii=False))


if __name__ == "__main__":
    main(sys.argv)
