"""Bound process telemetry concurrency and retain application shutdown ownership."""
import logging
import threading
import time


_PROCESS_CAPACITY = threading.BoundedSemaphore(4)
_GROUP_LOCK = threading.Lock()


class ObserverWorkGroup:
    def __init__(self):
        self._lock = threading.Lock()
        self._workers = set()
        self.closed = False

    def submit(self, job):
        capacity = _PROCESS_CAPACITY
        with self._lock:
            if self.closed or not capacity.acquire(blocking=False):
                return False

            def run():
                try:
                    job()
                except Exception:
                    logging.getLogger(__name__).exception('Security observer worker failed')
                finally:
                    with self._lock:
                        self._workers.discard(threading.current_thread())
                    capacity.release()

            worker = threading.Thread(target=run, name='security-observer', daemon=True)
            self._workers.add(worker)
            try:
                worker.start()
            except BaseException:
                self._workers.discard(worker)
                capacity.release()
                raise
        return True

    def stop(self, timeout=2.0):
        with self._lock:
            self.closed = True
            workers = list(self._workers)
        deadline = time.monotonic() + timeout
        for worker in workers:
            worker.join(timeout=max(0.0, deadline - time.monotonic()))
        with self._lock:
            if self._workers:
                raise RuntimeError('Security observer workers did not stop within their shutdown budget')

    def assert_stopped(self):
        with self._lock:
            if self._workers:
                raise RuntimeError('Security observer workers are still running; database ownership must be retained')


_FALLBACK = ObserverWorkGroup()


def observer_work_group(app=None):
    if app is None:
        return _FALLBACK
    with _GROUP_LOCK:
        group = getattr(app.state, 'security_observer_work_group', None)
        if group is None:
            group = ObserverWorkGroup()
            app.state.security_observer_work_group = group
        return group


def start_security_observer(app):
    with _GROUP_LOCK:
        previous = getattr(app.state, 'security_observer_work_group', None)
        if previous is not None and previous.closed:
            previous.stop(timeout=0.0)  # Never abandon an earlier lifetime's worker.
            app.state.security_observer_work_group = ObserverWorkGroup()


def stop_security_observer(app):
    group = getattr(app.state, 'security_observer_work_group', None)
    if group is not None:
        group.stop()


def assert_security_observer_stopped(app):
    group = getattr(app.state, 'security_observer_work_group', None)
    if group is not None:
        group.assert_stopped()
