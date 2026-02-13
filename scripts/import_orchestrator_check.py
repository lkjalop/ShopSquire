import importlib

try:
    importlib.import_module('src.app.services.orchestrator')
    print('import_ok')
except Exception as e:
    import traceback

    traceback.print_exc()
    raise SystemExit(2)
