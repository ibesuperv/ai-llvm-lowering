"""Error classifier for llvm-as error messages.

Maps raw stderr strings from the LLVM assembler to structured `ErrorCategory`
enums using heuristic string matching and regex.

This categorization drives the targeted repair prompt generation and
powers the final evaluation statistics.
"""

import re
from src.types import ErrorCategory


def classify_llvm_error(error_text: str) -> ErrorCategory:
    """Classify a raw llvm-as error message into a specific ErrorCategory.

    Uses a sequence of regex and string matches ordered roughly from
    most specific to least specific.

    Args:
        error_text: The full text of the error (potentially multi-line).

    Returns:
        The matched ErrorCategory, or ErrorCategory.UNKNOWN if no match.
    """
    error_text = error_text.lower()

    # ── 1. SSA Violations ────────────────────────────────────────────────
    # e.g., "multiple definition of local value named 'x'"
    # e.g., "instruction forward referenced with type" (use before def)
    if (
        "multiple definition" in error_text
        or "redefinition" in error_text
        or "forward referenced" in error_text
        or "does not dominate all uses" in error_text
        or "phi node" in error_text
    ):
        return ErrorCategory.SSA_VIOLATION

    # ── 2. Type Mismatches ───────────────────────────────────────────────
    # e.g., "instruction expected to be typed 'i32', got 'ptr'"
    # e.g., "invalid operand types for icmp"
    if (
        "type mismatch" in error_text
        or "invalid operand types" in error_text
        or "expected to be typed" in error_text
        or "invalid cast" in error_text
        or "different type" in error_text
    ):
        return ErrorCategory.TYPE_MISMATCH

    # ── 3. Missing Terminators ───────────────────────────────────────────
    # e.g., "basic block in function 'main' does not have terminator!"
    # e.g., "expected instruction opcode" (often happens at end of block)
    if "does not have terminator" in error_text or "terminator" in error_text:
        return ErrorCategory.MISSING_TERMINATOR

    # ── 4. Missing Declarations / Undefined References ───────────────────
    # e.g., "use of undefined value '@printf'"
    # e.g., "unresolved reference to function"
    if (
        "undefined value" in error_text
        or "unresolved reference" in error_text
        or "use of undefined" in error_text
    ):
        return ErrorCategory.MISSING_DECLARATION

    # ── 5. Invalid Control Flow Graph (CFG) ──────────────────────────────
    # e.g., "reference to undefined block"
    # e.g., "branch target not found"
    if (
        "undefined block" in error_text
        or "branch target" in error_text
        or "not a basic block" in error_text
    ):
        return ErrorCategory.INVALID_CFG

    # ── 6. Invalid Instructions ──────────────────────────────────────────
    # e.g., "invalid instruction mnemonic"
    # e.g., "expected instruction opcode"
    if (
        "invalid instruction" in error_text
        or "expected instruction" in error_text
        or "unknown instruction" in error_text
        or "bad instruction" in error_text
    ):
        return ErrorCategory.INVALID_INSTRUCTION

    # ── 7. Syntax Errors ─────────────────────────────────────────────────
    # e.g., "expected comma after getelementptr's type"
    # e.g., "expected '{' in function body"
    if (
        "expected" in error_text
        or "syntax error" in error_text
        or "unexpected token" in error_text
        or "invalid character" in error_text
    ):
        return ErrorCategory.SYNTAX_ERROR

    # ── 8. Fallback ──────────────────────────────────────────────────────
    return ErrorCategory.UNKNOWN
