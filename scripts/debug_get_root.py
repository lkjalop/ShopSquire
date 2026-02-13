from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
import os
os.environ['DATABASE_URL'] = 'sqlite+pysqlite:///tmp/debug_root.sqlite'
from src.app.main import create_app
from fastapi.testclient import TestClient
app = create_app()
client = TestClient(app)
resp = client.get('/')
print('status', resp.status_code)
print('text', resp.text[:200])
