# AI-Assisted Lowering from High-Level Code to LLVM IR

> Assignment 15 — Compiler Design | CS Project

A research pipeline that investigates whether a Large Language Model can reliably
translate high-level source code into LLVM IR, validates the output using the real
LLVM toolchain (`llvm-as` + `lli`), and automatically repairs failures through a
structured feedback loop.

---

## 📑 Documentation

| Document                                   | Contents                                                                                                      |
| ------------------------------------------ | ------------------------------------------------------------------------------------------------------------- |
| **[README.md](README.md)** ← you are here  | What the project is, how to run it                                                                            |
| **[DESIGN.md](DESIGN.md)**                 | Architecture, MiniLang grammar, prompt strategies, repair loop design, alternatives considered                |
| **[IMPLEMENTATION.md](IMPLEMENTATION.md)** | LLVM IR type mapping, alloca/store/load pattern, CFG block structure, GEP arrays, recursion, error categories |
| **[EVALUATION.md](EVALUATION.md)**         | 15 test cases with ground-truth, measured results, baseline vs pipeline comparison, failure mode analysis     |
| **[demo/README.md](demo/README.md)**       | Video demo link, sample generated IR files explained                                                          |

📹 **[Demo Video — Google Drive](https://drive.google.com/file/d/18xPuBdeGLbQfWNEWaexRLVaM-WNsy-nn/view?usp=sharing)**

---

## How It Works

```
MiniLang Source (.mini)
        │
        ▼
  Lexer / Parser  ───────────►  Tier-Aware AST  (Tier 1 / 2 / 3)
        │
        ▼
  Prompt Engine  ────────────►  Zero-Shot / Few-Shot / Chain-of-Thought
        │
        ▼
  LLM (Gemini 2.0 Flash / Llama 3.3 70B)  ──►  Generated LLVM IR
        │
        ▼
  llvm-as  ──────────────────►  Structural check (SSA, types, CFG, terminators)
        │
        ▼
  lli (JIT execute)  ─────────►  Semantic check (stdout vs .expected file)
        │
       Fail? ──► Repair Orchestrator ──► Re-prompt (max 3×) ──► Re-validate
        │
        ▼
  ✅ Pass  /  ❌ Categorized failure log
```

---

## Prerequisites

### 1 — Operating System

**WSL (Ubuntu)** or native Linux. The pipeline uses Linux LLVM tools.

On Windows, open **WSL terminal** for all commands below.

---

### 2 — Install LLVM 18

```bash
sudo apt update
sudo apt install -y llvm-18 lld-18

# Verify installation
llvm-as-18 --version    # should print: LLVM version 18.x.x
lli-18 --version        # should print: LLVM version 18.x.x
```

If LLVM 18 installs to `llvm-as-18` / `lli-18` instead of `llvm-as` / `lli`, create symlinks:

```bash
sudo ln -sf /usr/bin/llvm-as-18 /usr/bin/llvm-as
sudo ln -sf /usr/bin/lli-18     /usr/bin/lli
```

Then verify:

```bash
llvm-as --version   # LLVM version 18.x.x ✓
lli --version       # LLVM version 18.x.x ✓
```

---

### 3 — Get API Keys (Free, No Credit Card)

You need **at least one** of these:

#### Option A — Google Gemini (15 req/min free)

1. Go to **[aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey)**
2. Sign in with Google → click **Create API Key**
3. Copy the key (starts with `AIza...`)

#### Option B — Groq / Llama 3.3 70B (30 req/min free) — **Recommended if Gemini quota runs out**

1. Go to **[console.groq.com](https://console.groq.com/)**
2. Sign up → go to **API Keys** → click **Create API Key**
3. Copy the key (starts with `gsk_...`)

> **Tip**: Get both. Gemini has a daily token limit on free tier. When it runs out, switch to Groq with `--model llama-3.3-70b-versatile`.

---

## Setup & Run

### Step 1 — Clone the repo

```bash
git clone https://github.com/YOUR_USERNAME/ai-llvm-lowering.git
cd ai-llvm-lowering
```

---

### Step 2 — Configure API keys

```bash
# Copy the template
cp .env.example .env

# Open and fill in your keys
nano .env
```

Edit `.env` to look like this:

```env
# Paste your Gemini key here (or leave blank to skip)
GEMINI_API_KEY=AIzaSy...your_key_here...

# Paste your Groq key here (or leave blank to skip)
GROQ_API_KEY=gsk_...your_key_here...

# LLVM paths — change only if llvm-as/lli are not in /usr/bin
LLVM_AS_PATH=/usr/bin/llvm-as
LLI_PATH=/usr/bin/lli
```

Save with `Ctrl+O`, `Enter`, `Ctrl+X`.

> ⚠️ **Never commit your `.env` file.** It is in `.gitignore` by default.

---

### Step 3 — Build

```bash
chmod +x build.sh run.sh
./build.sh
```

This will:

- ✅ Create `venv/` (Python virtual environment)
- ✅ Install all Python packages from `requirements.txt`
- ✅ Check that `llvm-as` and `lli` are working
- ✅ Create `results/generated_ir/` and `results/reports/` directories

**Expected output:**

```
[build] Creating virtual environment...
[build] Installing Python dependencies...
[build] Verifying LLVM tools...
  llvm-as: /usr/bin/llvm-as  ✓
  lli:     /usr/bin/lli       ✓
[build] Build complete. Run ./run.sh to start.
```

If you see `llvm-as: not found`, check the [LLVM setup](#2--install-llvm-18) section above.

---

### Step 4 — Run

#### 4a. Quick demo — factorial(5) = 120

```bash
# With Gemini (default)
./run.sh demo

# With Groq/Llama (if Gemini quota exceeded)
./run.sh demo --model llama-3.3-70b-versatile
```

#### 4b. Compile a single MiniLang file

```bash
# Tier 1 — arithmetic (typically passes first attempt)
./run.sh compile test_programs/tier1/01_arithmetic.mini

# Tier 3 — fibonacci recursion (shows repair loop)
./run.sh compile test_programs/tier3/14_recursion.mini

# Use a specific model
./run.sh compile test_programs/tier2/07_for_loops.mini --model llama-3.3-70b-versatile
```

The generated IR is saved to `results/generated_ir/<filename>.ll`.

#### 4c. Batch evaluation — all 15 test programs

```bash
./run.sh evaluate test_programs/
```

> ⚠️ Takes 10–20 minutes. Runs all `.mini` files against all configured models.  
> Report saved to `results/reports/eval_report_<timestamp>.md`

#### 4d. Run unit tests

```bash
# Inside WSL
venv/bin/python3 -m pytest tests/ -v
# Expected: 48 passed
```

---

## LLVM Path Troubleshooting

| Problem                       | Fix                                                                                |
| ----------------------------- | ---------------------------------------------------------------------------------- |
| `llvm-as: not found`          | `sudo apt install llvm-18` then `sudo ln -sf /usr/bin/llvm-as-18 /usr/bin/llvm-as` |
| `lli: not found`              | `sudo ln -sf /usr/bin/lli-18 /usr/bin/lli`                                         |
| `llvm-as` is version 14 or 15 | Uninstall old version: `sudo apt remove llvm-14`, reinstall LLVM 18                |
| Wrong path in `.env`          | Run `which llvm-as` and update `LLVM_AS_PATH` in `.env`                            |

---

## Available Models

| Model ID                  | Provider | Flag                              | Free Tier             |
| ------------------------- | -------- | --------------------------------- | --------------------- |
| `gemini-2.0-flash`        | Google   | _(default)_                       | 15 RPM, 1M tokens/day |
| `llama-3.3-70b-versatile` | Groq     | `--model llama-3.3-70b-versatile` | 30 RPM, no daily cap  |

---

## Project Structure

```
ai-llvm-lowering/
├── build.sh                    # Step 1: sets up environment
├── run.sh                      # Step 2: runs the pipeline
├── .env.example                # API key template → copy to .env
├── requirements.txt            # Python dependencies
│
├── src/
│   ├── main.py                 # CLI entry point (click)
│   ├── config.py               # Reads .env, configures models
│   ├── types.py                # Shared enums: LanguageTier, ErrorCategory, etc.
│   │
│   ├── parser/                 # MiniLang frontend
│   │   ├── lexer.py            # Tokenizer
│   │   ├── parser.py           # Recursive descent parser + tier detection
│   │   └── ast_nodes.py        # AST node dataclasses
│   │
│   ├── llm/                    # LLM translation layer
│   │   ├── gemini_client.py    # Google Gemini (google-genai SDK)
│   │   ├── groq_client.py      # Groq/Llama via OpenAI-compatible API
│   │   ├── prompt_engine.py    # Zero-shot / few-shot / CoT prompt builder
│   │   └── base_client.py      # Shared: rate limiter, IR extraction, normalization
│   │
│   ├── validator/
│   │   ├── validator.py        # Runs llvm-as + lli, compares output
│   │   └── classifier.py       # Maps llvm-as stderr → ErrorCategory enum
│   │
│   ├── repair/
│   │   └── orchestrator.py     # Generate → Validate → Repair loop (max 3×)
│   │
│   └── evaluator/
│       └── runner.py           # Batch runner + Markdown report generator
│
├── test_programs/
│   ├── tier1/                  # 5 programs: arithmetic, if/else, while, functions
│   ├── tier2/                  # 5 programs: floats, for loops, logical ops
│   └── tier3/                  # 5 programs: arrays, recursion, strings
│       ├── *.mini              # MiniLang source
│       └── *.expected          # Ground-truth stdout for lli comparison
│
├── tests/                      # 48 pytest unit tests
├── demo/                       # Sample generated IR files + video link
│
├── DESIGN.md                   # → Architecture, grammar, design decisions
├── IMPLEMENTATION.md           # → LLVM details, type mapping, error categories
└── EVALUATION.md               # → Test cases, measured results, failure analysis
```

---

## Test Programs (15 total, ≥5 per tier)

| #   | File                           | Tier | Constructs                       | Expected Output |
| --- | ------------------------------ | ---- | -------------------------------- | --------------- |
| 01  | `tier1/01_arithmetic.mini`     | 1    | Functions, `add i32`             | `42`            |
| 02  | `tier1/02_control_flow.mini`   | 1    | `if/else`, `icmp`                | `20`, `5`       |
| 03  | `tier1/03_loops.mini`          | 1    | `while`, back-edge               | `55`            |
| 04  | `tier1/04_functions.mini`      | 1    | Nested calls                     | `20`            |
| 05  | `tier1/05_mixed_t1.mini`       | 1    | Modulo (`srem`)                  | `5`             |
| 06  | `tier2/06_float_math.mini`     | 2    | `double`, `fmul`                 | `25.000000`     |
| 07  | `tier2/07_for_loops.mini`      | 2    | `for` → while                    | `55`            |
| 08  | `tier2/08_logic_ops.mini`      | 2    | `&&`, `\|\|`, `!`                | `1`, `0`        |
| 09  | `tier2/09_nested_control.mini` | 2    | Nested for+if, early `ret`       | `14`            |
| 10  | `tier2/10_mixed_t2.mini`       | 2    | Float + for + if                 | `24.000000`     |
| 11  | `tier3/11_arrays.mini`         | 3    | `getelementptr`, array sum       | `150`           |
| 12  | `tier3/12_array_loops.mini`    | 3    | Array mutation, `ptr` passing    | `2 4 6 8 10`    |
| 13  | `tier3/13_strings.mini`        | 3    | `[N x i8]` globals, `%s`         | `Hello, World!` |
| 14  | `tier3/14_recursion.mini`      | 3    | Recursive fibonacci, repair demo | `55`            |
| 15  | `tier3/15_mixed_t3.mini`       | 3    | Arrays + strings + while         | reversed array  |

Each `.expected` file contains the exact ground-truth stdout. `lli` must match it for a semantic pass.

---

## Key Results

| Condition                            | Pass Rate |
| ------------------------------------ | --------- |
| Baseline (attempt 0 only, no repair) | **67%**   |
| Full pipeline (with up to 3 repairs) | **100%**  |

See **[EVALUATION.md](EVALUATION.md)** for full breakdown including the fibonacci repair case deep-dive.

---

## Team

| Member   | Contribution                                                |
| -------- | ----------------------------------------------------------- |
| Member 1 | MiniLang grammar, Lexer, Parser, Tier detection             |
| Member 2 | LLM clients, Prompt Engine (3 strategies), Rate limiting    |
| Member 3 | Validator, Repair Orchestrator, Evaluator, IR normalization |
