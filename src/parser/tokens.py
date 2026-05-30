"""Token definitions for the MiniLang lexer."""

from __future__ import annotations
from dataclasses import dataclass
from enum import Enum, auto
from typing import Any


class TokenType(Enum):
    # Literals
    INT_LITERAL = auto()
    FLOAT_LITERAL = auto()
    STRING_LITERAL = auto()
    IDENTIFIER = auto()

    # Keywords
    FN = auto()          # fn
    LET = auto()         # let
    IF = auto()          # if
    ELSE = auto()        # else
    WHILE = auto()       # while
    FOR = auto()         # for
    RETURN = auto()       # return
    PRINT = auto()       # print
    INT_TYPE = auto()    # int
    FLOAT_TYPE = auto()  # float
    VOID_TYPE = auto()   # void
    STRING_TYPE = auto() # string
    TRUE = auto()        # true
    FALSE = auto()       # false

    # Operators
    PLUS = auto()        # +
    MINUS = auto()       # -
    STAR = auto()        # *
    SLASH = auto()       # /
    PERCENT = auto()     # %
    ASSIGN = auto()      # =
    EQ = auto()          # ==
    NEQ = auto()         # !=
    LT = auto()          # <
    GT = auto()          # >
    LTE = auto()         # <=
    GTE = auto()         # >=
    AND = auto()         # &&
    OR = auto()          # ||
    NOT = auto()         # !

    # Delimiters
    LPAREN = auto()      # (
    RPAREN = auto()      # )
    LBRACE = auto()      # {
    RBRACE = auto()      # }
    LBRACKET = auto()    # [
    RBRACKET = auto()    # ]
    COMMA = auto()       # ,
    COLON = auto()       # :
    SEMICOLON = auto()   # ;
    ARROW = auto()       # ->

    # Special
    EOF = auto()


@dataclass(frozen=True)
class Token:
    """A lexical token with position information."""
    type: TokenType
    value: Any
    line: int
    column: int

    def __repr__(self) -> str:
        return f"Token({self.type.name}, {self.value!r}, L{self.line}:{self.column})"


KEYWORDS: dict[str, TokenType] = {
    "fn": TokenType.FN,
    "let": TokenType.LET,
    "if": TokenType.IF,
    "else": TokenType.ELSE,
    "while": TokenType.WHILE,
    "for": TokenType.FOR,
    "return": TokenType.RETURN,
    "print": TokenType.PRINT,
    "int": TokenType.INT_TYPE,
    "float": TokenType.FLOAT_TYPE,
    "void": TokenType.VOID_TYPE,
    "string": TokenType.STRING_TYPE,
    "true": TokenType.TRUE,
    "false": TokenType.FALSE,
}
