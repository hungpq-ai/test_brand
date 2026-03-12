import os
import re
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

        # Get system prompt if configured
        system_prompt = os.getenv("GEMINI_SYSTEM_PROMPT", "")

        # Combine system prompt with user prompt if system prompt exists
        full_prompt = prompt
        if system_prompt:
            full_prompt = f"{system_prompt}\n\nUser query: {prompt}"

        # Enable Google Search grounding if configured
        enable_grounding = os.getenv("GEMINI_ENABLE_GROUNDING", "true").lower() == "true"

        # Configure tools with google_search if grounding enabled
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

        # PRIMARY: Extract from grounding_metadata (like Gemini Web UI)
        if hasattr(response, 'candidates') and response.candidates:
            candidate = response.candidates[0]
            if hasattr(candidate, 'grounding_metadata') and candidate.grounding_metadata:
                grounding = candidate.grounding_metadata

                # Extract URLs from grounding_chunks (verified sources only)
                if hasattr(grounding, 'grounding_chunks') and grounding.grounding_chunks:
                    for chunk in grounding.grounding_chunks:
                        # Check if chunk has web data
                        if hasattr(chunk, 'web') and chunk.web:
                            # The 'title' field contains the actual domain (e.g., 'hrc.com.vn')
                            # The 'uri' field contains a redirect URL through vertexaisearch
                            title = getattr(chunk.web, 'title', None)
                            uri = getattr(chunk.web, 'uri', None)

                            # If title looks like a domain, construct the URL
                            if title and '.' in title and not title.startswith('http'):
                                # Construct full URL from domain
                                full_url = f"https://{title}" if not title.startswith('http') else title
                                if full_url not in citations:
                                    citations.append(full_url)
                            elif uri and uri not in citations:
                                # Fallback to redirect URI if title is not a domain
                                citations.append(uri)

        # FALLBACK: If no grounding metadata, extract URLs from text (legacy behavior)
        if not citations:
            url_pattern = r'https?://[^\s\)\]\},<>"\']+'
            citations = list(set(re.findall(url_pattern, text)))

        # DEBUG: Log raw response structure
        import json
        debug_mode = os.getenv("DEBUG_API_RESPONSES", "false").lower() == "true"
        if debug_mode:
            print(f"\n{'='*80}")
            print(f"GEMINI RAW RESPONSE DEBUG")
            print(f"{'='*80}")
            print(f"Model: {self.model}")
            print(f"Grounding enabled: {enable_grounding}")
            print(f"Response type: {type(response)}")
            if hasattr(response, 'candidates') and response.candidates:
                candidate = response.candidates[0]
                if hasattr(candidate, 'grounding_metadata'):
                    print(f"Has grounding_metadata: True")
                    print(f"Grounding metadata: {candidate.grounding_metadata}")
                else:
                    print(f"Has grounding_metadata: False")
            print(f"Extracted citations: {citations}")
            print(f"{'='*80}\n")

        return EngineResponse(
            engine=self.name,
            prompt=prompt,
            response_text=text,
            citations=citations,
        )
