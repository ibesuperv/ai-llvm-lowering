"""Model registry — discovers available LLM models and creates clients.

Checks which API keys are configured in PipelineConfig and instantiates
the corresponding LLM clients. Acts as a factory for the pipeline to
get all available models without knowing provider-specific details.
"""

from __future__ import annotations

import logging
from typing import Optional

from src.config import PipelineConfig
from src.llm.base_client import LLMClient
from src.llm.gemini_client import GeminiClient
from src.llm.groq_client import GroqClient
from src.types import ModelConfig

logger = logging.getLogger(__name__)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Default Model Configurations
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

GEMINI_MODELS: list[ModelConfig] = [
    ModelConfig(
        provider="gemini",
        model_id="gemini-2.0-flash",
        display_name="Gemini 2.0 Flash",
        max_tokens=8192,
        default_temperature=0.2,
        rate_limit_rpm=15,
    ),
]

GROQ_MODELS: list[ModelConfig] = [
    ModelConfig(
        provider="groq",
        model_id="llama-3.3-70b-versatile",
        display_name="Llama 3.3 70B (Groq)",
        max_tokens=4096,
        default_temperature=0.2,
        rate_limit_rpm=30,
    ),
]


class ModelRegistry:
    """Discovers and manages available LLM models.

    Usage:
        registry = ModelRegistry(config)
        clients = registry.get_all_clients()
        for client in clients:
            response = client.generate(prompt)
    """

    def __init__(self, config: PipelineConfig) -> None:
        self._config = config
        self._clients: dict[str, LLMClient] = {}
        self._discover()

    def _discover(self) -> None:
        """Check configured API keys and register available models."""
        if self._config.has_gemini:
            for model_config in GEMINI_MODELS:
                try:
                    client = GeminiClient(
                        config=model_config,
                        api_key=self._config.gemini_api_key,
                        rate_limit_config=self._config.rate_limit,
                    )
                    self._clients[model_config.model_id] = client
                    logger.info("Registered model: %s", model_config.display_name)
                except Exception as e:
                    logger.warning("Failed to register %s: %s", model_config.display_name, e)

        if self._config.has_groq:
            for model_config in GROQ_MODELS:
                try:
                    client = GroqClient(
                        config=model_config,
                        api_key=self._config.groq_api_key,
                        rate_limit_config=self._config.rate_limit,
                    )
                    self._clients[model_config.model_id] = client
                    logger.info("Registered model: %s", model_config.display_name)
                except Exception as e:
                    logger.warning("Failed to register %s: %s", model_config.display_name, e)

        if not self._clients:
            logger.error("No LLM models available. Check your API keys in .env")

    def get_all_clients(self) -> list[LLMClient]:
        """Return instantiated clients for all available models."""
        return list(self._clients.values())

    def get_client(self, model_id: str) -> Optional[LLMClient]:
        """Get a specific client by model ID."""
        return self._clients.get(model_id)

    def get_model_names(self) -> list[str]:
        """Return display names of all available models."""
        return [c.get_model_name() for c in self._clients.values()]

    def get_model_ids(self) -> list[str]:
        """Return model IDs of all available models."""
        return list(self._clients.keys())

    @property
    def model_count(self) -> int:
        return len(self._clients)
