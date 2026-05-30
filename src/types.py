"""Shared type definitions used across all modules of the AI-LLVM Lowering pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Optional


# ─── Language Tier System ──────────────────────────────────────────

class LanguageTier(Enum):
    """Progressive complexity tiers for the source language."""
    TIER_1 = 1  # Variables, arithmetic, if/else, while, functions
    TIER_2 = 2  # + floats, for loops, logical ops, nested control flow
    TIER_3 = 3  # + arrays, recursion, strings

    def __str__(self) -> str:
        return f"Tier {self.value}"


class DataType(Enum):
    """MiniLang type system."""
    INT = "int"
    FLOAT = "float"
    VOID = "void"
    STRING = "string"
    ARRAY_INT = "int[]"
    ARRAY_FLOAT = "float[]"
    BOOL = "bool"


# ─── Construct Classification (for dynamic prompt selection) ──────

class ConstructType(Enum):
    """Categories of language constructs for prompt template routing."""
    ARITHMETIC = auto()       # Pure arithmetic expressions
    CONTROL_FLOW = auto()     # if/else, while, for
    FUNCTIONS = auto()        # Function definitions and calls
    ARRAYS = auto()           # Array operations
    MIXED = auto()            # Multiple construct categories


# ─── LLM Configuration ───────────────────────────────────────────

class PromptStrategy(Enum):
    """LLM prompting strategies."""
    ZERO_SHOT = "zero_shot"
    FEW_SHOT = "few_shot"
    CHAIN_OF_THOUGHT = "chain_of_thought"


@dataclass(frozen=True)
class ModelConfig:
    """Configuration for a specific LLM model."""
    provider: str                   # "gemini" | "groq"
    model_id: str                   # e.g., "gemini-2.0-flash"
    display_name: str               # Human-readable name
    max_tokens: int = 4096
    default_temperature: float = 0.2
    rate_limit_rpm: int = 15        # Requests per minute


# ─── Validation Types ────────────────────────────────────────────

class ErrorCategory(Enum):
    """Failure mode categories for LLVM IR errors."""
    SSA_VIOLATION = "SSA Violation"
    TYPE_MISMATCH = "Type Mismatch"
    INVALID_CFG = "Invalid Control Flow Graph"
    UNDEFINED_REFERENCE = "Undefined Reference"
    SYNTAX_ERROR = "Syntax Error"
    MISSING_TERMINATOR = "Missing Block Terminator"
    INVALID_INSTRUCTION = "Invalid Instruction"
    MISSING_DECLARATION = "Missing Declaration"
    EXECUTION_MISMATCH = "Execution Output Mismatch"
    EXECUTION_ERROR = "Runtime Execution Error"
    OTHER = "Uncategorized"
    UNKNOWN = "Unknown Error"


class ErrorSeverity(Enum):
    ERROR = "error"
    WARNING = "warning"


@dataclass
class ValidationError:
    """A single validation error with classification."""
    category: ErrorCategory
    message: str
    line: Optional[int] = None
    column: Optional[int] = None
    severity: ErrorSeverity = ErrorSeverity.ERROR
    raw_text: str = ""
    suggestion: Optional[str] = None


@dataclass
class ValidationResult:
    """Complete result of validating an LLVM IR fragment."""
    is_valid: bool
    errors: list[ValidationError] = field(default_factory=list)
    error_categories: dict[ErrorCategory, int] = field(default_factory=dict)
    raw_stderr: str = ""
    ir_code: str = ""

    @property
    def error_count(self) -> int:
        return len(self.errors)

    @property
    def category_distribution(self) -> dict[str, int]:
        return {cat.value: count for cat, count in self.error_categories.items()}


@dataclass
class ExecutionResult:
    """Result of executing LLVM IR via lli."""
    success: bool
    actual_output: str = ""
    expected_output: str = ""
    matches: bool = False
    exit_code: int = -1
    stderr: str = ""
    duration_ms: float = 0.0


# ─── Repair Types ────────────────────────────────────────────────

class RepairStrategy(Enum):
    """Strategies for repairing invalid IR."""
    SIMPLE_RETRY = "simple_retry"           # Feed error back, ask to fix
    TARGETED_FIX = "targeted_fix"           # Parse error, give specific instruction
    FULL_REGENERATION = "full_regeneration"  # Regenerate with higher temperature


@dataclass
class RepairAttempt:
    """Record of a single repair attempt."""
    attempt_number: int
    prompt: str
    response: "Any"  # LLMResponse — avoid circular import
    validation: ValidationResult
    duration_ms: float = 0.0


@dataclass
class RepairResult:
    """Complete result of the repair loop."""
    success: bool
    final_ir: str
    attempts: list[RepairAttempt] = field(default_factory=list)
    total_attempts: int = 0
    strategy_used: Optional[RepairStrategy] = None


# ─── Pipeline Types ──────────────────────────────────────────────

@dataclass
class ModelResult:
    """Result from a single LLM model's attempt at IR generation."""
    model_name: str
    prompt_strategy: PromptStrategy
    construct_type: ConstructType
    initial_ir: str
    initial_validation: ValidationResult
    repair_result: Optional[RepairResult] = None
    final_ir: str = ""
    final_validation: Optional[ValidationResult] = None
    execution_result: Optional[ExecutionResult] = None
    duration_ms: float = 0.0

    @property
    def succeeded(self) -> bool:
        return self.final_validation is not None and self.final_validation.is_valid


@dataclass
class TaskResult:
    """Result of running a compilation task."""
    source_code: str
    tier: LanguageTier
    prompt_strategy: PromptStrategy
    model_id: str
    success: bool
    final_ir: str
    repair_attempts: list[RepairAttempt]


@dataclass
class PipelineResult:
    """Complete result from processing a single source file."""
    source_file: str
    source_code: str
    tier: LanguageTier
    construct_type: ConstructType
    model_results: dict[str, ModelResult] = field(default_factory=dict)
    best_result: Optional[ModelResult] = None
    duration_ms: float = 0.0
    expected_output: Optional[str] = None


@dataclass
class EvaluationMetrics:
    """Aggregate evaluation metrics across all test cases."""
    total_cases: int = 0
    initial_correct: int = 0
    repaired_correct: int = 0
    final_correct: int = 0
    initial_correctness_pct: float = 0.0
    repair_success_rate: float = 0.0
    final_correctness_pct: float = 0.0
    avg_repair_attempts: float = 0.0
    failure_distribution: dict[str, int] = field(default_factory=dict)
    per_tier_metrics: dict[LanguageTier, dict] = field(default_factory=dict)
    per_model_metrics: dict[str, dict] = field(default_factory=dict)
    per_strategy_metrics: dict[str, dict] = field(default_factory=dict)
