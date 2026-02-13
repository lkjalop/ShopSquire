import os
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
LOG_DIR = BASE / "runs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
OUT = str(LOG_DIR / "uvicorn.out")
ERR = str(LOG_DIR / "uvicorn.err")
PIDF = str(LOG_DIR / "uvicorn.pid")

env = os.environ.copy()
# Respect caller-provided envs but set sensible defaults
env.setdefault("DATABASE_URL", f"sqlite+pysqlite:///{BASE / 'tmp' / 'e2e.sqlite'}")
env.setdefault("DISABLE_UI_ROUTES", "0")
env.setdefault("API_PORT", "8080")
env.setdefault("BACKPRESSURE_TEST_DELAY_SEC", "0.3")

python = sys.executable
args = [python, "-m", "uvicorn", "src.app.main:create_app", "--host", "127.0.0.1", "--port", env['API_PORT'], "--factory"]

# Windows: detach process
creationflags = 0
try:
    import subprocess as _sp
    if os.name == 'nt':
        creationflags = getattr(_sp, 'CREATE_NEW_PROCESS_GROUP', 0) | getattr(_sp, 'DETACHED_PROCESS', 0)
except Exception:
    creationflags = 0

with open(OUT, 'ab') as out, open(ERR, 'ab') as err:
    proc = subprocess.Popen(args, env=env, cwd=str(BASE), stdout=out, stderr=err, creationflags=creationflags)
    with open(PIDF, 'w') as pf:
        pf.write(str(proc.pid))
    print(f"started pid={proc.pid}")
    # Do not wait; exit so caller continues

