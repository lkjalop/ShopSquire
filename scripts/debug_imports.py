import importlib, traceback, sys

mods = [
    'src.app.routers.cv',
    'src.app.routers.email_security',
    'src.app.main',
]

for m in mods:
    try:
        importlib.import_module(m)
        print('OK', m)
    except Exception:
        print('ERR', m)
        traceback.print_exc()
        sys.exit(1)

print('ALL_OK')
