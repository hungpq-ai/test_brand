import os
from openai import AsyncOpenAI
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from .base import BaseEngine, EngineResponse


class PerplexityEngine(BaseEngine):
    name = "perplexity"

    def __init__(self, model: str = "sonar-pro", rpm: int = 50):
        super().__init__(model, rpm)
        self.client = AsyncOpenAI(
            api_key=os.getenv("PERPLEXITY_API_KEY"),
            base_url="https://api.perplexity.ai",
        )

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=16),
        retry=retry_if_exception_type(Exception),
        reraise=True,
    )
    async def query(self, prompt: str) -> EngineResponse:
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.choices[0].message.content or ""

        # Extract citations if available (Perplexity returns them in the response)
        citations = []
        if hasattr(response, "citations"):
            citations = response.citations or []

        return EngineResponse(
            engine=self.name,
            prompt=prompt,
            response_text=text,
            citations=citations,
        )
