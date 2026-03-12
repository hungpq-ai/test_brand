import os
from openai import AsyncOpenAI
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from .base import BaseEngine, EngineResponse, RateLimiter


class ClaudeEngine(BaseEngine):
    name = "claude"

    def __init__(self, model: str = "claude-sonnet-4-20250514", rpm: int = 50):
        super().__init__(model, rpm)

        # Multi-provider fallback support with per-provider model names
        self._providers = []

        # Model name mapping per provider
        yescale_model = os.getenv("YESCALE_CLAUDE_MODEL", "claude-haiku-4.5")
        deepbricks_model = os.getenv("DEEPBRICKS_CLAUDE_MODEL", "claude-haiku-4.5")

        # Provider 1: Yescale (primary)
        yescale_key = os.getenv("YESCALE_CLAUDE_API_KEY") or os.getenv("CLAUDE_API_KEY")
        yescale_url = os.getenv("YESCALE_BASE_URL", "https://api.yescale.one/v1")
        if yescale_key:
            self._providers.append({
                "name": "Yescale",
                "client": AsyncOpenAI(api_key=yescale_key, base_url=yescale_url),
                "model": yescale_model,
                "active": True
            })

        # Provider 2: DeepBricks (fallback) - single key for all models
        deepbricks_key = os.getenv("DEEPBRICKS_API_KEY")
        deepbricks_url = os.getenv("DEEPBRICKS_BASE_URL", "https://api.deepbricks.ai/v1")
        if deepbricks_key:
            self._providers.append({
                "name": "DeepBricks",
                "client": AsyncOpenAI(api_key=deepbricks_key, base_url=deepbricks_url),
                "model": deepbricks_model,
                "active": True
            })

        # Legacy fallback
        if not self._providers:
            base_url = os.getenv("CLAUDE_BASE_URL") or os.getenv("OPENAI_BASE_URL")
            raw_keys = os.getenv("CLAUDE_API_KEY") or os.getenv("OPENAI_API_KEY", "")
            api_keys = [k.strip() for k in raw_keys.split(",") if k.strip()]

            if not api_keys:
                raise ValueError("No Claude API keys configured. Set YESCALE_CLAUDE_API_KEY, DEEPBRICKS_API_KEY, or CLAUDE_API_KEY")

            for key in api_keys:
                self._providers.append({
                    "name": "OpenAI-Compatible",
                    "client": AsyncOpenAI(api_key=key, base_url=base_url),
                    "active": True
                })

        self._current_provider_idx = 0
        self.rate_limiter = RateLimiter(rpm, len(self._providers))

    def _next_provider(self):
        """Get next active provider (round-robin)"""
        for _ in range(len(self._providers)):
            provider = self._providers[self._current_provider_idx % len(self._providers)]
            self._current_provider_idx += 1
            if provider["active"]:
                return provider
        raise ValueError("No active Claude providers available")

    def _mark_provider_inactive(self, provider_name: str):
        """Temporarily mark provider as inactive after quota errors"""
        for p in self._providers:
            if p["name"] == provider_name:
                p["active"] = False
                print(f"⚠️ {provider_name} marked inactive due to quota/auth error")

    async def query(self, prompt: str) -> EngineResponse:
        """Query with automatic fallback across providers"""
        last_error = None

        # Try all active providers
        for attempt in range(len(self._providers)):
            provider = self._next_provider()

            try:
                # Use provider-specific model name
                model_to_use = provider.get("model", self.model)
                response = await provider["client"].chat.completions.create(
                    model=model_to_use,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.7,
                    timeout=30.0,
                )
                text = response.choices[0].message.content or ""
                return EngineResponse(
                    engine=self.name,
                    prompt=prompt,
                    response_text=text,
                )

            except Exception as e:
                error_msg = str(e)
                last_error = e

                # Check for quota/auth errors
                if "401" in error_msg or "quota" in error_msg.lower() or "exhausted" in error_msg.lower():
                    print(f"🔄 {provider['name']} quota exceeded, trying fallback...")
                    self._mark_provider_inactive(provider["name"])
                    continue

                # Check for rate limit errors
                elif "429" in error_msg or "rate_limit" in error_msg.lower():
                    print(f"⏱️ {provider['name']} rate limited, trying fallback...")
                    continue

                # Other errors - try next provider
                else:
                    print(f"❌ {provider['name']} error: {error_msg[:100]}")
                    continue

        # All providers failed
        raise Exception(f"All Claude providers failed. Last error: {last_error}")
