from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import asyncio


@dataclass
class EngineResponse:
    engine: str
    prompt: str
    response_text: str
    citations: list[str] = field(default_factory=list)
    error: str | None = None


class RateLimiter:
    def __init__(self, rpm: int, num_keys: int = 1):
        effective_rpm = rpm * num_keys
        self.semaphore = asyncio.Semaphore(min(effective_rpm, 10 * num_keys))
        self.delay = 60.0 / effective_rpm

    async def __aenter__(self):
        await self.semaphore.acquire()
        await asyncio.sleep(self.delay)
        return self

    async def __aexit__(self, *args):
        self.semaphore.release()


class BaseEngine(ABC):
    name: str
    model: str

    def __init__(self, model: str, rpm: int = 60, num_keys: int = 1):
        self.model = model
        self.rate_limiter = RateLimiter(rpm, num_keys)

    @abstractmethod
    async def query(self, prompt: str) -> EngineResponse:
        ...

    async def safe_query(self, prompt: str) -> EngineResponse:
        """Query with rate limiting."""
        async with self.rate_limiter:
            try:
                return await self.query(prompt)
            except Exception as e:
                return EngineResponse(
                    engine=self.name,
                    prompt=prompt,
                    response_text="",
                    error=str(e),
                )
