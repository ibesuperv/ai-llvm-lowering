"""Dynamic prompt selection and construction engine.

The prompt engine is the 'brain' of the LLM interaction layer. It:
1. Analyzes the AST to determine the dominant construct category
2. Selects the optimal prompt strategy (zero-shot / few-shot / CoT)
3. Builds the generation prompt with construct-specific examples
4. Builds repair prompts with error context and targeted fix instructions

All prompts are designed for LLVM 18 with opaque pointers (ptr, not i32*).
"""

from __future__ import annotations

import logging
from typing import Optional

from src.parser.ast_nodes import (
    ASTNode, ArrayAccess, ArrayLiteral, BinaryOp, BoolLiteral, FloatLiteral,
    ForStmt, FunctionCall, IfStmt, Program, StringLiteral, WhileStmt,
)
from src.parser.parser import _walk_ast
from src.types import ConstructType, ErrorCategory, PromptStrategy, ValidationError

logger = logging.getLogger(__name__)


class PromptEngine:
    """Constructs optimized prompts based on source code AST analysis.

    Usage:
        engine = PromptEngine()
        construct = engine.analyze_constructs(ast)
        strategy = engine.select_strategy(construct)
        prompt = engine.build_generation_prompt(source, ast, strategy, construct)
    """

    def __init__(self, llvm_version: str = "18") -> None:
        self._llvm_version = llvm_version

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  Construct Analysis & Strategy Selection
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def analyze_constructs(self, ast: Program) -> ConstructType:
        """Walk the AST to determine the dominant construct category.

        Returns MIXED if multiple categories are present.
        """
        has_control = False
        has_functions = False
        has_arrays = False
        has_arithmetic = False

        func_names = {f.name for f in ast.functions}

        for node in _walk_ast(ast):
            if isinstance(node, (IfStmt, WhileStmt, ForStmt)):
                has_control = True
            elif isinstance(node, FunctionCall) and node.name not in ("print",):
                has_functions = True
            elif isinstance(node, (ArrayAccess, ArrayLiteral)):
                has_arrays = True
            elif isinstance(node, BinaryOp) and node.op in ("+", "-", "*", "/", "%"):
                has_arithmetic = True

        categories = sum([has_control, has_functions, has_arrays])

        if has_arrays:
            return ConstructType.ARRAYS
        if categories >= 2:
            return ConstructType.MIXED
        if has_functions:
            return ConstructType.FUNCTIONS
        if has_control:
            return ConstructType.CONTROL_FLOW
        return ConstructType.ARITHMETIC

    def select_strategy(self, construct_type: ConstructType) -> PromptStrategy:
        """Select the best prompt strategy for the given construct type.

        Policy:
        - ARITHMETIC → ZERO_SHOT (simple enough for direct translation)
        - CONTROL_FLOW → FEW_SHOT (needs branch/loop basic block examples)
        - FUNCTIONS → FEW_SHOT (needs calling convention examples)
        - ARRAYS → CHAIN_OF_THOUGHT (complex GEP needs step-by-step reasoning)
        - MIXED → CHAIN_OF_THOUGHT (complex programs benefit from reasoning)
        """
        strategy_map = {
            ConstructType.ARITHMETIC: PromptStrategy.ZERO_SHOT,
            ConstructType.CONTROL_FLOW: PromptStrategy.FEW_SHOT,
            ConstructType.FUNCTIONS: PromptStrategy.FEW_SHOT,
            ConstructType.ARRAYS: PromptStrategy.CHAIN_OF_THOUGHT,
            ConstructType.MIXED: PromptStrategy.CHAIN_OF_THOUGHT,
        }
        return strategy_map[construct_type]

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  Generation Prompts
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def build_generation_prompt(
        self,
        source_code: str,
        ast: Program,
        strategy: PromptStrategy,
        construct_type: ConstructType,
    ) -> str:
        """Build a complete prompt for initial IR generation."""
        if strategy == PromptStrategy.ZERO_SHOT:
            return self._zero_shot_prompt(source_code)
        elif strategy == PromptStrategy.FEW_SHOT:
            return self._few_shot_prompt(source_code, construct_type)
        else:
            return self._chain_of_thought_prompt(source_code)

    def _zero_shot_prompt(self, source_code: str) -> str:
        return f"""You are an expert LLVM IR compiler backend. Translate the following MiniLang source code into valid LLVM IR.

=== SOURCE CODE ===
{source_code}

=== REQUIREMENTS ===
1. Generate valid LLVM IR in SSA form for LLVM 18
2. Use alloca + store + load pattern for ALL local variables
3. Type mapping: int → i32, float → double, void → void, bool → i1
4. Use OPAQUE POINTERS (ptr) — NOT typed pointers like i32*
5. Every basic block MUST end with exactly ONE terminator (ret, br)
6. Declare external functions: declare i32 @printf(ptr, ...)
7. For print(int): call @printf with @.fmt.int = "%d\\0A" format string
8. For print(float): call @printf with @.fmt.float = "%f\\0A" format string
9. Target triple: x86_64-pc-linux-gnu
10. Main function must return i32

=== OUTPUT ===
Output ONLY the complete LLVM IR. No explanations. No markdown fencing. Start directly with the IR."""

    def _few_shot_prompt(self, source_code: str, construct_type: ConstructType) -> str:
        examples = self._get_examples(construct_type)
        return f"""You are an expert LLVM IR compiler backend. Below are examples of MiniLang source code and their correct LLVM IR translations for LLVM 18. Use these as reference.

{examples}

=== NOW TRANSLATE THIS ===
--- MiniLang ---
{source_code}

=== REQUIREMENTS ===
- LLVM 18 syntax with OPAQUE POINTERS (ptr, NOT i32*)
- SSA form with alloca/store/load pattern
- Every basic block ends with exactly ONE terminator (ret, br)
- declare i32 @printf(ptr, ...) for print statements
- int → i32, float → double, void → void

--- LLVM IR ---
Output ONLY the LLVM IR. No explanations. Start directly with the IR."""

    def _chain_of_thought_prompt(self, source_code: str) -> str:
        return f"""You are an expert LLVM IR compiler backend. Translate MiniLang source code to valid LLVM IR for LLVM 18. Think step by step.

=== SOURCE CODE ===
{source_code}

=== TRANSLATION STEPS ===
Work through these IN ORDER:

Step 1 — Declarations: List all functions, parameters, return types, local variables.
Step 2 — Type mapping: int→i32, float→double, void→void, bool→i1, arrays→ptr (opaque pointers).
Step 3 — Plan basic blocks:
  - entry: always present (allocas + parameter stores)
  - if.then / if.else / if.end for conditionals
  - while.cond / while.body / while.end for loops
  - Each block MUST end with exactly one terminator (ret, br)
Step 4 — SSA form: Use alloca+store+load for ALL mutable variables. Each SSA value (%0, %1) assigned once.
Step 5 — External declarations: declare i32 @printf(ptr, ...) for print.

=== CONSTRAINTS ===
- LLVM 18: Use OPAQUE POINTERS (ptr), NOT typed pointers (i32*)
- Format strings: @.fmt.int = private constant [4 x i8] c"%d\\0A\\00"
- All blocks must have terminators
- Use i32 0 as return value for main

=== OUTPUT ===
After your analysis, output the final LLVM IR between these markers:
===LLVM_IR_START===
(complete IR here)
===LLVM_IR_END==="""

    def _get_examples(self, construct_type: ConstructType) -> str:
        """Return few-shot examples appropriate for the construct type."""
        examples = []

        if construct_type in (ConstructType.ARITHMETIC, ConstructType.FUNCTIONS, ConstructType.MIXED):
            examples.append(_EXAMPLE_ARITHMETIC)
        if construct_type in (ConstructType.CONTROL_FLOW, ConstructType.MIXED):
            examples.append(_EXAMPLE_IF_ELSE)
            examples.append(_EXAMPLE_WHILE_LOOP)
        if construct_type == ConstructType.FUNCTIONS:
            examples.append(_EXAMPLE_FUNCTION_CALL)

        return "\n\n".join(examples)

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  Repair Prompts
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def build_repair_prompt(
        self,
        source_code: str,
        failed_ir: str,
        errors: list[ValidationError],
        attempt: int,
        strategy: str,
    ) -> str:
        """Build a repair prompt with error context.

        Args:
            source_code: Original MiniLang source.
            failed_ir: The invalid LLVM IR that needs fixing.
            errors: Classified validation errors.
            attempt: Current repair attempt number (0-indexed).
            strategy: "simple", "targeted", or "regenerate".
        """
        if strategy == "simple":
            return self._simple_repair_prompt(source_code, failed_ir, errors)
        elif strategy == "targeted":
            return self._targeted_repair_prompt(source_code, failed_ir, errors)
        else:
            return self._regeneration_prompt(source_code, errors)

    def _simple_repair_prompt(
        self, source_code: str, failed_ir: str, errors: list[ValidationError]
    ) -> str:
        error_text = "\n".join(e.raw_text or str(e) for e in errors[:10])
        return f"""The LLVM IR you generated has errors. Fix them.

=== ORIGINAL SOURCE CODE ===
{source_code}

=== YOUR PREVIOUS IR (INVALID) ===
{failed_ir}

=== ERRORS FROM llvm-as ===
{error_text}

Fix ALL errors. Output the COMPLETE corrected LLVM IR.
Use LLVM 18 opaque pointers (ptr, NOT i32*).
Output ONLY the IR, no explanations."""

    def _targeted_repair_prompt(
        self, source_code: str, failed_ir: str, errors: list[ValidationError]
    ) -> str:
        fix_instructions = []
        for e in errors[:8]:
            instruction = _get_fix_instruction(e)
            fix_instructions.append(f"• {instruction}")
        fixes_text = "\n".join(fix_instructions)

        return f"""The LLVM IR has specific errors that need targeted fixes.

=== ORIGINAL SOURCE CODE ===
{source_code}

=== PREVIOUS IR (INVALID) ===
{failed_ir}

=== SPECIFIC ISSUES TO FIX ===
{fixes_text}

=== INSTRUCTIONS ===
1. Address each issue listed above
2. Do NOT change correct parts of the IR
3. Ensure all basic blocks have terminators after fixes
4. Verify SSA form is maintained
5. Use OPAQUE POINTERS (ptr, NOT i32*)

Output the COMPLETE fixed LLVM IR. No explanations."""

    def _regeneration_prompt(
        self, source_code: str, errors: list[ValidationError]
    ) -> str:
        categories = {}
        for e in errors:
            cat = e.category.value
            categories[cat] = categories.get(cat, 0) + 1
        summary = ", ".join(f"{cat}: {count}" for cat, count in categories.items())

        return f"""Previous attempts to generate LLVM IR for this code failed. Start fresh.

=== SOURCE CODE ===
{source_code}

=== PREVIOUS FAILURE SUMMARY ===
Error categories: {summary}

=== GENERATE FROM SCRATCH ===
Think step by step:
1. What functions and variables are needed?
2. What basic blocks are required for control flow?
3. What are ALL the alloca declarations?
4. Does every block end with a terminator (ret or br)?
5. Are all types correct (i32, double, ptr)?

Use LLVM 18 with OPAQUE POINTERS (ptr, NOT i32*).
Declare @printf: declare i32 @printf(ptr, ...)

Output ONLY complete, valid LLVM IR. No explanations."""


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Few-Shot Examples (LLVM 18, opaque pointers)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_EXAMPLE_ARITHMETIC = """=== EXAMPLE: Arithmetic ===
--- MiniLang ---
fn add(a: int, b: int): int {
    let result: int = a + b;
    return result;
}

--- LLVM IR ---
define i32 @add(i32 %a, i32 %b) {
entry:
  %a.addr = alloca i32
  %b.addr = alloca i32
  %result = alloca i32
  store i32 %a, ptr %a.addr
  store i32 %b, ptr %b.addr
  %0 = load i32, ptr %a.addr
  %1 = load i32, ptr %b.addr
  %2 = add i32 %0, %1
  store i32 %2, ptr %result
  %3 = load i32, ptr %result
  ret i32 %3
}"""

