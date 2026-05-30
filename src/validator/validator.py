"""LLVM IR validation and error classification.

This module provides the validation pipeline that checks LLM-generated IR
for correctness using the official LLVM toolchain.

Pipeline steps:
1. Save generated IR to a temporary file (.ll).
2. Run `llvm-as` to check syntax, types, and SSA form.
3. If valid, run `lli` (JIT execution) to verify runtime behavior (optional).
4. Parse `llvm-as` stderr output into structured `ValidationError` objects.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from src.types import ErrorCategory, ValidationResult, ValidationError
from src.validator.classifier import classify_llvm_error

logger = logging.getLogger(__name__)


class IRValidator:
    """Validates LLVM IR code using the LLVM toolchain.

    Requires `llvm-as` and (optionally) `lli` to be available in the system PATH.
    """

    def __init__(self, llvm_as_path: str = "llvm-as", lli_path: str = "lli") -> None:
        """Initialize the validator with paths to LLVM tools.

        Args:
            llvm_as_path: Path to the llvm-as executable.
            lli_path: Path to the lli executable.
        """
        self._llvm_as = llvm_as_path
        self._lli = lli_path
        self._check_tools()

    def _check_tools(self) -> None:
        """Verify that required tools are installed and accessible."""
        try:
            subprocess.run(
                [self._llvm_as, "--version"],
                capture_output=True,
                check=True,
                text=True,
            )
        except (FileNotFoundError, subprocess.CalledProcessError) as e:
            logger.warning("llvm-as not found or failed. Validation will fail. (%s)", e)

    def validate_ir(
        self,
        ir_code: str,
        check_execution: bool = False,
        expected_output: Optional[str] = None,
    ) -> ValidationResult:
        """Validate LLVM IR code.

        Args:
            ir_code: The raw LLVM IR string to validate.
            check_execution: If True, also attempt to run it with lli.
            expected_output: If provided, compare lli stdout against this string.

        Returns:
            ValidationResult with status and parsed errors.
        """
        if not ir_code.strip():
            return ValidationResult(
                is_valid=False,
                errors=[
                    ValidationError(
                        category=ErrorCategory.SYNTAX_ERROR,
                        message="Generated IR is empty",
                    )
                ],
            )

        # Write IR to a temporary file
        with tempfile.NamedTemporaryFile(suffix=".ll", mode="w", delete=False) as f:
            f.write(ir_code)
            temp_path = f.name

        try:
            # 1. Assembly & Syntax Check
            result = self._run_llvm_as(temp_path)
            if not result.is_valid:
                return result

            # 2. Execution Check (Optional)
            if check_execution:
                exec_result = self._run_lli(temp_path, expected_output=expected_output)
                if not exec_result.is_valid:
                    return exec_result

            return ValidationResult(is_valid=True, errors=[])

        finally:
            # Cleanup temp file
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def _run_llvm_as(self, file_path: str) -> ValidationResult:
        """Run llvm-as to check IR validity.

        Args:
            file_path: Path to the .ll file.

        Returns:
            ValidationResult. If invalid, parses stderr into ValidationError objects.
        """
        try:
            # -disable-output means "just check syntax, don't write a .bc file"
            process = subprocess.run(
                [self._llvm_as, "-disable-output", file_path],
                capture_output=True,
                text=True,
                timeout=5.0,  # Prevent infinite hangs
            )

            if process.returncode == 0:
                return ValidationResult(is_valid=True)

            # Parse stderr output into structured errors
            errors = self._parse_llvm_as_output(process.stderr)
            return ValidationResult(is_valid=False, errors=errors)

        except subprocess.TimeoutExpired:
            return ValidationResult(
                is_valid=False,
                errors=[
                    ValidationError(
                        category=ErrorCategory.UNKNOWN,
                        message="llvm-as timed out after 5.0 seconds",
                    )
                ],
            )
        except Exception as e:
            logger.error("Failed to execute llvm-as: %s", e)
            return ValidationResult(
                is_valid=False,
                errors=[
                    ValidationError(
                        category=ErrorCategory.UNKNOWN,
                        message=f"Failed to execute llvm-as: {e}",
                    )
                ],
            )

    def _run_lli(
        self,
        file_path: str,
        expected_output: Optional[str] = None,
    ) -> ValidationResult:
        """Run lli to execute the IR and catch runtime crashes/aborts.

        Args:
            file_path: Path to the .ll file.
            expected_output: Optional expected stdout string to compare against.

        Returns:
            ValidationResult indicating runtime success/failure.
            If expected_output is given, also checks for output correctness.
        """
        try:
            process = subprocess.run(
                [self._lli, file_path],
                capture_output=True,
                text=True,
                timeout=10.0,
            )

            if process.returncode != 0:
                msg = f"Runtime error (exit code {process.returncode}): {process.stderr.strip()}"
                return ValidationResult(
                    is_valid=False,
                    errors=[
                        ValidationError(
                            category=ErrorCategory.EXECUTION_ERROR,
                            message=msg,
                            raw_text=process.stderr,
                        )
                    ],
                )

            # Compare stdout against expected output if provided
            if expected_output is not None:
                actual = process.stdout
                # Normalize line endings for comparison
                actual_norm = actual.replace("\r\n", "\n").strip()
                expected_norm = expected_output.replace("\r\n", "\n").strip()
                if actual_norm != expected_norm:
                    msg = (
                        f"Output mismatch.\n"
                        f"  Expected: {repr(expected_norm[:200])}\n"
                        f"  Actual:   {repr(actual_norm[:200])}"
                    )
                    return ValidationResult(
                        is_valid=False,
                        errors=[
                            ValidationError(
                                category=ErrorCategory.EXECUTION_MISMATCH,
                                message=msg,
                                raw_text=actual,
                            )
                        ],
                    )

            return ValidationResult(is_valid=True)

        except subprocess.TimeoutExpired:
            return ValidationResult(
                is_valid=False,
                errors=[
                    ValidationError(
                        category=ErrorCategory.UNKNOWN,
                        message="lli execution timed out after 10.0 seconds (possible infinite loop)",
                    )
                ],
            )
        except Exception as e:
            return ValidationResult(
                is_valid=False,
                errors=[
                    ValidationError(
                        category=ErrorCategory.UNKNOWN,
                        message=f"Failed to execute lli: {e}",
                    )
                ],
            )

    def _parse_llvm_as_output(self, stderr: str) -> list[ValidationError]:
        """Parse stderr output from llvm-as into structured errors.

        Breaks multi-line output into individual error reports and classifies them.
        """
        errors = []
        # llvm-as typically outputs errors in the format:
        # llvm-as: <filename>:<line>:<col>: error: <message>
        # followed by the source line and a caret indicating the column.

        # We'll split the output by 'error:' to isolate distinct issues.
        # But for robustness against varying output formats, we use a regex line scanner.

        lines = stderr.splitlines()
        current_error_msg = []
        current_line_num = None

        error_regex = re.compile(r"^.*:(\d+):\d+: error: (.*)$")

        for line in lines:
            match = error_regex.match(line)
            if match:
                # If we were building an error, save it before starting a new one
                if current_error_msg:
                    raw_text = "\n".join(current_error_msg)
                    category = classify_llvm_error(raw_text)
                    errors.append(
                        ValidationError(
                            category=category,
                            message=current_error_msg[0],  # First line is the main message
                            line=current_line_num,
                            raw_text=raw_text,
                        )
                    )
                    current_error_msg = []

                current_line_num = int(match.group(1))
                current_error_msg.append(match.group(2))
            elif current_error_msg:
                # Append context lines (e.g., the code snippet and caret) to the current error
                current_error_msg.append(line)

        # Save the last error
        if current_error_msg:
            raw_text = "\n".join(current_error_msg)
            category = classify_llvm_error(raw_text)
            errors.append(
                ValidationError(
                    category=category,
                    message=current_error_msg[0],
                    line=current_line_num,
                    raw_text=raw_text,
                )
            )

        # Fallback if the regex failed entirely (e.g., linker errors, module-level errors)
        if not errors and stderr.strip():
            errors.append(
                ValidationError(
                    category=classify_llvm_error(stderr),
                    message="Validation failed (unparsed format)",
                    raw_text=stderr,
                )
            )

        return errors
