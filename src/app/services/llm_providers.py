import os
from typing import Any, Dict

from src.app.security.provider_boundary import require_provider_transfer, sanitize_for_provider
from src.app.services.secrets_manager import get_secret


def invocation_version_trace(
    provider: str,
    model: str,
    values: Dict[str, Any],
) -> Dict[str, str]:
    """Return explicit model/prompt/policy versions for decision traces."""
    return {
        "provider": provider,
        "model": str(model),
        "model_version": str(
            values.get("model_version")
            or os.getenv("MODEL_VERSION")
            or model
        ),
        "prompt_version": str(
            values.get("prompt_version")
            or os.getenv("PROMPT_VERSION")
            or "unversioned"
        ),
        "policy_version": str(
            values.get("policy_version")
            or os.getenv("POLICY_VERSION")
            or "unversioned"
        ),
    }


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
            raise RuntimeError(
                "AnthropicProvider: ANTHROPIC_API_KEY not configured. "
                "Set the environment variable or choose a different provider."
            )
        model = kwargs.get("model", "claude-sonnet-4-20250514")
        trace = invocation_version_trace(self.name, model, kwargs)
        try:
            import requests

            prompt, _, _ = sanitize_for_provider("anthropic", prompt, data_categories=["llm_prompt"])
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
            return {**trace, "text": txt, "raw": j}
        except Exception as e:
            return {**trace, "text": f"[anthropic error: {e}]", "raw": None}


class OpenAIProvider(BaseLLMProvider):
    name = "openai"

    def __init__(self):
        self.api_key = os.getenv("OPENAI_API_KEY")
        self.endpoint = os.getenv("OPENAI_API_URL", "https://api.openai.com/v1/chat/completions")

    def generate(self, prompt: str, **kwargs) -> Dict[str, Any]:
        if not self.api_key:
            raise RuntimeError(
                "OpenAIProvider: OPENAI_API_KEY not configured. "
                "Set the environment variable or choose a different provider."
            )
        model = kwargs.get("model", "gpt-4o-mini")
        trace = invocation_version_trace(self.name, model, kwargs)
        try:
            import requests

            prompt, _, _ = sanitize_for_provider("openai", prompt, data_categories=["llm_prompt"])
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
            return {**trace, "text": txt, "raw": j}
        except Exception as e:
            return {**trace, "text": f"[openai error: {e}]", "raw": None}


class MistralProvider(BaseLLMProvider):
    name = "mistral"

    def __init__(self):
        self.api_key = os.getenv("MISTRAL_API_KEY")
        self.endpoint = os.getenv("MISTRAL_API_URL", "https://api.mistral.ai/v1/chat/completions")

    def generate(self, prompt: str, **kwargs) -> Dict[str, Any]:
        if not self.api_key:
            raise RuntimeError(
                "MistralProvider: MISTRAL_API_KEY not configured. "
                "Set the environment variable or choose a different provider."
            )
        model = kwargs.get("model", "mistral-small-latest")
        trace = invocation_version_trace(self.name, model, kwargs)
        try:
            import requests

            prompt, _, _ = sanitize_for_provider("mistral", prompt, data_categories=["llm_prompt"])
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
            return {**trace, "text": txt, "raw": j}
        except Exception as e:
            return {**trace, "text": f"[mistral error: {e}]", "raw": None}


# Adapter aliases for clarity in admin/config (no-op wrappers around providers)
class AnthropicAdapter(AnthropicProvider):
    name = "anthropic"


class OpenAIAdapter(OpenAIProvider):
    name = "openai"


class MistralAdapter(MistralProvider):
    name = "mistral"


