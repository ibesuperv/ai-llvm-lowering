# IMPLEMENTATION.md — LLVM IR Implementation Details

## 1. LLVM IR Target: Version 18 with Opaque Pointers

All generated IR targets **LLVM 18** with **opaque pointers** (`ptr` instead of `i32*`).
This is a breaking change from LLVM 14 and earlier — prompts explicitly instruct the LLM
to use `ptr` everywhere.

---

## 2. Type Mapping: MiniLang → LLVM IR

| MiniLang | LLVM IR | Notes |
|---|---|---|
| `int` | `i32` | 32-bit signed integer |
| `float` | `double` | 64-bit IEEE 754 (not `float`/`f32`) |
| `bool` | `i1` | 1-bit integer; produced by `icmp`/`fcmp` |
| `void` | `void` | Return type only |
| `string` | `ptr` | Pointer to `[N x i8]` constant global |
| `int[]` | `ptr` | Pointer to heap/stack array allocation |
| `float[]` | `ptr` | Same |

**Key decision**: Using `double` for `float` avoids precision-related mismatches
and is what most LLMs default to when generating floating-point IR.

---

## 3. Memory Model: alloca/store/load Pattern

All mutable local variables use the standard SSA-compatible memory pattern:

```llvm
; MiniLang: let x: int = 42;
%x = alloca i32          ; allocate stack slot
store i32 42, ptr %x     ; initialize

; MiniLang: x = x + 1;
%0 = load i32, ptr %x    ; read current value
%1 = add i32 %0, 1       ; compute new value
store i32 %1, ptr %x     ; write back
```

**Why not direct SSA values for everything?** Because MiniLang allows mutable variables
(reassignment). Using `alloca` avoids the need for `phi` nodes and is what `clang -O0`
generates — it's what LLMs are most trained on.

---

## 4. Control Flow: Basic Blocks

### if/else

```llvm
; MiniLang: if (a > b) { ... } else { ... }
%cmp = icmp sgt i32 %a_val, %b_val
br i1 %cmp, label %if.then, label %if.else

if.then:
  ; then body
  br label %if.end       ← REQUIRED terminator

if.else:
  ; else body  
  br label %if.end       ← REQUIRED terminator

if.end:
  ; continuation
```

**Common LLM failure**: Forgetting the `br label %if.end` terminator — each block
must end with *exactly one* terminator. The `MISSING_TERMINATOR` category catches this.

### while loop

```llvm
; MiniLang: while (i <= n) { ... }
  br label %while.cond

while.cond:
  %cond = icmp sle i32 %i_val, %n_val
  br i1 %cond, label %while.body, label %while.end

while.body:
  ; loop body
  br label %while.cond   ← back-edge

while.end:
  ; post-loop
```

### for loop (lowered as while)

The `for (let i: int = 0; i < n; i = i + 1)` construct is lowered identically
to while with the init before the loop and update inside the body.

---

## 5. Function Calls and Calling Convention

```llvm
; MiniLang: let result: int = add(x, y);
; Generates:
%x_val = load i32, ptr %x
%y_val = load i32, ptr %y
%result_val = call i32 @add(i32 %x_val, i32 %y_val)
store i32 %result_val, ptr %result
```

Parameters are passed by value. The callee receives fresh `i32` values — not pointers.
Arrays are passed as `ptr` (base pointer only; size passed separately as `int`).

---

## 6. print() — Runtime Output via printf

MiniLang's `print()` is lowered to `printf` with format strings:

```llvm
; Global format strings (declared once per module)
@.fmt.int   = private constant [4 x i8] c"%d\0A\00"   ; "%d\n"
@.fmt.float = private constant [10 x i8] c"%f\0A\00"  ; "%f\n"
@.fmt.str   = private constant [4 x i8] c"%s\0A\00"   ; "%s\n"

; External declaration
declare i32 @printf(ptr, ...)

; print(x) where x: int
%x_val = load i32, ptr %x
call i32 (ptr, ...) @printf(ptr @.fmt.int, i32 %x_val)
```

---

## 7. Arrays: GEP (GetElementPointer)

```llvm
; MiniLang: let nums: int[] = [10, 20, 30];
; Lowered as stack allocation:
%nums = alloca [3 x i32]
%p0 = getelementptr inbounds [3 x i32], ptr %nums, i32 0, i32 0
store i32 10, ptr %p0
%p1 = getelementptr inbounds [3 x i32], ptr %nums, i32 0, i32 1
store i32 20, ptr %p1
; ...

; MiniLang: arr[i] = arr[i] * 2;
%i_val = load i32, ptr %i
%elem_ptr = getelementptr inbounds i32, ptr %arr, i32 %i_val
%elem_val = load i32, ptr %elem_ptr
%doubled = mul i32 %elem_val, 2
store i32 %doubled, ptr %elem_ptr
```

