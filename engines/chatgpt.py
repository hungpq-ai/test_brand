import os
import re
from openai import AsyncOpenAI
from .base import BaseEngine, EngineResponse, RateLimiter, KeyPool


class ChatGPTEngine(BaseEngine):
    name = "chatgpt"

    def __init__(self, model: str = "gpt-4o", rpm: int = 60):
        super().__init__(model, rpm)

        # Multi-provider fallback support with per-provider KeyPool
        self._providers = []
        total_keys = 0

        # Model name mapping per provider
        yescale_model = os.getenv("YESCALE_GPT_MODEL", "gpt-5.1")
        deepbricks_model = os.getenv("DEEPBRICKS_GPT_MODEL", "gpt-5.1")

        # Provider 1: Yescale (primary)
        yescale_pool = KeyPool.from_env_optional("YESCALE_API_KEY")
        yescale_url = os.getenv("YESCALE_BASE_URL", "https://api.yescale.io/v1")
        if yescale_pool:
            clients = {
                key: AsyncOpenAI(api_key=key, base_url=yescale_url, timeout=90.0)
                for key in yescale_pool.keys
            }
            self._providers.append({
                "name": "Yescale",
                "key_pool": yescale_pool,
                "clients": clients,
                "model": yescale_model,
            })
            total_keys += len(yescale_pool)

        # Provider 2: DeepBricks (fallback)
        deepbricks_pool = KeyPool.from_env_optional("DEEPBRICKS_API_KEY")
        deepbricks_url = os.getenv("DEEPBRICKS_BASE_URL", "https://api.deepbricks.ai/v1")
        if deepbricks_pool:
            clients = {
                key: AsyncOpenAI(api_key=key, base_url=deepbricks_url, timeout=90.0)
                for key in deepbricks_pool.keys
            }
            self._providers.append({
                "name": "DeepBricks",
                "key_pool": deepbricks_pool,
                "clients": clients,
                "model": deepbricks_model,
            })
            total_keys += len(deepbricks_pool)

        # Legacy fallback: Generic OpenAI-compatible config
        if not self._providers:
            base_url = os.getenv("CHATGPT_BASE_URL") or os.getenv("OPENAI_BASE_URL")
            legacy_pool = KeyPool.from_env_optional("CHATGPT_API_KEY") or KeyPool.from_env("OPENAI_API_KEY")
            clients = {
                key: AsyncOpenAI(api_key=key, base_url=base_url)
                for key in legacy_pool.keys
            }
            self._providers.append({
                "name": "OpenAI-Compatible",
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
        raise ValueError("No active ChatGPT providers available")

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
                    break  # All keys in this provider exhausted, try next provider

                client = provider["clients"][key]
                model_to_use = provider.get("model", self.model)

                try:
                    # Build messages with optional system prompt
                    messages = []
                    system_prompt = os.getenv("CHATGPT_SYSTEM_PROMPT", "")
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

                    # DEBUG
                    debug_mode = os.getenv("DEBUG_API_RESPONSES", "false").lower() == "true"
                    if debug_mode:
                        print(f"\n{'='*80}")
                        print(f"CHATGPT RAW RESPONSE DEBUG ({provider['name']})")
                        print(f"{'='*80}")
                        print(f"Model: {model_to_use}")
                        print(f"Active keys: {key_pool.active_count()}/{len(key_pool)}")
                        print(f"Response type: {type(response)}")
                        print(f"Extracted citations: {citations}")
                        print(f"{'='*80}\n")

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

                    # Server errors → try next key/provider
                    if any(code in error_msg for code in ("500", "502", "503")):
                        print(f"🔄 {provider['name']} server error, rotating...")
                        continue

                    # Timeout → try next key/provider
                    if "timeout" in error_msg.lower() or "timed out" in error_msg.lower():
                        print(f"⏱️ {provider['name']} timeout, rotating...")
                        continue

                    # Other errors → try next key
                    print(f"❌ {provider['name']} error: {error_msg[:100]}")
                    continue

        raise Exception(f"All ChatGPT providers failed. Last error: {last_error}")
