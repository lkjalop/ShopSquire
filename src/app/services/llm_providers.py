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
        self.endpoint = os.getenv("ANTHROPIC_API_URL", "https://api.anthropic.com/v1/messages")

    def generate(self, prompt: str, **kwargs) -> Dict[str, Any]:
        if not self.api_key:
            return {"provider": self.name, "text": "[anthropic stub response]", "raw": None}
        try:
            import requests

            model = kwargs.get("model", "claude-sonnet-4-20250514")
            payload = {
                "model": model,
                "max_tokens": kwargs.get("max_tokens", 1024),
                "messages": [{"role": "user", "content": prompt}],
            }
            headers = {
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            }
            resp = requests.post(self.endpoint, json=payload, headers=headers, timeout=30)
            try:
                j = resp.json()
            except Exception:
                j = {"status_code": resp.status_code, "text": resp.text}
            # Extract text from Messages API response
            txt = None
            try:
                content = j.get("content", [])
                if isinstance(content, list) and content:
                    txt = content[0].get("text")
            except Exception:
                pass
            if not txt:
                txt = j.get("completion") or j.get("text") or str(j)
            return {"provider": self.name, "text": txt, "raw": j, "model": model}
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
        self.endpoint = os.getenv("MISTRAL_API_URL", "https://api.mistral.ai/v1/chat/completions")

    def generate(self, prompt: str, **kwargs) -> Dict[str, Any]:
        if not self.api_key:
            return {"provider": self.name, "text": "[mistral stub response]", "raw": None}
        try:
            import requests

            model = kwargs.get("model", "mistral-small-latest")
            payload = {
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": kwargs.get("max_tokens", 512),
            }
            headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
            resp = requests.post(self.endpoint, json=payload, headers=headers, timeout=30)
            try:
                j = resp.json()
            except Exception:
                j = {"status_code": resp.status_code, "text": resp.text}
            txt = None
            try:
                if isinstance(j, dict) and j.get("choices"):
                    first = j["choices"][0]
                    if isinstance(first, dict):
                        txt = first.get("message", {}).get("content") or first.get("text")
            except Exception:
                pass
            if not txt:
                txt = j.get("text") or j.get("output") or str(j)
            return {"provider": self.name, "text": txt, "raw": j, "model": model}
        except Exception as e:
            return {"provider": self.name, "text": f"[mistral error: {e}]", "raw": None}


# Adapter aliases for clarity in admin/config (no-op wrappers around providers)
class AnthropicAdapter(AnthropicProvider):
    name = "anthropic"


class OpenAIAdapter(OpenAIProvider):
    name = "openai"


class MistralAdapter(MistralProvider):
    name = "mistral"


# ── Provider registry ──

_PROVIDER_MAP: Dict[str, type] = {
    "anthropic": AnthropicProvider,
    "openai": OpenAIProvider,
    "mistral": MistralProvider,
}


def get_provider(name: str | None = None) -> BaseLLMProvider:
    """Return a provider instance by name, or auto-select based on available keys."""
    if name and name.lower() in _PROVIDER_MAP:
        return _PROVIDER_MAP[name.lower()]()

    # Auto-select: prefer the first provider with an API key
    if os.getenv("ANTHROPIC_API_KEY"):
        return AnthropicProvider()
    if os.getenv("OPENAI_API_KEY"):
        return OpenAIProvider()
    if os.getenv("MISTRAL_API_KEY"):
        return MistralProvider()

    # Default fallback (will return stub responses)
    default = os.getenv("LLM_PROVIDER", "openai").lower()
    return _PROVIDER_MAP.get(default, OpenAIProvider)()


def list_providers() -> list[Dict[str, Any]]:
    """List all available providers and their readiness status."""
    results = []
    for name, cls in _PROVIDER_MAP.items():
        instance = cls()
        has_key = bool(getattr(instance, "api_key", None))
        results.append({
            "name": name,
            "ready": has_key,
            "endpoint": getattr(instance, "endpoint", None),
        })
    return results
