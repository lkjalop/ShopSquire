import importlib
import os
import sys

# Ensure project root is on sys.path so implicit namespace package 'src' resolves
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
print(f"[check_imports] ROOT={ROOT}")
print(f"[check_imports] sys.path[0:3]={sys.path[:3]}")
print(f"[check_imports] src exists? {os.path.isdir(os.path.join(ROOT, 'src'))}")

modules = [
    'src.app.routers.admin',
    'src.app.routers.decisions',
]

for m in modules:
    try:
        importlib.import_module(m)
        print(f"Imported {m} successfully")
    except Exception as e:
        print(f"Failed to import {m}: {e}")
        sys.exit(1)

print('All imports successful')
