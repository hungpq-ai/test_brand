import os
import re
from openai import AsyncOpenAI
from .base import BaseEngine, EngineResponse, RateLimiter, KeyPool

try:
    import anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False


class ClaudeEngine(BaseEngine):
    name = "claude"

    def __init__(self, model: str = "claude-sonnet-4-20250514", rpm: int = 50):
        super().__init__(model, rpm)

        # Multi-provider fallback support with per-provider KeyPool
        self._providers = []
        total_keys = 0

        # Model name mapping per provider
        yescale_model = os.getenv("YESCALE_CLAUDE_MODEL", "claude-haiku-4.5")
        deepbricks_model = os.getenv("DEEPBRICKS_CLAUDE_MODEL", "claude-haiku-4.5")

        # Provider 1: Yescale (primary) - Native Anthropic API
        yescale_pool = KeyPool.from_env_optional("YESCALE_CLAUDE_API_KEY")
        if yescale_pool is None:
            yescale_pool = KeyPool.from_env_optional("CLAUDE_API_KEY")
        # Remove /v1 suffix as Anthropic SDK adds its own path
        yescale_url = os.getenv("YESCALE_BASE_URL", "https://api.yescale.io/v1").rstrip("/v1")
        if yescale_pool and ANTHROPIC_AVAILABLE:
            clients = {
                key: anthropic.AsyncAnthropic(api_key=key, base_url=yescale_url)
                for key in yescale_pool.keys
            }
            self._providers.append({
                "name": "Yescale",
                "type": "anthropic",
                "key_pool": yescale_pool,
                "clients": clients,
                "model": yescale_model,
            })
            total_keys += len(yescale_pool)

        # Provider 2: DeepBricks (fallback) - OpenAI-compatible
        deepbricks_pool = KeyPool.from_env_optional("DEEPBRICKS_API_KEY")
        deepbricks_url = os.getenv("DEEPBRICKS_BASE_URL", "https://api.deepbricks.ai/v1")
        if deepbricks_pool:
            clients = {
                key: AsyncOpenAI(api_key=key, base_url=deepbricks_url)
                for key in deepbricks_pool.keys
            }
            self._providers.append({
                "name": "DeepBricks",
                "type": "openai",
                "key_pool": deepbricks_pool,
                "clients": clients,
                "model": deepbricks_model,
            })
            total_keys += len(deepbricks_pool)

        # Legacy fallback
        if not self._providers:
            legacy_pool = KeyPool.from_env_optional("CLAUDE_API_KEY") or KeyPool.from_env("OPENAI_API_KEY")
            base_url = os.getenv("CLAUDE_BASE_URL") or os.getenv("OPENAI_BASE_URL")
            clients = {
                key: AsyncOpenAI(api_key=key, base_url=base_url)
                for key in legacy_pool.keys
            }
            self._providers.append({
                "name": "OpenAI-Compatible",
                "type": "openai",
                "key_pool": legacy_pool,
                "clients": clients,
                "model": model,
            })
            total_keys += len(legacy_pool)

        self._current_provider_idx = 0
        self.rate_limiter = RateLimiter(rpm, total_keys)

    def _next_provider(self):
        """Get next provider with active keys (round-robin)."""
        for _ in range(len(self._providers)):
            provider = self._providers[self._current_provider_idx % len(self._providers)]
            self._current_provider_idx += 1
            if provider["key_pool"].active_count() > 0:
                return provider
        raise ValueError("No active Claude providers available")

    async def query(self, prompt: str) -> EngineResponse:
        """Query with automatic fallback across providers and keys."""
        last_error = None

        for _ in range(len(self._providers)):
            try:
                provider = self._next_provider()
            except ValueError:
                break

            # Try all keys within this provider
            key_pool = provider["key_pool"]
            for _ in range(len(key_pool)):
                try:
                    key = key_pool.next_key()
                except ValueError:
                    break  # All keys in this provider exhausted

                client = provider["clients"][key]
                model_to_use = provider.get("model", self.model)
                provider_type = provider.get("type", "openai")
                system_prompt = os.getenv("CLAUDE_SYSTEM_PROMPT", "")

                try:
                    # Handle Anthropic native API
                    if provider_type == "anthropic":
                        response = await client.messages.create(
                            model=model_to_use,
                            max_tokens=4096,
                            temperature=0.7,
                            system=system_prompt if system_prompt else None,
                            messages=[{"role": "user", "content": prompt}],
                            timeout=60.0,
                        )
                        text = response.content[0].text if response.content else ""
                    # Handle OpenAI-compatible API
                    else:
                        messages = []
                        if system_prompt:
                            messages.append({"role": "system", "content": system_prompt})
                        messages.append({"role": "user", "content": prompt})

                        response = await client.chat.completions.create(
                            model=model_to_use,
                            messages=messages,
                            temperature=0.7,
                            timeout=60.0,
                        )
                        text = response.choices[0].message.content or ""

                    # Extract URLs from response text
                    url_pattern = r'https?://[^\s\)\]\},<>"\']+'
                    citations = list(set(re.findall(url_pattern, text)))

                    return EngineResponse(
                        engine=self.name,
                        prompt=prompt,
                        response_text=text,
                        citations=citations,
                    )

                except Exception as e:
                    error_msg = str(e)
                    last_error = e

                    # Quota/auth errors → mark key exhausted
                    if "401" in error_msg or "quota" in error_msg.lower() or "exhausted" in error_msg.lower():
                        print(f"🔄 {provider['name']} key exhausted, rotating... ({key_pool.active_count()-1}/{len(key_pool)} remaining)")
                        key_pool.mark_exhausted(key)
                        continue

                    # Rate limit → try next key
                    if "429" in error_msg or "rate_limit" in error_msg.lower():
                        print(f"⏱️ {provider['name']} rate limited, rotating key...")
                        continue

                    # Other errors → try next key
                    print(f"❌ {provider['name']} error: {error_msg[:100]}")
                    continue

        raise Exception(f"All Claude providers failed. Last error: {last_error}")
