import os


def default_headers() -> dict:
    return {"x-api-key": os.getenv("MERCHANT_API_KEY", "local-merchant-key")}
