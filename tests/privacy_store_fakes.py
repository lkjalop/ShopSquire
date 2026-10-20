"""Acknowledging shared-store contract for isolated privacy API tests."""


class SharedStore:
    is_shared_backend = True

    def __init__(self):
        self.values = {}

    def get(self, key):
        return self.values.get(key)

    def set(self, key, value):
        self.values[key] = value
        return True
