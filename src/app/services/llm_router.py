from typing import Dict, Optional
from src.app.services.llm_providers import AnthropicProvider, OpenAIProvider, MistralProvider, BaseLLMProvider
import os


class ProviderRouter:
    """Simple multi-provider router for LLM calls.

    Selection rules (basic):
      - prefer: explicit provider name if available
      - tier 3 -> prefer Anthropic
      - tier 2 -> prefer OpenAI
      - tier 1 -> prefer Mistral (cost-efficient) then OpenAI
      - fallback: first available provider
    """

    def __init__(self, providers: Optional[Dict[str, BaseLLMProvider]] = None):
        self.providers: Dict[str, BaseLLMProvider] = providers or {}
        self.stats: Dict[str, int] = {"attempts": 0}
        # register default providers if not provided
        if not self.providers:
            try:
                self.providers = {
                    'anthropic': AnthropicProvider(),
                    'openai': OpenAIProvider(),
                    'mistral': MistralProvider(),
                }
            except Exception:
                # defensive: at least keep an empty dict
                self.providers = {}

    def register(self, name: str, provider: BaseLLMProvider):
        self.providers[name] = provider

    def select_provider(self, tier: int = 1, prefer: Optional[str] = None) -> Optional[BaseLLMProvider]:
        # Env-driven preference chain (comma-separated)
        chain_env = os.getenv("LLM_PROVIDER_CHAIN", "")
        chain = [p.strip().lower() for p in chain_env.split(",") if p.strip()] if chain_env else []
        # Optional per-tier overrides
        tier_map = {
            3: os.getenv("LLM_PROVIDER_TIER_PREMIUM"),
            2: os.getenv("LLM_PROVIDER_TIER_STANDARD"),
            1: os.getenv("LLM_PROVIDER_TIER_CHEAP"),
        }
        if prefer and prefer in self.providers:
            return self.providers.get(prefer)

        # Tier mapping
        override = tier_map.get(tier)
        if override and override in self.providers:
            return self.providers[override]
        if tier >= 3 and 'anthropic' in self.providers:
            return self.providers['anthropic']
        if tier == 2 and 'openai' in self.providers:
            return self.providers['openai']
        if tier == 1:
            if 'mistral' in self.providers:
                return self.providers['mistral']
            if 'openai' in self.providers:
                return self.providers['openai']

        # fallback to any available
        for p in (chain or ['openai', 'anthropic', 'mistral']):
            if p in self.providers:
                return self.providers[p]

        # last resort: return first registered
        return next(iter(self.providers.values()), None)

    def generate(self, prompt: str, tier: int = 1, prefer: Optional[str] = None, **kwargs) -> Dict:
        provider = self.select_provider(tier=tier, prefer=prefer)
        if provider is None:
            return {"error": "no_provider_available", "text": None}
        try:
            self.stats["attempts"] = int(self.stats.get("attempts", 0)) + 1
            return provider.generate(prompt, **kwargs)
        except Exception as e:
            return {"error": "provider_call_failed", "exception": str(e)}


# Convenience singleton router using environment at import-time
_GLOBAL = None

def get_global_router() -> ProviderRouter:
    global _GLOBAL
    if _GLOBAL is None:
        _GLOBAL = ProviderRouter()
    return _GLOBAL

def generate_text(prompt: str, tier: int = 1, prefer: Optional[str] = None, **kwargs) -> Dict:
    r = get_global_router()
    return r.generate(prompt, tier=tier, prefer=prefer, **kwargs)
