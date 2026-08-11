import inspect
import time

from src.app.services.syslog_listener import start_syslog_listener, stop_syslog_listener


def test_syslog_listener_defaults_to_loopback_and_disables_spoofable_udp():
    signature = inspect.signature(start_syslog_listener)
    assert signature.parameters["host"].default == "127.0.0.1"
    assert signature.parameters["enable_udp"].default is False


def test_tcp_listener_shutdown_joins_background_thread() -> None:
    handle = start_syslog_listener(
        host="127.0.0.1",
        tcp_port=0,
        enable_udp=False,
        enable_tcp=True,
    )
    time.sleep(0.05)

    stop_syslog_listener(handle, timeout=2.0)

    assert handle["stop_event"].is_set()
    assert all(not thread.is_alive() for thread in handle["threads"])
