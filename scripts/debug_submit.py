import io, os, sys
from pathlib import Path
from fastapi.testclient import TestClient
# Ensure repo root on sys.path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from src.app.main import create_app

os.environ["DATABASE_URL"] = "sqlite+pysqlite:///tmp/debug_pipeline.sqlite"
app = create_app()
client = TestClient(app)

png_bytes = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde"
    b"\x00\x00\x00\x0cIDAT\x08\x99c``\xf8\x0f\x00\x01\x05\x01\x00\x18\x9d\x9c\x1e\x00\x00\x00\x00IEND\xAE\x42\x60\x82"
)
files = [("images", ("a.png", io.BytesIO(png_bytes), "image/png"))]
payload = {"order_id": "ORDER9", "issue_type": "damage", "description": "cracked screen"}
resp = client.post("/api/v1/support/complaints/submit", data=payload, files=files)
print('status_code=', resp.status_code)
try:
    data = resp.json()
except Exception as e:
    print('json error', e)
    print('text:', resp.text)
    sys.exit(1)
print('json:', data)
