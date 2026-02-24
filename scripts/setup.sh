#!/usr/bin/env bash
# Setup script for the adaptive web automation engine.
#
# Usage:
#   chmod +x scripts/setup.sh
#   ./scripts/setup.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

echo "=== Adaptive Web Automation Engine — Setup ==="
echo "Project root: $PROJECT_ROOT"
echo ""

echo "[1/5] Installing Python dependencies..."
cd "$PROJECT_ROOT"
pip install -e ".[dev]"

echo ""
echo "[2/5] Installing Playwright browsers..."
python -m playwright install chromium

echo ""
echo "[3/5] Creating data directories..."
mkdir -p data/episodes data/artifacts data/

echo ""
echo "[4/5] Verifying workflow files..."
if [ -f config/workflows/naver_shopping.yaml ]; then
    echo "  Found: config/workflows/naver_shopping.yaml"
else
    echo "  WARNING: config/workflows/naver_shopping.yaml not found!"
fi

echo ""
echo "[5/5] Running tests..."
python -m pytest tests/ -v --tb=short

echo ""
echo "=== Setup complete! ==="
echo ""
echo "Next steps:"
echo "  1. Set GEMINI_API_KEY environment variable (optional, for LLM features)"
echo "  2. Run the PoC: python scripts/run_poc.py --headless"
echo "  3. Run benchmarks: python scripts/benchmark.py"
