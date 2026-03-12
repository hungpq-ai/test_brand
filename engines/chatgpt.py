import os
import re
from openai import AsyncOpenAI
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from .base import BaseEngine, EngineResponse, RateLimiter


class ChatGPTEngine(BaseEngine):
    name = "chatgpt"

    def __init__(self, model: str = "gpt-4o", rpm: int = 60):
        super().__init__(model, rpm)

        # Multi-provider fallback support with per-provider model names
        self._providers = []

        # Model name mapping per provider
        yescale_model = os.getenv("YESCALE_GPT_MODEL", "gpt-5.1")
        deepbricks_model = os.getenv("DEEPBRICKS_GPT_MODEL", "gpt-5.1")

        # Provider 1: Yescale (primary - working with gpt-5.1)
        yescale_key = os.getenv("YESCALE_API_KEY")
        yescale_url = os.getenv("YESCALE_BASE_URL", "https://api.yescale.io/v1")
        if yescale_key:
            self._providers.append({
                "name": "Yescale",
                "client": AsyncOpenAI(api_key=yescale_key, base_url=yescale_url, timeout=90.0),
                "model": yescale_model,
                "active": True
            })

        # Provider 2: DeepBricks (fallback - intermittent 500 errors)
        deepbricks_key = os.getenv("DEEPBRICKS_API_KEY")
        deepbricks_url = os.getenv("DEEPBRICKS_BASE_URL", "https://api.deepbricks.ai/v1")
        if deepbricks_key:
            self._providers.append({
                "name": "DeepBricks",
                "client": AsyncOpenAI(api_key=deepbricks_key, base_url=deepbricks_url, timeout=90.0),
                "model": deepbricks_model,
                "active": True
            })

        # Legacy fallback: Generic OpenAI-compatible config
        if not self._providers:
            base_url = os.getenv("CHATGPT_BASE_URL") or os.getenv("OPENAI_BASE_URL")
            raw_keys = os.getenv("CHATGPT_API_KEY") or os.getenv("OPENAI_API_KEY", "")
            api_keys = [k.strip() for k in raw_keys.split(",") if k.strip()]

            if not api_keys:
                raise ValueError("No ChatGPT API keys configured. Set YESCALE_API_KEY, DEEPBRICK_API_KEY, or CHATGPT_API_KEY")

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
        raise ValueError("No active ChatGPT providers available")

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

                # Build messages with optional system prompt for source citation
                messages = []
                system_prompt = os.getenv("CHATGPT_SYSTEM_PROMPT", "")
                if system_prompt:
                    messages.append({"role": "system", "content": system_prompt})
                messages.append({"role": "user", "content": prompt})

                response = await provider["client"].chat.completions.create(
                    model=model_to_use,
                    messages=messages,
                    temperature=0.7,
                    timeout=60.0,
                )
                text = response.choices[0].message.content or ""

                # Extract URLs from response text
                url_pattern = r'https?://[^\s\)\]\},<>"\']+'
                citations = list(set(re.findall(url_pattern, text)))

                # DEBUG: Log raw response structure
                debug_mode = os.getenv("DEBUG_API_RESPONSES", "false").lower() == "true"
                if debug_mode:
                    print(f"\n{'='*80}")
                    print(f"CHATGPT RAW RESPONSE DEBUG ({provider['name']})")
                    print(f"{'='*80}")
                    print(f"Model: {model_to_use}")
                    print(f"Response type: {type(response)}")
                    print(f"Response dict: {response.model_dump() if hasattr(response, 'model_dump') else response}")
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

                # Check for quota/auth errors
                if "401" in error_msg or "quota" in error_msg.lower() or "exhausted" in error_msg.lower():
                    print(f"🔄 {provider['name']} quota exceeded, trying fallback...")
                    self._mark_provider_inactive(provider["name"])
                    continue

                # Check for rate limit errors
                elif "429" in error_msg or "rate_limit" in error_msg.lower():
                    print(f"⏱️ {provider['name']} rate limited, trying fallback...")
                    continue

                # Check for 500 errors (temporary server issues)
                elif "500" in error_msg or "502" in error_msg or "503" in error_msg:
                    print(f"🔄 {provider['name']} server error (500), trying fallback...")
                    continue

                # Timeout errors
                elif "timeout" in error_msg.lower() or "timed out" in error_msg.lower():
                    print(f"⏱️ {provider['name']} timeout, trying fallback...")
                    continue

                # Other errors - try next provider
                else:
                    print(f"❌ {provider['name']} error: {error_msg[:100]}")
                    continue

        # All providers failed
        raise Exception(f"All ChatGPT providers failed. Last error: {last_error}")
