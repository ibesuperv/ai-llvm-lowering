"""Centralized configuration and environment management for the AI-LLVM Lowering pipeline."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

from src.types import ModelConfig


# Find and load the .env file in parent directories
def load_env() -> None:
    current_dir = Path(__file__).resolve().parent
    for parent in [current_dir, current_dir.parent, current_dir.parent.parent]:
        env_path = parent / ".env"
        if env_path.exists():
            load_dotenv(env_path)
            return


load_env()


@dataclass
class RateLimitConfig:
    """Rate limiting configuration for LLM API calls."""

    rpm: int = 15
    burst: int = 5
    max_retries: int = 3

    def get_backoff_delay(self, attempt: int) -> float:
        """Return exponential backoff delay in seconds, capped at 60s."""
        return min(60.0, float(2 ** attempt * 2))


@dataclass
class PipelineConfig:
    """Main pipeline configuration loaded from environment variables."""

    gemini_api_key: str = field(default_factory=lambda: os.getenv("GEMINI_API_KEY", ""))
    groq_api_key: str = field(default_factory=lambda: os.getenv("GROQ_API_KEY", ""))
    llvm_as_path: str = field(default_factory=lambda: os.getenv("LLVM_AS_PATH", "/usr/bin/llvm-as"))
    lli_path: str = field(default_factory=lambda: os.getenv("LLI_PATH", "/usr/bin/lli"))
    output_dir: str = "results"
    cache_dir: str = "results/cache"
    no_cache: bool = False
    max_repair_attempts: int = 3
    max_retries: int = 3

    # Available Models configurations
    models: dict[str, ModelConfig] = field(default_factory=lambda: {
        "gemini-2.0-flash": ModelConfig("gemini", "gemini-2.0-flash", "Gemini 2.0 Flash", 4096, 0.2, 15),
        "gemini-1.5-flash": ModelConfig("gemini", "gemini-1.5-flash", "Gemini 1.5 Flash", 4096, 0.2, 15),
        "llama-3.1-70b-versatile": ModelConfig("groq", "llama-3.1-70b-versatile", "Llama 3.1 70B", 4096, 0.2, 30),
    })

    @property
    def has_gemini(self) -> bool:
        """True if a Gemini API key is configured."""
        return bool(self.gemini_api_key)

    @property
    def has_groq(self) -> bool:
        """True if a Groq API key is configured."""
        return bool(self.groq_api_key)

    @property
    def rate_limit(self) -> RateLimitConfig:
        """Return a default RateLimitConfig instance."""
        return RateLimitConfig()


def load_config() -> PipelineConfig:
    """Load and return the pipeline configuration from environment."""
    return PipelineConfig()


class ResponseCache:
    """File-based caching layer for LLM responses to prevent quota burn."""

    def __init__(self, config: PipelineConfig) -> None:
        self.cache_dir = Path(config.cache_dir)
        self.no_cache = config.no_cache
        if not self.no_cache:
            self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _get_key(self, source_code: str, model: str, strategy: str) -> str:
        data = f"{source_code}:{model}:{strategy}".encode("utf-8")
        return hashlib.sha256(data).hexdigest()

    def get(self, source_code: str, model: str, strategy: str) -> Optional[dict]:
        if self.no_cache:
            return None
        key = self._get_key(source_code, model, strategy)
        cache_file = self.cache_dir / f"{key}.json"
        if cache_file.exists():
            try:
                return json.loads(cache_file.read_text(encoding="utf-8"))
            except Exception:
                return None
        return None

    def put(self, source_code: str, model: str, strategy: str, response: dict) -> None:
        if self.no_cache:
            return
        key = self._get_key(source_code, model, strategy)
        cache_file = self.cache_dir / f"{key}.json"
        try:
            cache_file.write_text(json.dumps(response, indent=2), encoding="utf-8")
        except Exception:
            pass
