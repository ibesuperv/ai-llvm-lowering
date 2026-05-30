# DESIGN.md — Architecture & Design Decisions

## 1. Problem Statement

Compiler lowering from high-level code to LLVM IR is traditionally done through
carefully engineered, deterministic compiler frontends. LLVM IR has strict structural
invariants that make this non-trivial:

- **SSA Form**: Every variable must be defined exactly once, before all uses
- **Typed Instructions**: Every operand has an explicit LLVM type that must be consistent
- **Control Flow Graph (CFG)**: Every basic block must end with exactly one terminator
- **Opaque Pointers (LLVM 18+)**: No more typed pointers like `i32*` — everything is `ptr`

We investigate whether an LLM can perform this lowering reliably, and where it fails.

---

## 2. Source Language — MiniLang (BNF Grammar)

```bnf
<program>      ::= <function>+
<function>     ::= "fn" IDENT "(" <params> ")" ":" <type> <block>
<params>       ::= ε | <param> ("," <param>)*
<param>        ::= IDENT ":" <type>
<type>         ::= "int" | "float" | "void" | "string" | "bool"
                 | "int" "[" "]" | "float" "[" "]"

<block>        ::= "{" <statement>* "}"
<statement>    ::= <var_decl>
                 | <assignment>
                 | <if_stmt>
                 | <while_stmt>
                 | <for_stmt>
                 | <return_stmt>
                 | <print_stmt>

<var_decl>     ::= "let" IDENT ":" <type> "=" <expr> ";"
<assignment>   ::= IDENT ("[" <expr> "]")? "=" <expr> ";"
<if_stmt>      ::= "if" "(" <expr> ")" <block> ("else" (<block> | <if_stmt>))?
<while_stmt>   ::= "while" "(" <expr> ")" <block>
<for_stmt>     ::= "for" "(" "let" IDENT ":" <type> "=" <expr> ";" <expr> ";" <assignment> ")" <block>
<return_stmt>  ::= "return" <expr>? ";"
<print_stmt>   ::= "print" "(" <expr> ")" ";"

<expr>         ::= <or_expr>
<or_expr>      ::= <and_expr> ("||" <and_expr>)*
<and_expr>     ::= <equality> ("&&" <equality>)*
<equality>     ::= <comparison> (("==" | "!=") <comparison>)*
<comparison>   ::= <additive> (("<" | ">" | "<=" | ">=") <additive>)*
<additive>     ::= <mult> (("+" | "-") <mult>)*
<mult>         ::= <unary> (("*" | "/" | "%") <unary>)*
<unary>        ::= ("!" | "-") <unary> | <primary>
<primary>      ::= INT_LITERAL | FLOAT_LITERAL | STRING_LITERAL
                 | "true" | "false"
                 | IDENT "(" <args> ")"   -- function call
                 | IDENT "[" <expr> "]"    -- array access
                 | IDENT
                 | "[" <args> "]"          -- array literal
                 | "(" <expr> ")"
<args>         ::= ε | <expr> ("," <expr>)*
```

### Tier System

The parser auto-detects the minimum complexity tier via `detect_tier()`:

| Tier | Features Added | LLVM Challenges |
|---|---|---|
| 1 | Variables, arithmetic, if/else, while, functions | `alloca/store/load`, `br`, `icmp`, function calls |
| 2 | Floats, for loops, logical ops, nesting | `double`, `fcmp`, `sitofp`, `fptosi`, loop induction |
| 3 | Arrays, recursion, strings | `getelementptr`, indirect calls, stack frames |

---

## 3. Architecture

