# EVALUATION.md — Metrics, Comparison, and Test Cases

## 1. Evaluation Methodology

### Pipeline

Each of the 15 test programs is compiled through the full pipeline:

```
.mini source → Parser → Prompt Engine → LLM → llvm-as → lli → .expected comparison
```

### Metrics Collected

| Metric | Definition |
|---|---|
| **Pass@1** | % of programs that produce valid, correct IR on the *first* LLM attempt |
| **Final Accuracy** | % of programs that produce correct IR after up to 3 repair attempts |
| **Repair Success Rate** | % of initially-failing programs that succeed after repair |
| **Avg Repair Attempts** | Average attempts needed per successful repair |
| **Error Distribution** | Frequency of each `ErrorCategory` across all failed attempts |

### Baseline

A **naïve baseline** (zero-shot prompt with no repair, no few-shot examples) is compared
against the full pipeline (dynamic strategy selection + up to 3 repair attempts).

---

## 2. Test Cases with Ground Truth

### Tier 1 — Basic Constructs

#### TC-01: Arithmetic (`01_arithmetic.mini`)
```
Input:  add(20, 22) → print result
Output: 42
```
**LLVM Challenge**: Function call, `add i32`, `alloca`/`store`/`load` pattern.

#### TC-02: Control Flow (`02_control_flow.mini`)
```
Input:  max(10, 20), min(result, 5) → print both
Output: 20
        5
```
**LLVM Challenge**: `icmp sgt`, `icmp slt`, two-block `if.then`/`if.else` with terminators.

#### TC-03: While Loop (`03_loops.mini`)
```
Input:  sum_to_n(10) → print
Output: 55
```
**LLVM Challenge**: `while.cond`/`while.body`/`while.end` basic block structure, back-edge.

#### TC-04: Nested Functions (`04_functions.mini`)
```
Input:  math_op(2, 3, 4) = multiply(add(2,3), 4) → print
Output: 20
```
**LLVM Challenge**: Call chaining, intermediate values.

#### TC-05: Mixed Tier 1 (`05_mixed_t1.mini`)
```
Input:  count_evens(10) → print
Output: 5
```
**LLVM Challenge**: Modulo (`srem`), function call inside loop, conditional increment.

---

### Tier 2 — Extended Constructs

#### TC-06: Float Math (`06_float_math.mini`)
```
Input:  hypotenuse(3.0, 4.0) → sum of squares
Output: 25.000000
```
**LLVM Challenge**: `double` type, `fmul`, `fadd`, `%f` format string.

#### TC-07: For Loop (`07_for_loops.mini`)
```
Input:  sum_to_n(10) via for loop
Output: 55
```
**LLVM Challenge**: For loop lowered to while with induction variable update.

#### TC-08: Logical Operators (`08_logic_ops.mini`)
```
Input:  check_range(5,1,10) && check_range(15,1,10) → || → !
Output: 1
        0
```
**LLVM Challenge**: Short-circuit `&&`/`||`, `xor i1` for `!`, nested branches.

#### TC-09: Nested Control Flow (`09_nested_control.mini`)
```
Input:  find_first_divisible(10, 20, 7)
Output: 14
```
**LLVM Challenge**: for loop with early return via `ret` from inside the loop body.

#### TC-10: Mixed Tier 2 (`10_mixed_t2.mini`)
```
Input:  complex_math(1.5, 2.0, 5)
Output: 24.000000
```
**LLVM Challenge**: Float + for loop + alternating if/else inside loop.

---

### Tier 3 — Advanced Constructs

#### TC-11: Array Sum (`11_arrays.mini`)
```
Input:  sum_array([10,20,30,40,50], 5)
Output: 150
```
**LLVM Challenge**: `alloca [5 x i32]`, `getelementptr inbounds`, array literal init.

#### TC-12: Array Mutation (`12_array_loops.mini`)
```
Input:  double_elements([1,2,3,4,5]) then print_array
Output: 2
        4
        6
        8
        10
```
**LLVM Challenge**: Passing arrays as `ptr`, GEP-based mutation, void functions.

#### TC-13: Strings (`13_strings.mini`)
```
Input:  greet("World"), then escape sequences
Output: Hello, 
        World
        !
        Line 1
        Line 2  Tabbed
```
**LLVM Challenge**: String constants as `[N x i8]` globals, `%s` format, escape handling.

#### TC-14: Recursion — Fibonacci (`14_recursion.mini`)
```
Input:  fibonacci(10)
Output: 55
```
**LLVM Challenge**: Self-referential `call`, two recursive calls per invocation,
base case `ret` from conditional block.

#### TC-15: Mixed Tier 3 (`15_mixed_t3.mini`)
```
Input:  reverse_array([5,4,3,2,1]) → print original + reversed
Output: Original array:
        5 4 3 2 1
        Reversed array:
        1 2 3 4 5
```
**LLVM Challenge**: Strings + arrays + while loop + GEP-based swap, print string literals.

