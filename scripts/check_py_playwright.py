import sys
import importlib

modules = ("pytest", "playwright")
for m in modules:
    try:
        mod = importlib.import_module(m)
        v = getattr(mod, "__version__", None)
        print(f"OK {m} {v}")
    except Exception as e:
        print(f"FAIL {m} {e}", file=sys.stderr)

sys.exit(0)