_EXAMPLE_IF_ELSE = """=== EXAMPLE: If/Else ===
--- MiniLang ---
fn max(a: int, b: int): int {
    if (a > b) {
        return a;
    } else {
        return b;
    }
}

--- LLVM IR ---
define i32 @max(i32 %a, i32 %b) {
entry:
  %a.addr = alloca i32
  %b.addr = alloca i32
  store i32 %a, ptr %a.addr
  store i32 %b, ptr %b.addr
  %0 = load i32, ptr %a.addr
  %1 = load i32, ptr %b.addr
  %cmp = icmp sgt i32 %0, %1
  br i1 %cmp, label %if.then, label %if.else
if.then:
  %2 = load i32, ptr %a.addr
  ret i32 %2
if.else:
  %3 = load i32, ptr %b.addr
  ret i32 %3
}"""

_EXAMPLE_WHILE_LOOP = """=== EXAMPLE: While Loop ===
--- MiniLang ---
fn sum_to_n(n: int): int {
    let total: int = 0;
    let i: int = 1;
    while (i <= n) {
        total = total + i;
        i = i + 1;
    }
    return total;
}

--- LLVM IR ---
define i32 @sum_to_n(i32 %n) {
entry:
  %n.addr = alloca i32
  %total = alloca i32
  %i = alloca i32
  store i32 %n, ptr %n.addr
  store i32 0, ptr %total
  store i32 1, ptr %i
  br label %while.cond
while.cond:
  %0 = load i32, ptr %i
  %1 = load i32, ptr %n.addr
  %cmp = icmp sle i32 %0, %1
  br i1 %cmp, label %while.body, label %while.end
while.body:
  %2 = load i32, ptr %total
  %3 = load i32, ptr %i
  %4 = add i32 %2, %3
  store i32 %4, ptr %total
  %5 = load i32, ptr %i
  %6 = add i32 %5, 1
  store i32 %6, ptr %i
  br label %while.cond
while.end:
  %7 = load i32, ptr %total
  ret i32 %7
}"""

