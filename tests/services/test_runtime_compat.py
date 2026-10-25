import builtins
import importlib.util
from enum import auto
from pathlib import Path


def test_python310_strenum_fallback_has_string_and_auto_semantics(monkeypatch):
    original = builtins.__import__
    def without_strenum(name, globals=None, locals=None, fromlist=(), level=0):
        if name == 'enum' and 'StrEnum' in fromlist:
            raise ImportError('Python 3.10')
        return original(name, globals, locals, fromlist, level)
    monkeypatch.setattr(builtins, '__import__', without_strenum)
    spec = importlib.util.spec_from_file_location('compat310', Path('src/app/compat.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    class Status(module.StrEnum):
        READY = auto()
    assert str(Status.READY) == 'ready'
    assert f'{Status.READY}' == 'ready'
    assert Status.READY == 'ready'
