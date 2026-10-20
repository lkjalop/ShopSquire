import gc
import weakref


def test_diagnostic_collection_releases_unreachable_handles_and_preserves_live_owner(tmp_path):
    from tests.conftest import collect_test_resource_garbage
    class Cycle:
        pass
    was_enabled = gc.isenabled()
    gc.disable()
    try:
        with (tmp_path / 'borrowed.txt').open('w') as borrowed:
            cycle = Cycle()
            cycle.self = cycle
            cycle.file = (tmp_path / 'unreachable.txt').open('w')
            object_ref, file_ref = weakref.ref(cycle), weakref.ref(cycle.file)
            del cycle
            assert object_ref() is not None and file_ref() is not None
            result = collect_test_resource_garbage()
            assert object_ref() is None and file_ref() is None
            assert borrowed.closed is False
            assert result['collected'] > 0
    finally:
        gc.collect()
        if was_enabled:
            gc.enable()