_EXAMPLE_FUNCTION_CALL = """=== EXAMPLE: Function Call ===
--- MiniLang ---
fn square(x: int): int {
    return x * x;
}

fn main(): int {
    let result: int = square(7);
    print(result);
    return 0;
}

--- LLVM IR ---
@.fmt.int = private constant [4 x i8] c"%d\\0A\\00"

declare i32 @printf(ptr, ...)

define i32 @square(i32 %x) {
entry:
  %x.addr = alloca i32
  store i32 %x, ptr %x.addr
  %0 = load i32, ptr %x.addr
  %1 = load i32, ptr %x.addr
  %2 = mul i32 %0, %1
  ret i32 %2
}

define i32 @main() {
entry:
  %result = alloca i32
  %0 = call i32 @square(i32 7)
  store i32 %0, ptr %result
  %1 = load i32, ptr %result
  call i32 (ptr, ...) @printf(ptr @.fmt.int, i32 %1)
  ret i32 0
}"""


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Targeted Fix Instruction Generator
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_FIX_TEMPLATES: dict[ErrorCategory, str] = {
    ErrorCategory.SSA_VIOLATION: (
        "SSA violation: {msg}. Ensure every variable is defined via alloca+store "
        "before its first use via load. Each SSA value (%name) can only be assigned once."
    ),
    ErrorCategory.TYPE_MISMATCH: (
        "Type mismatch: {msg}. Check operand types match the instruction. "
        "Use sitofp for int→float, fptosi for float→int. int=i32, float=double."
    ),
    ErrorCategory.MISSING_TERMINATOR: (
        "Missing terminator: {msg}. Every basic block MUST end with exactly one "
        "terminator instruction (ret, br, switch, unreachable)."
    ),
    ErrorCategory.INVALID_CFG: (
        "Invalid control flow: {msg}. Ensure all branch targets reference "
        "existing basic block labels. Conditional br needs exactly two targets."
    ),
    ErrorCategory.UNDEFINED_REFERENCE: (
        "Undefined reference: {msg}. Add a 'declare' for external functions "
        "or define the missing function/global variable."
    ),
    ErrorCategory.SYNTAX_ERROR: (
        "Syntax error: {msg}. Check for malformed instructions, missing commas, "
        "or incorrect LLVM IR syntax. Use opaque pointers (ptr, NOT i32*)."
    ),
    ErrorCategory.MISSING_DECLARATION: (
        "Missing declaration: {msg}. Add 'declare i32 @printf(ptr, ...)' or "
        "similar declarations for all external functions used."
    ),
    ErrorCategory.INVALID_INSTRUCTION: (
        "Invalid instruction: {msg}. Verify the instruction name and operand "
        "count/types are correct for LLVM 18."
    ),
}


def _get_fix_instruction(error: ValidationError) -> str:
    """Convert a ValidationError into a targeted fix instruction."""
    template = _FIX_TEMPLATES.get(error.category)
    if template:
        return template.format(msg=error.message)
    return f"Fix: {error.message}"
