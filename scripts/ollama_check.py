import requests
import sys

url = 'http://127.0.0.1:11434/api/generate'
payload = {
    'model': 'llama3:8b',
    'prompt': 'Hello',
    'stream': False,
    'options': {'temperature': 0.2, 'num_predict': 8},
}
try:
    r = requests.post(url, json=payload, timeout=30)
    print('STATUS', r.status_code)
    print(r.text[:1000])
except Exception as e:
    print('ERR', e)
    sys.exit(2)
