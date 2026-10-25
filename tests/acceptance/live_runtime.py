"""Explicit opt-in for live acceptance checks; never probe an ambient server."""
import os
from urllib.parse import urlsplit


def live_base_url():
    if os.getenv('SHOPSQUIRE_ACCEPTANCE_LIVE') != '1':
        return None
    url = os.getenv('SHOPSQUIRE_ACCEPTANCE_BASE_URL', '').rstrip('/')
    parsed = urlsplit(url)
    if (parsed.scheme not in {'http', 'https'}
            or parsed.hostname not in {'localhost', '127.0.0.1', '::1'}
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.path):
        raise ValueError('Live acceptance requires an explicit local server base URL')
    return url
