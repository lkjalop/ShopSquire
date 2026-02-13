import requests
import sys

trace = sys.argv[1] if len(sys.argv) > 1 else 'demo-1770544601-33c62750'
url = f'http://127.0.0.1:8081/api/v1/decisions/{trace}'
headers = {'x-api-key': 'local-developer-key'}
try:
    r = requests.get(url, headers=headers, timeout=5)
    print(r.status_code)
    print(r.text)
except Exception as e:
    print('ERROR', e)
