"""Unit tests for the MiniLang parser."""

import pytest
from src.parser import Lexer, Parser, ParseError

def test_arithmetic_tier_1():
    source = "fn main(): int { return 1 + 2 * 3; }"
    tokens = Lexer(source).tokenize()
    ast = Parser(tokens).parse()
    
    assert len(ast.functions) == 1
    assert ast.functions[0].name == "main"
    assert ast.tier.value == 1

def test_float_tier_2():
    source = "fn calc(): float { let x: float = 3.14; return x; }"
    tokens = Lexer(source).tokenize()
    ast = Parser(tokens).parse()
    
    assert ast.tier.value == 2

def test_array_tier_3():
    source = "fn process(arr: int[]): void { arr[0] = 42; }"
    tokens = Lexer(source).tokenize()
    ast = Parser(tokens).parse()
    
    assert ast.tier.value == 3

def test_syntax_error():
    source = "fn main() int { return 0; }"  # Missing colon
    tokens = Lexer(source).tokenize()
    with pytest.raises(ParseError):
        Parser(tokens).parse()
