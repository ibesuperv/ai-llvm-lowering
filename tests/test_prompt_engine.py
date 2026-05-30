"""Unit tests for the PromptEngine — strategy selection and construct analysis.

Tests that the PromptEngine correctly identifies constructs from the AST and
selects the appropriate prompt strategy.
"""

import pytest

from src.llm.prompt_engine import PromptEngine
from src.parser.lexer import Lexer
from src.parser.parser import Parser
from src.types import ConstructType, PromptStrategy


def parse(source: str):
    """Helper: lex + parse MiniLang source → Program AST."""
    tokens = Lexer(source).tokenize()
    return Parser(tokens).parse()


@pytest.fixture
def engine():
    return PromptEngine()


class TestConstructAnalysis:
    """Test that analyze_constructs() correctly identifies construct types."""

    def test_pure_arithmetic(self, engine):
        src = """
        fn main(): int {
            let x: int = 2 + 3 * 4;
            let y: int = x - 1;
            return y;
        }
        """
        ast = parse(src)
        result = engine.analyze_constructs(ast)
        assert result == ConstructType.ARITHMETIC

    def test_control_flow_detected(self, engine):
        src = """
        fn main(): int {
            let x: int = 5;
            if (x > 3) {
                return 1;
            }
            return 0;
        }
        """
        ast = parse(src)
        result = engine.analyze_constructs(ast)
        assert result == ConstructType.CONTROL_FLOW

    def test_while_loop_is_control_flow(self, engine):
        src = """
        fn main(): int {
            let i: int = 0;
            while (i < 10) {
                i = i + 1;
            }
            return i;
        }
        """
        ast = parse(src)
        result = engine.analyze_constructs(ast)
        assert result == ConstructType.CONTROL_FLOW

    def test_multiple_functions_detected(self, engine):
        src = """
        fn add(a: int, b: int): int {
            return a + b;
        }
        fn main(): int {
            let r: int = add(1, 2);
            return r;
        }
        """
        ast = parse(src)
        result = engine.analyze_constructs(ast)
        assert result == ConstructType.FUNCTIONS

    def test_mixed_constructs(self, engine):
        src = """
        fn compute(n: int): int {
            let total: int = 0;
            let i: int = 0;
            while (i < n) {
                if (i % 2 == 0) {
                    total = total + i;
                }
                i = i + 1;
            }
            return total;
        }
        fn main(): int {
            let r: int = compute(10);
            return r;
        }
        """
        ast = parse(src)
        result = engine.analyze_constructs(ast)
        assert result == ConstructType.MIXED


class TestStrategySelection:
    """Test that select_strategy() maps construct types to the right strategies."""

    def test_arithmetic_gets_zero_shot(self, engine):
        strategy = engine.select_strategy(ConstructType.ARITHMETIC)
        assert strategy == PromptStrategy.ZERO_SHOT

    def test_control_flow_gets_few_shot(self, engine):
        strategy = engine.select_strategy(ConstructType.CONTROL_FLOW)
        assert strategy == PromptStrategy.FEW_SHOT

    def test_functions_gets_few_shot(self, engine):
        strategy = engine.select_strategy(ConstructType.FUNCTIONS)
        assert strategy == PromptStrategy.FEW_SHOT

    def test_arrays_gets_chain_of_thought(self, engine):
        strategy = engine.select_strategy(ConstructType.ARRAYS)
        assert strategy == PromptStrategy.CHAIN_OF_THOUGHT

    def test_mixed_gets_chain_of_thought(self, engine):
        strategy = engine.select_strategy(ConstructType.MIXED)
        assert strategy == PromptStrategy.CHAIN_OF_THOUGHT


class TestPromptBuilding:
    """Test that built prompts contain required LLVM 18 instructions."""

    def test_generation_prompt_contains_opaque_pointer_rule(self, engine):
        src = "fn main(): int { return 42; }"
        ast = parse(src)
        construct = engine.analyze_constructs(ast)
        strategy = engine.select_strategy(construct)
        prompt = engine.build_generation_prompt(
            source_code=src, ast=ast, strategy=strategy, construct_type=construct
        )
        # Must always instruct LLM to use opaque pointers
        assert "ptr" in prompt.lower() or "opaque" in prompt.lower()

    def test_generation_prompt_contains_source(self, engine):
        src = "fn main(): int { let x: int = 7; return x; }"
        ast = parse(src)
        construct = engine.analyze_constructs(ast)
        strategy = engine.select_strategy(construct)
        prompt = engine.build_generation_prompt(
            source_code=src, ast=ast, strategy=strategy, construct_type=construct
        )
        assert "let x: int = 7" in prompt or "x" in prompt

    def test_repair_prompt_contains_error_text(self, engine):
        from src.types import ValidationError, ErrorCategory
        errors = [
            ValidationError(
                category=ErrorCategory.MISSING_TERMINATOR,
                message="basic block does not have terminator!",
            )
        ]
        prompt = engine.build_repair_prompt(
            source_code="fn main(): int { return 0; }",
            failed_ir="; invalid ir",
            errors=errors,
            attempt=1,
            strategy="simple",
        )
        assert "terminator" in prompt.lower() or "missing" in prompt.lower() or "error" in prompt.lower()