**Common LLM failure**: Using typed GEP syntax (`[N x i32]*`) instead of `ptr` with
LLVM 18 opaque pointers — classified as `SYNTAX_ERROR` or `TYPE_MISMATCH`.

---

## 8. Strings: Constant Globals

```llvm
; MiniLang: let s: string = "Hello";
@.str.0 = private constant [6 x i8] c"Hello\00"

; MiniLang: print(s);
call i32 (ptr, ...) @printf(ptr @.fmt.str, ptr @.str.0)
```

---

## 9. Recursion

Recursive functions work naturally since LLVM IR supports direct recursion.
The key is that each recursive call allocates a new stack frame via `alloca`s in
the callee's `entry` block.

```llvm
; MiniLang: return fibonacci(n-1) + fibonacci(n-2);
%n_val = load i32, ptr %n.addr
%n_minus_1 = sub i32 %n_val, 1
%fib1 = call i32 @fibonacci(i32 %n_minus_1)
%n_minus_2 = sub i32 %n_val, 2
%fib2 = call i32 @fibonacci(i32 %n_minus_2)
%sum = add i32 %fib1, %fib2
ret i32 %sum
```

---

## 10. IR Extraction from LLM Responses

LLMs return IR in various formats. The `extract_ir_from_response()` function tries:

1. **Custom markers**: `===LLVM_IR_START=== ... ===LLVM_IR_END===` (used in CoT prompts)
2. **Fenced code blocks**: ` ```llvm `, ` ```ir `, ` ```ll `, ` ``` `
3. **Raw IR detection**: Lines starting with LLVM IR keywords (`define`, `declare`, `@`, `;`)
4. **Fallback**: Return entire response (validator will report as invalid)

---

## 11. Module-Level Code Map

| Module | Key Class / Function | Responsibility |
|---|---|---|
| `parser/lexer.py` | `Lexer.tokenize()` | Tokenize MiniLang source into `Token` stream |
| `parser/parser.py` | `Parser.parse()` | Build AST; `_walk_ast()` for depth-first traversal |
| `parser/parser.py` | `Parser.detect_tier()` | Classify program into Tier 1/2/3 |
| `llm/prompt_engine.py` | `PromptEngine.analyze_constructs()` | Walk AST → `ConstructType` |
| `llm/prompt_engine.py` | `PromptEngine.build_generation_prompt()` | Select and build prompt |
| `llm/gemini_client.py` | `GeminiClient.generate()` | Call Gemini API with rate limiting |
| `llm/groq_client.py` | `GroqClient.generate()` | Call Groq API with rate limiting |
| `validator/validator.py` | `IRValidator.validate_ir()` | Run llvm-as + lli, compare output |
| `validator/classifier.py` | `classify_llvm_error()` | Map stderr → `ErrorCategory` |
| `repair/orchestrator.py` | `RepairOrchestrator.run_task()` | Full generate→validate→repair loop |
| `evaluator/runner.py` | `Evaluator.run_evaluation()` | Batch evaluation + Markdown report |

---

## 12. Error Categories Implemented

| Category | Detection | Example |
|---|---|---|
| `SSA_VIOLATION` | "multiple definition", "does not dominate" | Reusing `%x` for two different values |
| `TYPE_MISMATCH` | "type mismatch", "invalid operand types" | Adding `i32` and `double` directly |
| `MISSING_TERMINATOR` | "does not have terminator" | Block missing `ret` or `br` |
| `INVALID_CFG` | "undefined block", "branch target" | `br` to non-existent label |
| `MISSING_DECLARATION` | "undefined value", "use of undefined" | Using `@printf` without `declare` |
| `INVALID_INSTRUCTION` | "invalid instruction", "unknown instruction" | Wrong mnemonic or operand count |
| `SYNTAX_ERROR` | "expected", "unexpected token" | Malformed IR, wrong types syntax |
| `EXECUTION_MISMATCH` | stdout ≠ `.expected` file | Semantically wrong computation |
| `EXECUTION_ERROR` | lli non-zero exit code | Runtime crash, division by zero |
| `UNKNOWN` | Fallback | Unrecognized error format |