---

## 3. Measured Results (Llama 3.3 70B via Groq)

The following results are from actual pipeline runs using `llama-3.3-70b-versatile` via Groq API.

### Individual Test Results

| # | Program | Tier | Attempts | Result | Output Matched |
|---|---|---|---|---|---|
| TC-01 | `01_arithmetic.mini` | 1 | **1** | ✅ PASS | `42` ✓ |
| TC-14 | `14_recursion.mini` | 3 | **2** | ✅ PASS (repaired) | `55` ✓ |
| DEMO | `factorial(5)` | 3 | **1** | ✅ PASS | `120` ✓ |

### Observed Failure → Repair (TC-14 Deep Dive)

**Attempt 0 failed with `EXECUTION_ERROR`** (exit code -11, SIGSEGV):
```
target datalayout = "e-m:e-p:32:32-p270:32:32-..."  ← 32-bit pointer layout
```
The LLM generated a 32-bit pointer datalayout on a 64-bit x86_64 system.
`llvm-as` accepted it in compatibility mode, but `lli` crashed at `printf`
because pointer truncation caused a bad address.

**Repair 1 succeeded** — pipeline normalized the datalayout and re-prompted:
- `target datalayout = "e-m:e-p270:32:32-p271:32:32-p272:64:64-i64:64-..."` ✓
- Correct `fibonacci(n-1) + fibonacci(n-2)` computation ✓
- Output: `55` matched `.expected` ✓

### Pass@1 vs Final Accuracy (Observed)

| Metric | TC-01 (Tier 1) | DEMO (Tier 3) | TC-14 (Tier 3) |
|---|---|---|---|
| Pass@1 | ✅ Yes | ✅ Yes | ❌ No |
| Final | ✅ Pass | ✅ Pass | ✅ Pass (repair) |
| Repairs | 0 | 0 | 1 |

### Baseline Comparison

| Condition | Pass Rate (Observed) |
|---|---|
| **Baseline**: Attempt 0 only, no repair | 2/3 = **67%** |
| **Full pipeline**: With up to 3 repair attempts | 3/3 = **100%** |

> The repair loop rescued 1 out of 1 initially failing programs (100% repair rate).
> Run `./run.sh evaluate test_programs/` for full 15-program × 2-model batch results.

## 4. Predicted Results for Full Batch

### Most Common Failures (Hypothesis)

1. **Missing Block Terminators** (≈30% of failures)
   - LLM generates basic blocks but forgets `br label %block.end` after conditional
   - Fix: Targeted repair prompt specifically about terminators

2. **Typed Pointer Syntax** (≈25% of failures)
   - LLM generates `i32*` instead of `ptr` (LLVM 14 syntax, pre-opaque pointers)
   - Fix: Explicit "USE OPAQUE POINTERS (ptr, NOT i32*)" in every prompt

3. **Missing `declare @printf`** (≈15% of failures)
   - LLM uses `printf` without declaring it external
   - Fix: Few-shot examples always include the declaration

4. **SSA Violations** (≈10% of failures)
   - Redefining `%x` instead of using a new SSA value after `store`
   - Happens most often with complex loop bodies

5. **GEP Syntax Errors** (≈10% of failures)
   - Wrong GEP type arguments for LLVM 18 opaque pointers
   - Primarily in Tier 3 array programs

6. **Execution Mismatches** (≈10% of remaining)
   - Valid IR that runs but computes the wrong answer
   - Float precision issues (using `float` instead of `double`)

---

## 5. Repair Loop Effectiveness

The repair loop is expected to rescue 60–80% of initially failing programs:

```
Initial Failures → Attempt 1 (Simple Repair): ~50% rescued
Remaining     → Attempt 2 (Targeted Repair): ~30% rescued
Remaining     → Attempt 3 (Regeneration):    ~20% rescued
Final failures: ~10–15% of all programs
```

The biggest gains come from simple repairs (just showing the llvm-as error output),
which fixes straightforward issues like missing terminators and missing declarations.

---

## 6. How to Run the Evaluation

```bash
# Full batch evaluation (all 15 programs × all configured models)
./run.sh evaluate test_programs/

# Results saved to:
# results/reports/eval_report_<timestamp>.md  ← Markdown summary table
# results/generated_ir/                       ← All generated .ll files
```

The Markdown report includes:
- Per-model success rate table
- Error category distribution table
- Individual file results

---

## 7. Reproducing Results

All LLM responses are cached in `results/cache/` (SHA-256 keyed by source + model + strategy).
Re-running evaluation will use cached responses unless `--no-cache` is passed.

```bash
# Force fresh LLM calls (no cache)
./run.sh evaluate test_programs/ --no-cache
```
