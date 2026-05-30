"""AST node definitions for MiniLang — all three tiers."""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
from src.types import DataType, LanguageTier


class ASTNode:
    """Base class for all AST nodes. Carries source location."""
    line: int = 0
    column: int = 0


# ─── Program Structure ───────────────────────────────────────────

@dataclass
class Program(ASTNode):
    functions: list[Function] = field(default_factory=list)
    tier: LanguageTier = LanguageTier.TIER_1

@dataclass
class Function(ASTNode):
    name: str = ""
    params: list[Parameter] = field(default_factory=list)
    return_type: DataType = DataType.VOID
    body: Block = field(default_factory=lambda: Block())

@dataclass
class Parameter(ASTNode):
    name: str = ""
    type: DataType = DataType.INT

@dataclass
class Block(ASTNode):
    statements: list[Statement] = field(default_factory=list)


# ─── Statements ──────────────────────────────────────────────────

@dataclass
class Statement(ASTNode):
    """Base class for all statements."""
    pass

@dataclass
class VarDecl(Statement):              # let x: int = 5;
    name: str = ""
    type: DataType = DataType.INT
    value: Optional[Expression] = None

@dataclass
class Assignment(Statement):           # x = expr;
    target: str = ""
    index: Optional[Expression] = None  # For array assignment: arr[i] = expr
    value: Optional[Expression] = None

@dataclass
class IfStmt(Statement):              # if (cond) { } else { }
    condition: Optional[Expression] = None
    then_block: Block = field(default_factory=lambda: Block())
    else_block: Optional[Block] = None

@dataclass
class WhileStmt(Statement):           # while (cond) { }
    condition: Optional[Expression] = None
    body: Block = field(default_factory=lambda: Block())

@dataclass
class ForStmt(Statement):             # for (let i: int = 0; i < 10; i = i + 1) { }
    init: Optional[VarDecl] = None
    condition: Optional[Expression] = None
    update: Optional[Assignment] = None
    body: Block = field(default_factory=lambda: Block())

@dataclass
class ReturnStmt(Statement):          # return expr;
    value: Optional[Expression] = None

@dataclass
class PrintStmt(Statement):           # print(expr);
    value: Optional[Expression] = None


# ─── Expressions ─────────────────────────────────────────────────

@dataclass
class Expression(ASTNode):
    """Base class for all expressions."""
    pass

@dataclass
class IntLiteral(Expression):
    value: int = 0

@dataclass
class FloatLiteral(Expression):        # [Tier 2+]
    value: float = 0.0

@dataclass
class StringLiteral(Expression):       # [Tier 3]
    value: str = ""

@dataclass
class BoolLiteral(Expression):         # [Tier 2+]
    value: bool = False

@dataclass
class Identifier(Expression):
    name: str = ""

@dataclass
class BinaryOp(Expression):
    left: Optional[Expression] = None
    op: str = ""
    right: Optional[Expression] = None

@dataclass
class UnaryOp(Expression):
    op: str = ""
    operand: Optional[Expression] = None

@dataclass
class FunctionCall(Expression):
    name: str = ""
    args: list[Expression] = field(default_factory=list)

@dataclass
class ArrayAccess(Expression):         # [Tier 3]
    array: str = ""
    index: Optional[Expression] = None

@dataclass
class ArrayLiteral(Expression):        # [Tier 3]
    elements: list[Expression] = field(default_factory=list)
    element_type: DataType = DataType.INT