```
┌────────────────────────────────────────────────────────────────┐
│                         CLI (main.py)                          │
│              compile │ evaluate │ demo                         │
└───────┬───────────────────┬────────────────────────────────────┘
        │                   │
        ▼                   ▼
┌──────────────┐    ┌──────────────────┐
│   PARSER     │    │    EVALUATOR     │
│  (3 modules) │    │  (runner.py)     │
│  lexer       │    │  batch over all  │
│  parser      │    │  .mini files     │
│  ast_nodes   │    └────────┬─────────┘
└──────┬───────┘             │
       │ Program AST          │
       ▼                     ▼
┌──────────────────────────────────────┐
│          REPAIR ORCHESTRATOR         │
│  1. PromptEngine.analyze_constructs  │
│  2. PromptEngine.select_strategy     │
│  3. PromptEngine.build_prompt        │
│  4. LLMClient.generate               │
│  5. IRValidator.validate_ir          │
│  6. If invalid → repair_prompt → 4  │
└──────────────────────────────────────┘
       │                   │
       ▼                   ▼
┌──────────────┐    ┌──────────────┐
│ LLM CLIENTS  │    │  VALIDATOR   │
│  Gemini      │    │  llvm-as     │
│  Groq/Llama  │    │  lli         │
│  RateLimiter │    │  classifier  │
└──────────────┘    └──────────────┘
```

---

## 4. Prompt Engineering Strategy

### Why Three Strategies?

A single prompt doesn't work well across all construct types. We select strategy
based on AST analysis:

| Construct Type | Strategy | Rationale |
|---|---|---|
| `ARITHMETIC` | Zero-Shot | Simple; LLMs reliably do arithmetic |
| `CONTROL_FLOW` | Few-Shot | Branch/loop basic blocks need concrete examples |
| `FUNCTIONS` | Few-Shot | Calling conventions need to be shown |
| `ARRAYS` | Chain-of-Thought | GEP pointer math needs step-by-step reasoning |
| `MIXED` | Chain-of-Thought | Multiple interacting concerns; need structured thinking |

### Zero-Shot
Direct instruction with detailed LLVM 18 rules. No examples. Works for simple
arithmetic where the mapping is nearly mechanical.

### Few-Shot
Provides 2–4 concrete MiniLang → LLVM IR translation examples before the actual
problem. Steers the LLM toward correct basic block structure and memory layout.

### Chain-of-Thought (CoT)
Forces the LLM to reason step-by-step through: variable declarations, type mapping,
basic block planning, SSA form, and external declarations. Uses structured markers
(`===LLVM_IR_START===`) for reliable extraction. Best for complex programs.

---

## 5. Repair Loop Design

```
Attempt 0: Initial generation (temp = 0.2)
           ↓ llvm-as failure?
Attempt 1: Simple repair — show raw errors (temp = 0.4)
           ↓ still failing?
Attempt 2: Targeted repair — categorize errors, give specific fix instructions (temp = 0.6)
           ↓ still failing?
Attempt 3: Full regeneration — start from scratch with CoT (temp = 0.8)
           ↓
      Final result (success or failure)
```

**Dynamic temperature scaling**: Higher temperature on retries encourages exploration
of different IR structures when the deterministic low-temperature path failed.

**Targeted repair**: The `ErrorCategory` classifier maps `llvm-as` stderr messages
into structured categories (SSA_VIOLATION, TYPE_MISMATCH, MISSING_TERMINATOR, etc.),
enabling category-specific fix instructions (e.g., "every block needs a terminator").

---

## 6. Validation Architecture

### Stage 1: Syntax + Semantics (llvm-as)
```bash
llvm-as -disable-output <file.ll>
```
Checks: SSA form, type consistency, instruction validity, CFG completeness, declarations.

### Stage 2: Runtime Correctness (lli)
```bash
lli <file.ll>
```
Compares stdout against the `.expected` ground-truth file.
Catches semantic errors that are syntactically valid (wrong computation, off-by-one, etc.).

### Stage 3: Error Classification (Python)
Regex-based classifier maps raw `llvm-as` stderr to one of 11 `ErrorCategory` enum values,
enabling targeted repair prompts and evaluation statistics.

---

## 7. Alternatives Considered

| Decision | Chosen | Alternative | Reason |
|---|---|---|---|
| Validation | `llvm-as` + `lli` | FileCheck | `llvm-as` gives richer error messages; `lli` confirms semantics |
| Prompt strategy | Dynamic selection | Fixed strategy | Different constructs need different approaches |
| IR target | LLVM IR | MLIR | LLVM IR has more LLM training data; richer error messages |
| Repair signal | Structured errors | Raw stderr | Structured categories enable targeted instructions |
| Temperature | Dynamic increase | Fixed | Exhausted paths need creative divergence |
| Models | Gemini + Groq free tier | GPT-4 | Cost constraint; free tiers sufficient for evaluation |
