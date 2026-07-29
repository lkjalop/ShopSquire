from __future__ import annotations

import subprocess

from src.app.workers.leased_beat import _terminate_child


class _Child:
    def __init__(self, *, stuck: bool) -> None:
        self.stuck = stuck
        self.terminated = False
        self.killed = False

    def poll(self):
        if self.killed or (self.terminated and not self.stuck):
            return 0
        return None

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.killed = True

    def wait(self, timeout):
        del timeout
        if self.poll() is None:
            raise subprocess.TimeoutExpired("beat", 1)
        return 0


def test_terminate_child_escalates_to_kill() -> None:
    child = _Child(stuck=True)
    assert _terminate_child(child, grace_seconds=0.1) is True
    assert child.terminated is True
    assert child.killed is True


def test_terminate_child_does_not_kill_clean_exit() -> None:
    child = _Child(stuck=False)
    assert _terminate_child(child, grace_seconds=0.1) is True
    assert child.terminated is True
    assert child.killed is False
