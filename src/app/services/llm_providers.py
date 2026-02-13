import os
from typing import Any, Dict


class BaseLLMProvider:
    name = "base"

    def generate(self, prompt: str, **kwargs) -> Dict[str, Any]:
        raise NotImplementedError()


class AnthropicProvider(BaseLLMProvider):
    name = "anthropic"

    def __init__(self):
        self.api_key = os.getenv("ANTHROPIC_API_KEY")
        self.endpoint = os.getenv("ANTHROPIC_API_URL", "https://api.anthropic.com/v1/complete")

    def generate(self, prompt: str, **kwargs) -> Dict[str, Any]:
        # Lightweight stub: when no API key is present return a deterministic placeholder.
        if not self.api_key:
            return {"provider": self.name, "text": "[anthropic stub response]", "raw": None}
        try:
            import requests

            payload = {"model": kwargs.get("model", "claude-2"), "prompt": prompt}
            headers = {"x-api-key": self.api_key, "Content-Type": "application/json"}
            resp = requests.post(self.endpoint, json=payload, headers=headers, timeout=10)
            try:
                j = resp.json()
            except Exception:
                j = {"status_code": resp.status_code, "text": resp.text}
            # Best-effort: try to extract a text field
            txt = j.get("completion") or j.get("text") or str(j)
            return {"provider": self.name, "text": txt, "raw": j}
        except Exception as e:
            return {"provider": self.name, "text": f"[anthropic error: {e}]", "raw": None}


class OpenAIProvider(BaseLLMProvider):
    name = "openai"

    def __init__(self):
        self.api_key = os.getenv("OPENAI_API_KEY")
        self.endpoint = os.getenv("OPENAI_API_URL", "https://api.openai.com/v1/chat/completions")

    def generate(self, prompt: str, **kwargs) -> Dict[str, Any]:
        if not self.api_key:
            return {"provider": self.name, "text": "[openai stub response]", "raw": None}
        try:
            import requests

            model = kwargs.get("model", "gpt-4o-mini")
            payload = {"model": model, "messages": [{"role": "user", "content": prompt}], "max_tokens": kwargs.get("max_tokens", 512)}
            headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
            resp = requests.post(self.endpoint, json=payload, headers=headers, timeout=10)
            try:
                j = resp.json()
            except Exception:
                j = {"status_code": resp.status_code, "text": resp.text}
            # Extract text from chat completion response if present
            txt = None
            try:
                if isinstance(j, dict) and j.get("choices"):
                    first = j["choices"][0]
                    if isinstance(first, dict):
                        txt = first.get("message", {}).get("content") or first.get("text")
            except Exception:
                txt = None
            if not txt:
                txt = j.get("text") if isinstance(j, dict) else str(j)
            return {"provider": self.name, "text": txt, "raw": j}
        except Exception as e:
            return {"provider": self.name, "text": f"[openai error: {e}]", "raw": None}


class MistralProvider(BaseLLMProvider):
    name = "mistral"

    def __init__(self):
        self.api_key = os.getenv("MISTRAL_API_KEY")
        self.endpoint = os.getenv("MISTRAL_API_URL", "https://api.mistral.ai/generate")

    def generate(self, prompt: str, **kwargs) -> Dict[str, Any]:
        if not self.api_key:
            return {"provider": self.name, "text": "[mistral stub response]", "raw": None}
        try:
            import requests

            payload = {"input": prompt, "model": kwargs.get("model", "mixtral")}
            headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
            resp = requests.post(self.endpoint, json=payload, headers=headers, timeout=10)
            try:
                j = resp.json()
            except Exception:
                j = {"status_code": resp.status_code, "text": resp.text}
            txt = j.get("text") or j.get("output") or str(j)
            return {"provider": self.name, "text": txt, "raw": j}
        except Exception as e:
            return {"provider": self.name, "text": f"[mistral error: {e}]", "raw": None}


# Adapter aliases for clarity in admin/config (no-op wrappers around providers)
class AnthropicAdapter(AnthropicProvider):
    name = "anthropic"


class OpenAIAdapter(OpenAIProvider):
    name = "openai"


class MistralAdapter(MistralProvider):
    name = "mistral"
