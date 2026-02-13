from pathlib import Path
import traceback
s = Path('src/app/security/observer.py').read_text()
try:
    compile(s, 'src/app/security/observer.py', 'exec')
    print('compiled ok')
except Exception:
    traceback.print_exc()
