import os
import requests
import sys

API_BASE = os.getenv("API_BASE", "http://127.0.0.1:8080")
HEADERS = {"x-api-key": "local-merchant-key"}

def pretty(resp):
    try:
        return resp.status_code, resp.json()
    except Exception:
        return resp.status_code, resp.text


def test_recommend():
    url = f"{API_BASE}/api/v1/recommend/suggest"
    params = {"uid": "smoke-user", "query": "laptops under 2000"}
    print(f"GET {url} params={params}")
    r = requests.get(url, params=params, headers=HEADERS, timeout=15)
    print(pretty(r))


def test_chat():
    url = f"{API_BASE}/api/v1/chat/query"
    payload = {"query": "show laptops under 2000", "uid": "smoke-user"}
    print(f"POST {url} json={payload}")
    r = requests.post(url, json=payload, headers=HEADERS, timeout=20)
    print(pretty(r))


def test_ollama():
    url = f"{API_BASE}/api/v1/chat/ollama_test"
    payload = {"query": "Find best laptops for remote work with 16gb RAM"}
    print(f"POST {url} json={payload}")
    r = requests.post(url, json=payload, headers=HEADERS, timeout=30)
    print(pretty(r))


def test_vision():
    url = f"{API_BASE}/api/v1/vision/triage"
    # create a tiny 1x1 PNG
    png = bytes.fromhex(
        "89504e470d0a1a0a0000000d4948445200000001000000010806000000" 
        "1f15c4890000000a49444154789c6360000002000100e221bc33000000" 
        "0049454e44ae426082"
    )
    files = {"image": ("smoke.png", png, "image/png")}
    print(f"POST {url} file=smoke.png")
    r = requests.post(url, files=files, headers=HEADERS, timeout=15)
    print(pretty(r))


if __name__ == '__main__':
    print("Running ShopSquire smoke tests against:", API_BASE)
    try:
        test_recommend()
    except Exception as e:
        print("recommend failed:", e)
    try:
        test_chat()
    except Exception as e:
        print("chat failed:", e)
    try:
        test_ollama()
    except Exception as e:
        print("ollama test failed:", e)
    try:
        test_vision()
    except Exception as e:
        print("vision failed:", e)
    print("Smoke tests complete")
