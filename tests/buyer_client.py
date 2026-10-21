"""Signed buyer credentials for isolated API fixtures; no production override."""
import time
from urllib.parse import parse_qs, urlsplit

import jwt
from fastapi.testclient import TestClient


TEST_SIGNING_KEY = 'isolated-buyer-api-test-signing-key-never-deploy'


class BuyerTestClient(TestClient):
    def request(self, method, url, **kwargs):
        body = kwargs.get('json') or {}
        params = kwargs.get('params') or {}
        query = parse_qs(urlsplit(str(url)).query)
        uid = body.get('uid') or params.get('uid') or query.get('uid', [None])[0]
        if uid:
            now = int(time.time())
            token = jwt.encode(dict(sub=uid, typ='access', iss='shopsquire',
                aud='shopsquire-api', iat=now, exp=now+300), TEST_SIGNING_KEY, algorithm='HS256')
            headers = dict(kwargs.get('headers') or {})
            headers.setdefault('Authorization', 'Bearer '+token)
            kwargs['headers'] = headers
        return super().request(method, url, **kwargs)
