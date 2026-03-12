import os
from openai import AsyncOpenAI
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from .base import BaseEngine, EngineResponse


class PerplexityEngine(BaseEngine):
    name = "perplexity"

    def __init__(self, model: str = "sonar-pro", rpm: int = 50):
        super().__init__(model, rpm)
        api_key = os.getenv("PERPLEXITY_API_KEY")
        if not api_key:
            raise ValueError("PERPLEXITY_API_KEY environment variable is not set")
        self.client = AsyncOpenAI(
            api_key=api_key,
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

        # DEBUG: Log raw response structure
        debug_mode = os.getenv("DEBUG_API_RESPONSES", "false").lower() == "true"
        if debug_mode:
            print(f"\n{'='*80}")
            print(f"PERPLEXITY RAW RESPONSE DEBUG")
            print(f"{'='*80}")
            print(f"Model: {self.model}")
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