class AzureFoundryProvider(BaseLLMProvider):
    """OpenAI-compatible Azure AI Foundry adapter with workload identity."""

    name = "azure-foundry"

    def __init__(self):
        self.endpoint = os.getenv("AZURE_AI_FOUNDRY_ENDPOINT", "").rstrip("/")
        self.deployment = os.getenv("AZURE_AI_FOUNDRY_DEPLOYMENT", "")
        self.api_version = os.getenv(
            "AZURE_AI_FOUNDRY_API_VERSION",
            "2024-10-21",
        )
        self.api_key = get_secret("AZURE_AI_FOUNDRY_API_KEY")

    def _authorization_headers(self) -> Dict[str, str]:
        if self.api_key:
            return {"api-key": self.api_key}
        try:
            from src.app.providers.azure import get_cognitive_token

            return {"Authorization": f"Bearer {get_cognitive_token()}"}
        except Exception as exc:
            raise RuntimeError("azure_foundry_identity_unavailable") from exc

    def generate(self, prompt: str, **kwargs) -> Dict[str, Any]:
        if not self.endpoint or not self.deployment:
            raise RuntimeError("AzureFoundryProvider: endpoint/deployment not configured")
        model = str(kwargs.get("model") or self.deployment)
        trace = invocation_version_trace(self.name, model, kwargs)
        try:
            import requests

            prompt, _, _ = sanitize_for_provider(
                self.name,
                prompt,
                data_categories=["llm_prompt"],
            )
            url = (
                f"{self.endpoint}/openai/deployments/{self.deployment}"
                f"/chat/completions?api-version={self.api_version}"
            )
            headers = {
                **self._authorization_headers(),
                "Content-Type": "application/json",
            }
            payload = {
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": kwargs.get("max_tokens", 512),
            }
            response = requests.post(url, json=payload, headers=headers, timeout=30)
            body = response.json()
            text = None
            if isinstance(body, dict) and body.get("choices"):
                text = body["choices"][0].get("message", {}).get("content")
            return {**trace, "text": text or str(body), "raw": body}
        except Exception as exc:
            return {**trace, "text": f"[azure-foundry error: {exc}]", "raw": None}


class OllamaProvider(BaseLLMProvider):
    """Local air-gapped Ollama provider. No data leaves the host — GDPR/data-sovereignty safe."""
    name = "ollama"

    def __init__(self):
        self.base_url = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
        self.default_model = os.getenv("EMAIL_SECURITY_LLM_MODEL", os.getenv("OLLAMA_SMALL_MODEL", "qwen2.5:14b"))

    def generate(self, prompt: str, **kwargs) -> Dict[str, Any]:
        model = kwargs.get("model", self.default_model)
        trace = invocation_version_trace(self.name, model, kwargs)
        try:
            import requests

            payload = {
                "model": model,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": kwargs.get("temperature", 0.1), "num_predict": kwargs.get("max_tokens", 512)},
            }
            if kwargs.get("format"):
                payload["format"] = kwargs["format"]
            if "think" in kwargs:
                payload["think"] = bool(kwargs["think"])
            elif "qwen3" in str(model).lower():
                # Structured and bounded commerce roles must not return hidden-reasoning wrappers.
                payload["think"] = False
            timeout_s = max(1.0, min(float(kwargs.get("timeout_s", 30.0)), 180.0))
            r = requests.post(f"{self.base_url}/api/generate", json=payload, timeout=timeout_s)
            r.raise_for_status()
            j = r.json()
            txt = str(j.get("response") or "").strip()
            return {**trace, "text": txt, "raw": j}
        except Exception as e:
            return {**trace, "text": f"[ollama error: {e}]", "raw": None}


# ── Provider registry ──

_PROVIDER_MAP: Dict[str, type] = {
    "anthropic": AnthropicProvider,
    "openai": OpenAIProvider,
    "mistral": MistralProvider,
    "azure-foundry": AzureFoundryProvider,
    "ollama": OllamaProvider,
}


def get_provider(name: str | None = None) -> BaseLLMProvider:
    """Return a provider instance by name, or auto-select based on available keys."""
    if name and name.lower() in _PROVIDER_MAP:
        require_provider_transfer(name.lower(), data_categories=["llm_prompt"])
        return _PROVIDER_MAP[name.lower()]()

    # Auto-select: Ollama first (air-gapped, data-sovereign); then external APIs
    if os.getenv("OLLAMA_URL") or os.getenv("EMAIL_SECURITY_LLM_PROVIDER", "").lower() == "ollama":
        return OllamaProvider()
    if os.getenv("ANTHROPIC_API_KEY"):
        require_provider_transfer("anthropic", data_categories=["llm_prompt"])
        return AnthropicProvider()
    if os.getenv("OPENAI_API_KEY"):
        require_provider_transfer("openai", data_categories=["llm_prompt"])
        return OpenAIProvider()
    if os.getenv("MISTRAL_API_KEY"):
        require_provider_transfer("mistral", data_categories=["llm_prompt"])
        return MistralProvider()
    if os.getenv("AZURE_AI_FOUNDRY_ENDPOINT"):
        require_provider_transfer("azure-foundry")
        return AzureFoundryProvider()

    # No API key configured for any provider — fail closed rather than return stub text.
    # Callers should catch RuntimeError and degrade gracefully (e.g., skip LLM enrichment).
    configured = os.getenv("LLM_PROVIDER", "").lower()
    if configured and configured in _PROVIDER_MAP:
        # Caller explicitly requested a provider — let it raise on first use
        return _PROVIDER_MAP[configured]()
    raise RuntimeError(
        "No LLM provider API key is configured. "
        "Set a supported cloud API key, Azure Foundry endpoint, or local Ollama URL."
    )


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
