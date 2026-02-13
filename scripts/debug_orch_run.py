import sys
import traceback
# add workspace root to path
sys.path.insert(0, r"c:\AI\ShopSquire")
from src.app.services.orchestrator import Orchestrator
from src.app.security.firewall import TransactionFirewall

class DummyMemory:
    def __init__(self):
        self._ctx = {"kv": {}, "summary": None}
    def get_context(self, uid: str):
        return self._ctx
    def set_recent_retrieval(self, uid: str, facts: dict):
        pass

flags = {"AUTO_CV_DECISIONS_ENABLED": True, "DECISION_LOG_WRITES_ENABLED": False}
mem = DummyMemory()
fw = TransactionFirewall(flags={})
orch = Orchestrator(mem, fw, flags)

payload = {"query": "return my laptop", "cv_tier2": {"decision_action": "approve", "verdict": {"verdict": "approve", "score": 0.12}}, "cart_total_cents": 1000}

def tracer(frame, event, arg):
    co = frame.f_code
    lineno = frame.f_lineno
    fname = co.co_filename
    name = co.co_name
    if 'orchestrator.py' in fname and ('run' in name or 'Orchestrator' in name):
        print(f"TRACE {event} {name} {fname}:{lineno}")
    return tracer

sys.settrace(tracer)
try:
    res = orch.run(uid="user123", payload=payload, simulate_only=True)
    print('RESULT:', res)
except Exception:
    traceback.print_exc()
finally:
    sys.settrace(None)
