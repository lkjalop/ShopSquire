import requests
import time
import sys

url = 'http://127.0.0.1:8080/api/v1/decisions/demo/seed'
headers = {'x-api-key': 'local-developer-key'}
for i in range(20):
    try:
        r = requests.post(url, json={}, timeout=5, headers=headers)
        print('STATUS', r.status_code)
        print(r.text)
        sys.exit(0)
    except Exception as e:
        print('retry', i, 'error', str(e))
        time.sleep(0.5)
print('FAILED')
