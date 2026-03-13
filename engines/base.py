from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import asyncio
import os
import time
import threading


@dataclass
class EngineResponse:
    engine: str
    prompt: str
    response_text: str
    citations: list[str] = field(default_factory=list)
    error: str | None = None


class KeyPool:
    """Thread-safe pool of API keys with round-robin rotation and failover."""

    def __init__(self, keys: list[str], cooldown: float = 300.0):
        self.keys = keys
        self.cooldown = cooldown  # seconds before reactivating exhausted key
        self._index = 0
        self._lock = threading.Lock()
        # Track exhausted keys: key -> timestamp when exhausted
        self._exhausted: dict[str, float] = {}

    @classmethod
    def from_env(cls, var: str, cooldown: float = 300.0) -> "KeyPool":
        """Create KeyPool from comma-separated env var. Raises if no keys found."""
        raw = os.getenv(var, "")
        keys = [k.strip() for k in raw.split(",") if k.strip()]
        if not keys:
            raise ValueError(f"{var} is not set or empty")
        return cls(keys, cooldown)

    @classmethod
    def from_env_optional(cls, var: str, cooldown: float = 300.0) -> "KeyPool | None":
        """Create KeyPool from env var. Returns None if var is not set."""
        raw = os.getenv(var, "")
        keys = [k.strip() for k in raw.split(",") if k.strip()]
        if not keys:
            return None
        return cls(keys, cooldown)

    def _reactivate_expired(self):
        """Reactivate keys whose cooldown has expired."""
        now = time.time()
        expired = [k for k, t in self._exhausted.items() if now - t >= self.cooldown]
        for k in expired:
            del self._exhausted[k]

    def next_key(self) -> str:
        """Get next active key via round-robin. Raises if all keys exhausted."""
        with self._lock:
            self._reactivate_expired()
            for _ in range(len(self.keys)):
                key = self.keys[self._index % len(self.keys)]
                self._index += 1
                if key not in self._exhausted:
                    return key
            raise ValueError("All API keys are exhausted")

    def mark_exhausted(self, key: str):
        """Mark a key as exhausted (quota/auth error). Auto-reactivates after cooldown."""
        with self._lock:
            self._exhausted[key] = time.time()

    def active_count(self) -> int:
        """Number of currently active (non-exhausted) keys."""
        with self._lock:
            self._reactivate_expired()
            return len(self.keys) - len(self._exhausted)

    def __len__(self) -> int:
        return len(self.keys)


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
