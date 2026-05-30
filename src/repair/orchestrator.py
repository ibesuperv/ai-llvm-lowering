"""Repair loop orchestration.

This module orchestrates the core "Generate → Validate → Repair" cycle.
It leverages the PromptEngine to build dynamic prompts and the IRValidator
to verify the generated LLVM IR.

If validation fails, it attempts to repair the IR up to a maximum number
of retries, dynamically adjusting the repair strategy:
- Attempt 1: Simple repair (just showing the error)
- Attempt 2: Targeted repair (providing specific instructions based on error category)
- Attempt 3: Regeneration (starting from scratch with CoT)

It also implements dynamic temperature scaling: as retries increase, the
LLM is given slightly higher temperature to encourage exploring different
solutions if the deterministic path failed.
"""

from __future__ import annotations

import logging
from typing import Optional

from src.config import PipelineConfig
from src.llm.base_client import LLMClient
from src.llm.prompt_engine import PromptEngine
from src.parser.ast_nodes import Program
from src.types import RepairAttempt, TaskResult, ValidationResult
from src.validator.validator import IRValidator

logger = logging.getLogger(__name__)


class RepairOrchestrator:
    """Orchestrates the LLM generation and repair loop."""

    def __init__(
        self,
        config: PipelineConfig,
        validator: IRValidator,
        prompt_engine: PromptEngine,
    ) -> None:
        """Initialize the orchestrator.

        Args:
            config: Pipeline configuration (limits, retries, etc.).
            validator: Configured IRValidator instance.
            prompt_engine: Configured PromptEngine instance.
        """
        self._config = config
        self._validator = validator
        self._prompt_engine = prompt_engine

    def run_task(
        self,
        client: LLMClient,
        source_code: str,
        ast: Program,
        expected_output: Optional[str] = None,
    ) -> TaskResult:
        """Run the complete generation and repair loop for a single task.

        Args:
            client: The LLMClient to use for generation.
            source_code: The original MiniLang source code.
            ast: The parsed Abstract Syntax Tree.
            expected_output: Optional expected stdout for correctness checking.

        Returns:
            TaskResult containing the final IR, success status, and all repair history.
        """
        # 1. Analyze AST and determine optimal prompt strategy
        construct_type = self._prompt_engine.analyze_constructs(ast)
        prompt_strategy = self._prompt_engine.select_strategy(construct_type)

        # 2. Build initial prompt
        prompt = self._prompt_engine.build_generation_prompt(
            source_code=source_code,
            ast=ast,
            strategy=prompt_strategy,
            construct_type=construct_type,
        )

        logger.info(
            "Starting task with %s (Strategy: %s, Construct: %s)",
            client.get_model_name(),
            prompt_strategy.name,
            construct_type.name,
        )

        repair_history: list[RepairAttempt] = []
        current_ir = ""
        current_errors = []

        # ── The Generation / Repair Loop ──────────────────────────────
        max_attempts = self._config.max_retries + 1

        for attempt in range(max_attempts):
            is_repair = attempt > 0

            # Dynamic temperature scaling
            # e.g., attempt 0: 0.2, attempt 1: 0.4, attempt 2: 0.6
            base_temp = 0.2
            temp = min(1.0, base_temp + (attempt * 0.2))

            if is_repair:
                logger.info("Attempt %d/%d (Repair)", attempt, self._config.max_retries)
                strategy_name = self._get_repair_strategy(attempt)
                prompt = self._prompt_engine.build_repair_prompt(
                    source_code=source_code,
                    failed_ir=current_ir,
                    errors=current_errors,
                    attempt=attempt,
                    strategy=strategy_name,
                )
            else:
                logger.info("Attempt 0 (Initial Generation)")

            # Call LLM
            response = client.generate(prompt=prompt, temperature=temp)

            if not response.success:
                # API failure (rate limit, connection error, etc.)
                logger.error("LLM API failed: %s", response.error)
                repair_history.append(
                    RepairAttempt(
                        attempt_number=attempt,
                        prompt=prompt,
                        response=response,
                        validation=ValidationResult(
                            is_valid=False,
                            errors=[],
                        ),
                    )
                )
                # If API fails hard, abort the loop
                break

            current_ir = response.ir_code

            # Validate the generated IR
            # Pass expected_output to enable stdout correctness checking via lli.
            validation = self._validator.validate_ir(
                ir_code=current_ir,
                check_execution=True,
                expected_output=expected_output,
            )

            current_errors = validation.errors

            # Record attempt
            repair_history.append(
                RepairAttempt(
                    attempt_number=attempt,
                    prompt=prompt,
                    response=response,
                    validation=validation,
                )
            )

            if validation.is_valid:
                logger.info("✅ Validation passed on attempt %d!", attempt)
                break
            else:
                logger.warning(
                    "❌ Validation failed on attempt %d (%d errors)",
                    attempt, len(current_errors)
                )

        # ── Finalize Result ───────────────────────────────────────────
        final_attempt = repair_history[-1] if repair_history else None

        return TaskResult(
            source_code=source_code,
            tier=ast.tier,
            prompt_strategy=prompt_strategy,
            model_id=client.get_model_id(),
            success=final_attempt.validation.is_valid if final_attempt else False,
            final_ir=current_ir,
            repair_attempts=repair_history,
        )

    def _get_repair_strategy(self, attempt: int) -> str:
        """Determine the repair strategy based on the attempt number.

        attempt 1: simple (just show errors)
        attempt 2: targeted (provide specific fix instructions)
        attempt 3+: regenerate (start from scratch)
        """
        if attempt == 1:
            return "simple"
        elif attempt == 2:
            return "targeted"
        else:
            return "regenerate"
