"""Unit tests for the LLVM error classifier.

Tests that known llvm-as stderr messages are correctly mapped to ErrorCategory values.
"""

import pytest

from src.types import ErrorCategory
from src.validator.classifier import classify_llvm_error


class TestSSAViolations:
    def test_multiple_definition(self):
        err = "multiple definition of local value named '%x'"
        assert classify_llvm_error(err) == ErrorCategory.SSA_VIOLATION

    def test_redefinition(self):
        err = "redefinition of global named '@main'"
        assert classify_llvm_error(err) == ErrorCategory.SSA_VIOLATION

    def test_does_not_dominate(self):
        err = "Instruction does not dominate all uses!"
        assert classify_llvm_error(err) == ErrorCategory.SSA_VIOLATION

    def test_phi_node(self):
        err = "phi node operands must correspond to a basic block"
        assert classify_llvm_error(err) == ErrorCategory.SSA_VIOLATION


class TestTypeMismatches:
    def test_type_mismatch(self):
        err = "type mismatch: expected i32, got i64"
        assert classify_llvm_error(err) == ErrorCategory.TYPE_MISMATCH

    def test_invalid_operand_types(self):
        err = "invalid operand types for icmp instruction"
        assert classify_llvm_error(err) == ErrorCategory.TYPE_MISMATCH

    def test_expected_to_be_typed(self):
        err = "instruction expected to be typed 'i32', got 'ptr'"
        assert classify_llvm_error(err) == ErrorCategory.TYPE_MISMATCH


class TestMissingTerminator:
    def test_no_terminator(self):
        err = "basic block in function 'main' does not have terminator!"
        assert classify_llvm_error(err) == ErrorCategory.MISSING_TERMINATOR

    def test_terminator_keyword(self):
        err = "basic block terminator required"
        assert classify_llvm_error(err) == ErrorCategory.MISSING_TERMINATOR


class TestMissingDeclaration:
    def test_undefined_value(self):
        err = "use of undefined value '@printf'"
        assert classify_llvm_error(err) == ErrorCategory.MISSING_DECLARATION

    def test_unresolved_reference(self):
        err = "unresolved reference to function 'my_func'"
        assert classify_llvm_error(err) == ErrorCategory.MISSING_DECLARATION

    def test_use_of_undefined(self):
        err = "use of undefined '@foo'"
        assert classify_llvm_error(err) == ErrorCategory.MISSING_DECLARATION


class TestInvalidCFG:
    def test_undefined_block(self):
        err = "reference to undefined block '%nonexistent'"
        assert classify_llvm_error(err) == ErrorCategory.INVALID_CFG

    def test_branch_target(self):
        err = "branch target '%missing_label' is not a basic block"
        assert classify_llvm_error(err) == ErrorCategory.INVALID_CFG


class TestInvalidInstruction:
    def test_invalid_instruction(self):
        err = "invalid instruction mnemonic 'storeimm'"
        assert classify_llvm_error(err) == ErrorCategory.INVALID_INSTRUCTION

    def test_unknown_instruction(self):
        err = "unknown instruction 'fadd' for operands of type 'i32'"
        assert classify_llvm_error(err) == ErrorCategory.INVALID_INSTRUCTION


class TestSyntaxErrors:
    def test_expected_comma(self):
        err = "expected comma after getelementptr's type"
        assert classify_llvm_error(err) == ErrorCategory.SYNTAX_ERROR

    def test_expected_brace(self):
        err = "expected '{' in function body"
        assert classify_llvm_error(err) == ErrorCategory.SYNTAX_ERROR

    def test_syntax_error_keyword(self):
        err = "syntax error: unexpected '%'"
        assert classify_llvm_error(err) == ErrorCategory.SYNTAX_ERROR


class TestFallback:
    def test_unknown_returns_unknown(self):
        err = "some completely unrecognized error format 12345"
        assert classify_llvm_error(err) == ErrorCategory.UNKNOWN

    def test_empty_string(self):
        # Empty/whitespace should fall through to UNKNOWN
        assert classify_llvm_error("") == ErrorCategory.UNKNOWN

    def test_case_insensitive(self):
        # Classifier lowercases input — ensure it handles mixed case
        err = "MULTIPLE DEFINITION of local value named '%X'"
        assert classify_llvm_error(err) == ErrorCategory.SSA_VIOLATION
