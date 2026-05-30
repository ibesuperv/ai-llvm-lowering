"""Groq API client for LLVM IR generation.

Uses the Groq Python SDK to call open-source models (Llama, Gemma, etc.)
hosted on Groq's ultra-fast inference infrastructure.
Free tier: 30 RPM, ~14K tokens/min (varies by model).

Provides an alternative model for multi-model comparison in evaluation.
"""

from __future__ import annotations

import logging
import time
from typing import Optional

from src.config import RateLimitConfig
from src.llm.base_client import LLMClient, LLMResponse, RateLimiter, extract_ir_from_response
from src.types import ModelConfig

logger = logging.getLogger(__name__)


class GroqClient(LLMClient):
    """Client for Groq API (free tier).

    Supported models: llama-3.3-70b-versatile, gemma2-9b-it, etc.
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
        """Lazy-initialize the Groq SDK on first use."""
        if self._initialized:
            return
        try:
            from groq import Groq
            self._client = Groq(api_key=self._api_key)
            self._initialized = True
            logger.debug("Groq client initialized: %s", self._config.model_id)
        except ImportError:
            raise RuntimeError(
                "groq package not installed. Run: pip install groq"
            )
        except Exception as e:
            raise RuntimeError(f"Failed to initialize Groq client: {e}")

    def generate(self, prompt: str, temperature: float = 0.2) -> LLMResponse:
        """Generate LLVM IR using a Groq-hosted model.

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

                completion = self._client.chat.completions.create(
                    model=self._config.model_id,
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "You are an expert LLVM IR compiler backend. "
                                "Generate valid LLVM IR code that assembles with llvm-as "
                                "and executes correctly with lli. Use LLVM 18 syntax "
                                "with opaque pointers (ptr, not i32*)."
                            ),
                        },
                        {"role": "user", "content": prompt},
                    ],
                    temperature=temperature,
                    max_tokens=self._config.max_tokens,
                )

                duration_ms = (time.time() - start_time) * 1000

                content = completion.choices[0].message.content or ""
                ir_code = extract_ir_from_response(content)

                prompt_tokens = getattr(completion.usage, "prompt_tokens", 0) if completion.usage else 0
                completion_tokens = getattr(completion.usage, "completion_tokens", 0) if completion.usage else 0

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
                if "rate_limit" in error_str or "429" in error_str or "too many" in error_str:
                    if attempt < self._rate_limit_config.max_retries:
                        self._rate_limiter.backoff(attempt)
                        continue
                    return LLMResponse(
                        model=self._config.model_id,
                        temperature=temperature,
                        error=f"Rate limit exceeded after {self._rate_limit_config.max_retries} retries: {e}",
                    )

                logger.error("Groq API error: %s", e)
                return LLMResponse(
                    model=self._config.model_id,
                    temperature=temperature,
                    error=f"Groq API error: {e}",
                )

        return LLMResponse(
            model=self._config.model_id, temperature=temperature,
            error="Exhausted all retry attempts",
        )

    def get_model_name(self) -> str:
        return self._config.display_name

    def get_model_id(self) -> str:
        return self._config.model_id
