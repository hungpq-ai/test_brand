import os
import re
import asyncio
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from .base import BaseEngine, EngineResponse, RateLimiter, KeyPool

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

        self._key_pool = KeyPool.from_env("GOOGLE_API_KEY")
        self._clients = {
            key: genai.Client(api_key=key)
            for key in self._key_pool.keys
        }
        self.rate_limiter = RateLimiter(rpm, len(self._key_pool))

    def _next_client(self) -> tuple[str, object]:
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
                # Get system prompt if configured
                system_prompt = os.getenv("GEMINI_SYSTEM_PROMPT", "")
                full_prompt = prompt
                if system_prompt:
                    full_prompt = f"{system_prompt}\n\nUser query: {prompt}"

                # Enable Google Search grounding if configured
                enable_grounding = os.getenv("GEMINI_ENABLE_GROUNDING", "true").lower() == "true"

                config = {}
                if enable_grounding:
                    from google.genai import types
                    config = types.GenerateContentConfig(
                        tools=[types.Tool(google_search=types.GoogleSearch())],
                    )

                response = await asyncio.to_thread(
                    client.models.generate_content,
                    model=self.model,
                    contents=full_prompt,
                    config=config if enable_grounding else None,
                )
                text = response.text or ""
                citations = []

                # PRIMARY: Extract from grounding_metadata
                if hasattr(response, 'candidates') and response.candidates:
                    candidate = response.candidates[0]
                    if hasattr(candidate, 'grounding_metadata') and candidate.grounding_metadata:
                        grounding = candidate.grounding_metadata
                        if hasattr(grounding, 'grounding_chunks') and grounding.grounding_chunks:
                            for chunk in grounding.grounding_chunks:
                                if hasattr(chunk, 'web') and chunk.web:
                                    title = getattr(chunk.web, 'title', None)
                                    uri = getattr(chunk.web, 'uri', None)
                                    if title and '.' in title and not title.startswith('http'):
                                        full_url = f"https://{title}" if not title.startswith('http') else title
                                        if full_url not in citations:
                                            citations.append(full_url)
                                    elif uri and uri not in citations:
                                        citations.append(uri)

                # FALLBACK: Extract URLs from text
                if not citations:
                    url_pattern = r'https?://[^\s\)\]\},<>"\']+'
                    citations = list(set(re.findall(url_pattern, text)))

                # DEBUG
                debug_mode = os.getenv("DEBUG_API_RESPONSES", "false").lower() == "true"
                if debug_mode:
                    print(f"\n{'='*80}")
                    print(f"GEMINI RAW RESPONSE DEBUG")
                    print(f"{'='*80}")
                    print(f"Model: {self.model}")
                    print(f"Active keys: {self._key_pool.active_count()}/{len(self._key_pool)}")
                    print(f"Grounding enabled: {enable_grounding}")
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
                if "401" in error_msg or "403" in error_msg or "quota" in error_msg.lower() or "exhausted" in error_msg.lower() or "RESOURCE_EXHAUSTED" in error_msg:
                    print(f"🔄 Gemini key exhausted, rotating... ({self._key_pool.active_count()-1}/{len(self._key_pool)} remaining)")
                    self._key_pool.mark_exhausted(key)
                    continue

                # Rate limit → try next key
                if "429" in error_msg or "rate_limit" in error_msg.lower():
                    print(f"⏱️ Gemini rate limited, rotating key...")
                    continue

                # Other errors → propagate for tenacity retry
                raise

        raise Exception(f"All Gemini API keys failed. Last error: {last_error}")
