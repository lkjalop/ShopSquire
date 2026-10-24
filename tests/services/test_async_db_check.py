import importlib.util
from pathlib import Path


def test_async_checker_distinguishes_thread_helper_from_direct_io(tmp_path):
    spec = importlib.util.spec_from_file_location('async_check', Path('scripts/check_async_db.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    sample = tmp_path/'route.py'
    sample.write_text('''async def route():
    def helper():
        with db_session() as db:
            return db.execute('select 1')
    await asyncio.to_thread(helper)
    with db_session() as db:
        db.execute('select 2')
''')
    failures = module.check_file(sample)
    assert len(failures) == 1
    assert failures[0][1] == 6
