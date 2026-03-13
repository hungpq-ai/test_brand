import os
from openai import AsyncOpenAI
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from .base import BaseEngine, EngineResponse, RateLimiter, KeyPool


class PerplexityEngine(BaseEngine):
    name = "perplexity"

    def __init__(self, model: str = "sonar-pro", rpm: int = 50):
        super().__init__(model, rpm)
        self._key_pool = KeyPool.from_env("PERPLEXITY_API_KEY")
        self._clients = {
            key: AsyncOpenAI(api_key=key, base_url="https://api.perplexity.ai")
            for key in self._key_pool.keys
        }
        self.rate_limiter = RateLimiter(rpm, len(self._key_pool))

    def _next_client(self) -> tuple[str, AsyncOpenAI]:
        """Get next client via key rotation."""
        key = self._key_pool.next_key()
        return key, self._clients[key]

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=16),
        retry=retry_if_exception_type(Exception),
        reraise=True,
    )
    async def query(self, prompt: str) -> EngineResponse:
        last_error = None

        for _ in range(len(self._key_pool)):
            try:
                key, client = self._next_client()
            except ValueError:
                break  # All keys exhausted

            try:
                response = await client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "user", "content": prompt}],
                )
                text = response.choices[0].message.content or ""

                # Extract citations if available (Perplexity returns them in the response)
                citations = []
                if hasattr(response, "citations"):
                    citations = response.citations or []

                # DEBUG: Log raw response structure
                debug_mode = os.getenv("DEBUG_API_RESPONSES", "false").lower() == "true"
                if debug_mode:
                    print(f"\n{'='*80}")
                    print(f"PERPLEXITY RAW RESPONSE DEBUG")
                    print(f"{'='*80}")
                    print(f"Model: {self.model}")
                    print(f"Active keys: {self._key_pool.active_count()}/{len(self._key_pool)}")
                    print(f"Response type: {type(response)}")
                    print(f"Has citations attr: {hasattr(response, 'citations')}")
                    print(f"Response dict: {response.model_dump() if hasattr(response, 'model_dump') else response}")
                    if hasattr(response, 'citations') and response.citations:
                        print(f"Citations found: {response.citations}")
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

                # Quota/auth errors → mark key exhausted, try next
                if "401" in error_msg or "403" in error_msg or "quota" in error_msg.lower() or "exhausted" in error_msg.lower():
                    print(f"🔄 Perplexity key exhausted, rotating... ({self._key_pool.active_count()-1}/{len(self._key_pool)} remaining)")
                    self._key_pool.mark_exhausted(key)
                    continue

                # Rate limit → try next key (might have separate limits)
                if "429" in error_msg or "rate_limit" in error_msg.lower():
                    print(f"⏱️ Perplexity rate limited, rotating key...")
                    continue

                # Other errors → propagate for tenacity retry
                raise

        raise Exception(f"All Perplexity API keys failed. Last error: {last_error}")
