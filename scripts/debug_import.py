import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
print('ROOT added', ROOT)
from src.app.main import create_app
print('create_app imported', callable(create_app))
app = create_app()
print('app created', app)
