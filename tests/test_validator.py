"""Unit tests for the IR Validator.

Tests both the llvm-as validation path and the output comparison logic.
Requires llvm-as and lli to be installed (skips gracefully if not found).
"""

import subprocess
import pytest

from src.types import ErrorCategory
from src.validator.validator import IRValidator


def _llvm_tools_available() -> bool:
    """Return True if both llvm-as and lli are available on PATH."""
    for tool in ("llvm-as", "lli"):
        try:
            subprocess.run([tool, "--version"], capture_output=True, check=True, timeout=5)
        except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
            return False
    return True


requires_llvm = pytest.mark.skipif(
    not _llvm_tools_available(),
    reason="llvm-as/lli not installed — skipping LLVM integration tests",
)


# ── Known-Good IR Snippets ────────────────────────────────────────────────────

VALID_HELLO_IR = """\
; ModuleID = 'test'
source_filename = "test"
target datalayout = "e-m:e-p270:32:32-p271:32:32-p272:64:64-i64:64-f80:128-n8:16:32:64-S128"
target triple = "x86_64-pc-linux-gnu"

@.fmt = private constant [4 x i8] c"%d\\0A\\00"

declare i32 @printf(ptr, ...)

define i32 @main() {
entry:
  call i32 (ptr, ...) @printf(ptr @.fmt, i32 42)
  ret i32 0
}
"""

VALID_ARITHMETIC_IR = """\
; ModuleID = 'arith'
target triple = "x86_64-pc-linux-gnu"

define i32 @add(i32 %a, i32 %b) {
entry:
  %result = add i32 %a, %b
  ret i32 %result
}

define i32 @main() {
entry:
  %ans = call i32 @add(i32 20, i32 22)
  ret i32 0
}
"""

# ── Known-Bad IR Snippets ─────────────────────────────────────────────────────

# Missing terminator in then block
MISSING_TERMINATOR_IR = """\
target triple = "x86_64-pc-linux-gnu"

define i32 @main() {
entry:
  %cmp = icmp sgt i32 5, 3
  br i1 %cmp, label %if.then, label %if.end
if.then:
  ; Missing br label %if.end  ← intentional bug
if.end:
  ret i32 0
}
"""

# SSA violation: using %x before definition
SSA_VIOLATION_IR = """\
target triple = "x86_64-pc-linux-gnu"

define i32 @main() {
entry:
  %y = add i32 %x, 1
  %x = add i32 0, 42
  ret i32 %y
}
"""

# Missing @printf declaration
MISSING_DECL_IR = """\
target triple = "x86_64-pc-linux-gnu"

@.fmt = private constant [4 x i8] c"%d\\0A\\00"

define i32 @main() {
entry:
  call i32 (ptr, ...) @printf(ptr @.fmt, i32 42)
  ret i32 0
}
"""

# Completely empty IR
EMPTY_IR = ""
WHITESPACE_IR = "   \n  \t  "


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestValidatorEmptyInput:
    """Empty IR is rejected without needing llvm-as."""

    def setup_method(self):
        # Use non-existent tool paths — empty check should fire before subprocess
        self.validator = IRValidator(llvm_as_path="llvm-as", lli_path="lli")

    def test_empty_ir_rejected(self):
        result = self.validator.validate_ir("")
        assert not result.is_valid
        assert len(result.errors) == 1
        assert result.errors[0].category == ErrorCategory.SYNTAX_ERROR
        assert "empty" in result.errors[0].message.lower()

    def test_whitespace_only_rejected(self):
        result = self.validator.validate_ir("   \n\t  ")
        assert not result.is_valid


@requires_llvm
class TestValidatorWithLLVM:
    """Integration tests that require real llvm-as/lli."""

    def setup_method(self):
        self.validator = IRValidator()

    def test_valid_arithmetic_ir(self):
        result = self.validator.validate_ir(VALID_ARITHMETIC_IR)
        assert result.is_valid
        assert result.errors == []

    def test_missing_terminator_detected(self):
        result = self.validator.validate_ir(MISSING_TERMINATOR_IR)
        assert not result.is_valid
        # Should be classified as MISSING_TERMINATOR, SYNTAX_ERROR, SSA_VIOLATION,
        # or INVALID_INSTRUCTION (llvm-as 18 reports empty blocks differently)
        categories = {e.category for e in result.errors}
        assert categories & {
            ErrorCategory.MISSING_TERMINATOR,
            ErrorCategory.SYNTAX_ERROR,
            ErrorCategory.SSA_VIOLATION,
            ErrorCategory.INVALID_INSTRUCTION,
        }

    def test_ssa_violation_detected(self):
        result = self.validator.validate_ir(SSA_VIOLATION_IR)
        assert not result.is_valid

    def test_missing_declaration_detected(self):
        result = self.validator.validate_ir(MISSING_DECL_IR)
        assert not result.is_valid
        categories = {e.category for e in result.errors}
        assert ErrorCategory.MISSING_DECLARATION in categories


@requires_llvm
class TestOutputComparison:
    """Test the lli execution + expected output comparison."""

    def setup_method(self):
        self.validator = IRValidator()

    def test_correct_output_passes(self):
        result = self.validator.validate_ir(
            VALID_HELLO_IR,
            check_execution=True,
            expected_output="42\n",
        )
        assert result.is_valid

    def test_wrong_output_fails(self):
        result = self.validator.validate_ir(
            VALID_HELLO_IR,
            check_execution=True,
            expected_output="999\n",
        )
        assert not result.is_valid
        assert result.errors[0].category == ErrorCategory.EXECUTION_MISMATCH
        assert "mismatch" in result.errors[0].message.lower()

    def test_no_expected_output_skips_comparison(self):
        # When expected_output=None, execution check still runs but doesn't compare
        result = self.validator.validate_ir(
            VALID_HELLO_IR,
            check_execution=True,
            expected_output=None,
        )
        assert result.is_valid
