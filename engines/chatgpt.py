import os
from openai import AsyncOpenAI
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from .base import BaseEngine, EngineResponse, RateLimiter


class ChatGPTEngine(BaseEngine):
    name = "chatgpt"

    def __init__(self, model: str = "gpt-4o", rpm: int = 60):
        super().__init__(model, rpm)
        base_url = os.getenv("OPENAI_BASE_URL")
        raw_keys = os.getenv("OPENAI_API_KEY", "")
        self._api_keys = [k.strip() for k in raw_keys.split(",") if k.strip()]
        if not self._api_keys:
            raise ValueError("OPENAI_API_KEY is not set")

        self._clients = [
            AsyncOpenAI(api_key=k, base_url=base_url)
            for k in self._api_keys
        ]
        self._key_index = 0
        self.rate_limiter = RateLimiter(rpm, len(self._api_keys))

    def _next_client(self):
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
        response = await client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
        )
        text = response.choices[0].message.content or ""
        return EngineResponse(
            engine=self.name,
            prompt=prompt,
            response_text=text,
        )
