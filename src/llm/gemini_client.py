"""Google Gemini API client for LLVM IR generation.

Uses the google-genai SDK (replaces deprecated google-generativeai).
Free tier limits: 15 RPM, 1M tokens/day for gemini-2.0-flash.

The client handles:
- Rate limiting via sliding-window RateLimiter
- Automatic retry with exponential backoff on 429 errors
- Response extraction (IR code from LLM text)
- Error handling with structured LLMResponse
"""

from __future__ import annotations

import logging
import time
from typing import Optional

from src.config import RateLimitConfig
from src.llm.base_client import LLMClient, LLMResponse, RateLimiter, extract_ir_from_response
from src.types import ModelConfig

logger = logging.getLogger(__name__)


class GeminiClient(LLMClient):
    """Client for Google Gemini API (free tier).

    Uses the new google-genai SDK (google.genai).
    Supported models: gemini-2.0-flash, gemini-2.0-flash-lite, gemini-1.5-flash
    """

    def __init__(
        self,
        config: ModelConfig,
        api_key: str,
        rate_limit_config: Optional[RateLimitConfig] = None,
    ) -> None:
        self._config = config
        self._api_key = api_key
        self._rate_limit_config = rate_limit_config or RateLimitConfig()
        self._rate_limiter = RateLimiter(
            rpm=config.rate_limit_rpm,
            config=self._rate_limit_config,
        )
        self._client = None
        self._initialized = False

    def _ensure_initialized(self) -> None:
        """Lazy-initialize the Gemini SDK on first use.

        Tries the new google-genai package first, falls back to the
        legacy google-generativeai if not installed.
        """
        if self._initialized:
            return

        try:
            # New SDK: google-genai (pip install google-genai)
            from google import genai
            self._client = genai.Client(api_key=self._api_key)
            self._sdk = "new"
            self._initialized = True
            logger.debug("Gemini client initialized (google-genai): %s", self._config.model_id)
            return
        except ImportError:
            pass

        try:
            # Legacy SDK fallback: google-generativeai
            import warnings
            import google.generativeai as genai_legacy
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", FutureWarning)
                genai_legacy.configure(api_key=self._api_key)
                self._client = genai_legacy.GenerativeModel(self._config.model_id)
            self._sdk = "legacy"
            self._initialized = True
            logger.debug("Gemini client initialized (google-generativeai legacy): %s", self._config.model_id)
            return
        except ImportError:
            pass

        raise RuntimeError(
            "Neither 'google-genai' nor 'google-generativeai' is installed.\n"
            "Run: pip install google-genai"
        )

    def _call_new_sdk(self, prompt: str, temperature: float) -> tuple[str, int, int]:
        """Call using new google-genai SDK. Returns (content, prompt_tokens, completion_tokens)."""
        from google.genai import types as genai_types
        response = self._client.models.generate_content(
            model=self._config.model_id,
            contents=prompt,
            config=genai_types.GenerateContentConfig(
                temperature=temperature,
                max_output_tokens=self._config.max_tokens,
            ),
        )
        content = response.text or ""
        prompt_tokens = 0
        completion_tokens = 0
        if response.usage_metadata:
            prompt_tokens = getattr(response.usage_metadata, "prompt_token_count", 0) or 0
            completion_tokens = getattr(response.usage_metadata, "candidates_token_count", 0) or 0
        return content, prompt_tokens, completion_tokens

    def _call_legacy_sdk(self, prompt: str, temperature: float) -> tuple[str, int, int]:
        """Call using legacy google-generativeai SDK. Returns (content, prompt_tokens, completion_tokens)."""
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", FutureWarning)
            response = self._client.generate_content(
                prompt,
                generation_config={
                    "temperature": temperature,
                    "max_output_tokens": self._config.max_tokens,
                },
            )
        content = response.text or ""
        prompt_tokens = 0
        completion_tokens = 0
        if hasattr(response, "usage_metadata") and response.usage_metadata:
            prompt_tokens = getattr(response.usage_metadata, "prompt_token_count", 0) or 0
            completion_tokens = getattr(response.usage_metadata, "candidates_token_count", 0) or 0
        return content, prompt_tokens, completion_tokens

    def generate(self, prompt: str, temperature: float = 0.2) -> LLMResponse:
        """Generate LLVM IR using Gemini.

        Handles rate limiting and retries automatically.

        Args:
            prompt: Complete prompt for IR generation.
            temperature: Sampling temperature.

        Returns:
            LLMResponse with extracted IR code and metadata.
        """
        self._ensure_initialized()

        for attempt in range(self._rate_limit_config.max_retries + 1):
            try:
                self._rate_limiter.acquire()
                start_time = time.time()

                if self._sdk == "new":
                    content, prompt_tokens, completion_tokens = self._call_new_sdk(prompt, temperature)
                else:
                    content, prompt_tokens, completion_tokens = self._call_legacy_sdk(prompt, temperature)

                duration_ms = (time.time() - start_time) * 1000

                if not content:
                    return LLMResponse(
                        model=self._config.model_id,
                        temperature=temperature,
                        duration_ms=duration_ms,
                        error="Empty response from Gemini",
                    )

                ir_code = extract_ir_from_response(content)

                return LLMResponse(
                    content=content,
                    ir_code=ir_code,
                    model=self._config.model_id,
                    temperature=temperature,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    duration_ms=duration_ms,
                )

            except Exception as e:
                error_str = str(e).lower()

                # Check if it's a rate limit / quota error (429)
                is_rate_limit = (
                    "429" in error_str
                    or "resource_exhausted" in error_str
                    or "resource exhausted" in error_str
                    or "quota" in error_str
                    or "rate" in error_str
                )

                if is_rate_limit:
                    if attempt < self._rate_limit_config.max_retries:
                        self._rate_limiter.backoff(attempt)
                        continue
                    else:
                        logger.error(
                            "Gemini rate limit exceeded after %d retries",
                            self._rate_limit_config.max_retries,
                        )
                        return LLMResponse(
                            model=self._config.model_id,
                            temperature=temperature,
                            error=f"Rate limit exceeded after {self._rate_limit_config.max_retries} retries: {e}",
                        )

                # Non-rate-limit error — don't retry
                logger.error("Gemini API error: %s", e)
                return LLMResponse(
                    model=self._config.model_id,
                    temperature=temperature,
                    error=f"Gemini API error: {e}",
                )

        return LLMResponse(
            model=self._config.model_id,
            temperature=temperature,
            error="Exhausted all retry attempts",
        )

    def get_model_name(self) -> str:
        return self._config.display_name

    def get_model_id(self) -> str:
        return self._config.model_id
