import requests
import sys
import time

trace = sys.argv[1] if len(sys.argv) > 1 else 'demo-1770544601-33c62750'
url = f'http://127.0.0.1:8080/api/v1/decisions/{trace}/events/stream'
try:
    with requests.get(url, stream=True, timeout=10) as r:
        print('STATUS', r.status_code)
        if r.status_code != 200:
            print(r.text)
        else:
            start = time.time()
            for line in r.iter_lines(decode_unicode=True):
                if line:
                    print('LINE:', line)
                # stop after 5s
                if time.time() - start > 5:
                    break
except Exception as e:
    print('ERROR', e)
