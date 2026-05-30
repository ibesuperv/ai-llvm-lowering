"""Batch evaluation and reporting.

This module provides the Evaluator class, which runs the test suite
across all available models, saves the results, and generates a
detailed Markdown report.
"""

from __future__ import annotations

import json
import logging
import os
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from src.config import PipelineConfig
from src.llm.model_registry import ModelRegistry
from src.parser import Lexer, Parser
from src.repair.orchestrator import RepairOrchestrator
from src.types import ErrorCategory, LanguageTier, TaskResult

logger = logging.getLogger(__name__)


class Evaluator:
    """Runs evaluations across multiple models and generates reports."""

    def __init__(
        self,
        config: PipelineConfig,
        registry: ModelRegistry,
        orchestrator: RepairOrchestrator,
    ) -> None:
        self._config = config
        self._registry = registry
        self._orchestrator = orchestrator

    def run_evaluation(self, test_dir: Path) -> list[TaskResult]:
        """Run the pipeline on all .mini files in the given directory.

        Args:
            test_dir: Directory containing test programs.

        Returns:
            List of TaskResults for all models and all files.
        """
        results: list[TaskResult] = []

        if not test_dir.exists() or not test_dir.is_dir():
            logger.error("Test directory not found: %s", test_dir)
            return results

        test_files = list(test_dir.rglob("*.mini"))
        if not test_files:
            logger.warning("No .mini files found in %s", test_dir)
            return results

        logger.info("Found %d test files. Starting evaluation.", len(test_files))

        clients = self._registry.get_all_clients()
        total_tasks = len(test_files) * len(clients)
        completed = 0

        for file_path in sorted(test_files):
            logger.info("Processing: %s", file_path.name)

            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    source_code = f.read()

                # Load expected output if a .expected file exists alongside the .mini
                expected_output: Optional[str] = None
                expected_path = file_path.with_suffix(".expected")
                if expected_path.exists():
                    expected_output = expected_path.read_text(encoding="utf-8")
                    logger.info("  Expected output loaded from %s", expected_path.name)

                # Parse once per file
                tokens = Lexer(source_code, filename=file_path.name).tokenize()
                ast = Parser(tokens).parse()

                # Run for each model
                for client in clients:
                    completed += 1
                    logger.info(
                        "[%d/%d] Model: %s, File: %s",
                        completed, total_tasks, client.get_model_name(), file_path.name
                    )

                    result = self._orchestrator.run_task(
                        client=client,
                        source_code=source_code,
                        ast=ast,
                        expected_output=expected_output,
                    )

                    # Tag result with filename
                    result.source_code = f"// File: {file_path.name}\n{result.source_code}"
                    results.append(result)

            except Exception as e:
                logger.error("Failed to process %s: %s", file_path.name, e)

        # Save generated IR files
        self._save_ir(results)

        # Generate markdown report
        self._generate_report(results)

        return results

    def _save_ir(self, results: list[TaskResult]) -> None:
        """Save the generated LLVM IR for successful tasks."""
        out_dir = Path(self._config.output_dir) / "generated_ir"
        out_dir.mkdir(parents=True, exist_ok=True)

        for result in results:
            if not result.success:
                continue

            # Extract filename from the prepended comment
            filename = "unknown"
            if result.source_code.startswith("// File: "):
                filename = result.source_code.split("\n")[0].replace("// File: ", "").strip()
            
            base_name = Path(filename).stem
            safe_model_id = result.model_id.replace("/", "_").replace("-", "_")
            
            out_path = out_dir / f"{base_name}_{safe_model_id}.ll"
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(result.final_ir)

    def _generate_report(self, results: list[TaskResult]) -> None:
        """Generate a detailed Markdown report of the evaluation."""
        if not results:
            return

        report_dir = Path(self._config.output_dir) / "reports"
        report_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_path = report_dir / f"eval_report_{timestamp}.md"

        # ── Compute Statistics ───────────────────────────────────────
        models = list(set(r.model_id for r in results))
        total_tests = len(results) // len(models) if models else 0

        # Model comparison: {model_id: {"success": int, "retries": int}}
        model_stats: dict[str, dict[str, int]] = {
            m: {"success": 0, "retries_needed": 0, "total_attempts": 0} 
            for m in models
        }
        
        # Error categorization across all failures
        error_counts: dict[ErrorCategory, int] = defaultdict(int)

        for r in results:
            m = r.model_id
            if r.success:
                model_stats[m]["success"] += 1
                
            attempts = len(r.repair_attempts)
            model_stats[m]["total_attempts"] += attempts
            if r.success and attempts > 1:
                model_stats[m]["retries_needed"] += 1

            # Count errors from all failed attempts
            for attempt in r.repair_attempts:
                if not attempt.validation.is_valid:
                    for error in attempt.validation.errors:
                        error_counts[error.category] += 1

        # ── Write Markdown ───────────────────────────────────────────
        with open(report_path, "w", encoding="utf-8") as f:
            f.write("# AI-Assisted LLVM Lowering Evaluation Report\n\n")
            f.write(f"**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"**Total Test Files:** {total_tests}\n\n")

            f.write("## Model Performance\n\n")
            f.write("| Model | Success Rate | Pass@1 | Repaired | Avg Attempts |\n")
            f.write("|-------|--------------|--------|----------|--------------|\n")

            for model_id in sorted(models):
                stats = model_stats[model_id]
                success = stats["success"]
                pass_at_1 = success - stats["retries_needed"]
                repaired = stats["retries_needed"]
                avg_attempts = stats["total_attempts"] / max(1, total_tests)
                
                success_rate = (success / max(1, total_tests)) * 100
                pass_at_1_rate = (pass_at_1 / max(1, total_tests)) * 100

                f.write(
                    f"| `{model_id}` | {success_rate:.1f}% ({success}/{total_tests}) | "
                    f"{pass_at_1_rate:.1f}% | {repaired} | {avg_attempts:.1f} |\n"
                )

            f.write("\n## Error Categorization (All Attempts)\n\n")
            if error_counts:
                f.write("| Error Category | Occurrences |\n")
                f.write("|----------------|-------------|\n")
                for cat, count in sorted(error_counts.items(), key=lambda x: x[1], reverse=True):
                    f.write(f"| {cat.name} | {count} |\n")
            else:
                f.write("No errors encountered!\n")

        logger.info("Evaluation report saved to: %s", report_path)
