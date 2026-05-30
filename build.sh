#!/bin/bash
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  AI-LLVM Lowering — Build Script
#  Sets up the environment, installs dependencies, verifies tools.
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "╔══════════════════════════════════════════════════╗"
echo "║  AI-LLVM Lowering Pipeline — Build Setup        ║"
echo "╚══════════════════════════════════════════════════╝"
echo ""

# ── Check Python ──────────────────────────────────────────────
PYTHON="${PYTHON:-python3}"
if ! command -v "$PYTHON" &>/dev/null; then
    echo "❌ ERROR: Python 3 not found. Install python3."
    exit 1
fi

PY_VERSION=$("$PYTHON" --version 2>&1)
echo "✓ Python: $PY_VERSION"

# ── Check minimum version (3.10+) ────────────────────────────
PY_MINOR=$("$PYTHON" -c "import sys; print(sys.version_info.minor)")
if [ "$PY_MINOR" -lt 10 ]; then
    echo "❌ ERROR: Python 3.10+ required, found $PY_VERSION"
    exit 1
fi

# ── Setup virtual environment ─────────────────────────────────
skip_venv=false
if [ ! -d "venv" ]; then
    echo ""
    echo "Creating virtual environment..."
    if "$PYTHON" -m venv venv 2>/dev/null; then
        echo "✓ Virtual environment created"
    else
        echo "⚠ python3-venv not available. Installing with --user..."
        "$PYTHON" -m pip install --user --break-system-packages \
            -r requirements.txt 2>&1 | tail -3
        echo "✓ Dependencies installed (--user mode)"
        echo ""
        echo "Note: Run with 'python3' directly (no venv activation needed)"
        skip_venv=true
    fi
fi

if [ "$skip_venv" = false ]; then
    echo "Activating virtual environment..."
    # shellcheck disable=SC1091
    source venv/bin/activate
    echo "✓ Virtual environment active"

    echo ""
    echo "Installing dependencies..."
    pip install --upgrade pip -q
    pip install -r requirements.txt -q
    echo "✓ All dependencies installed"
fi

# ── Check LLVM Tools ─────────────────────────────────────────
echo ""
echo "Checking LLVM toolchain..."

LLVM_OK=true
if command -v llvm-as &>/dev/null; then
    LLVM_AS_VER=$(llvm-as --version 2>&1 | head -2)
    echo "✓ llvm-as: $(which llvm-as)"
    echo "  $LLVM_AS_VER"
else
    echo "❌ llvm-as not found"
    echo "  Install with: sudo apt install llvm-18"
    LLVM_OK=false
fi

if command -v lli &>/dev/null; then
    echo "✓ lli:     $(which lli)"
else
    echo "❌ lli not found"
    echo "  Install with: sudo apt install llvm-18"
    LLVM_OK=false
fi

# ── Check API Keys ────────────────────────────────────────────
echo ""
echo "Checking API configuration..."

if [ -f ".env" ]; then
    echo "✓ .env file found"
elif [ -f "../.env" ]; then
    echo "✓ .env file found (parent directory)"
else
    echo "⚠ No .env file found. Copy .env.example to .env and add your API keys."
fi

# ── Create output directories ─────────────────────────────────
mkdir -p results/cache results/reports results/generated_ir
echo "✓ Output directories ready"

# ── Summary ───────────────────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════════════════╗"
if [ "$LLVM_OK" = true ]; then
    echo "║  ✅ Build complete — ready to run!              ║"
else
    echo "║  ⚠️  Build complete — LLVM tools missing        ║"
fi
echo "╚══════════════════════════════════════════════════╝"
echo ""
echo "Next steps:"
echo "  ./run.sh compile test_programs/tier1/01_arithmetic.mini"
echo "  ./run.sh evaluate test_programs/"
echo "  ./run.sh demo"
