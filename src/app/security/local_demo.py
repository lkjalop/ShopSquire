"""One admission policy for explicitly local demonstration conveniences."""
import ipaddress
import os


def is_loopback_peer(request) -> bool:
    peer = getattr(getattr(request, 'client', None), 'host', None)
    try:
        return ipaddress.ip_address(peer).is_loopback
    except (TypeError, ValueError):
        return False


def allow_local_demo_request(request) -> bool:
    environment = str(os.getenv('APP_ENV') or '').strip().lower()
    if environment not in {'local', 'dev', 'development', 'test'}:
        return False
    choice = str(os.getenv('ALLOW_UNAUTH_MERCHANT_DASHBOARD') or '').strip().lower()
    if choice:
        return choice in {'1', 'true', 'yes', 'on'} and is_loopback_peer(request)
    return environment in {'local', 'dev', 'development'} and is_loopback_peer(request)
