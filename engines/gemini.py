import os
import asyncio
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from .base import BaseEngine, EngineResponse, RateLimiter

try:
    from google import genai
except ImportError:
    genai = None


class GeminiEngine(BaseEngine):
    name = "gemini"

    def __init__(self, model: str = "gemini-2.0-flash", rpm: int = 15):
        super().__init__(model, rpm)
        if genai is None:
            raise ImportError("google-genai package is required")

        raw_keys = os.getenv("GOOGLE_API_KEY", "")
        self._api_keys = [k.strip() for k in raw_keys.split(",") if k.strip()]
        if not self._api_keys:
            raise ValueError("GOOGLE_API_KEY is not set")

        self._clients = [genai.Client(api_key=k) for k in self._api_keys]
        self._key_index = 0
        # Re-init rate limiter with num_keys for higher concurrency
        self.rate_limiter = RateLimiter(rpm, len(self._api_keys))

    def _next_client(self):
        """Round-robin client selection across API keys."""
        client = self._clients[self._key_index % len(self._clients)]
        self._key_index += 1
        return client

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=16),
        retry=retry_if_exception_type(Exception),
        reraise=True,
    )
    async def query(self, prompt: str) -> EngineResponse:
        client = self._next_client()
        response = await asyncio.to_thread(
            client.models.generate_content,
            model=self.model,
            contents=prompt,
        )
        text = response.text or ""
        return EngineResponse(
            engine=self.name,
            prompt=prompt,
            response_text=text,
        )
