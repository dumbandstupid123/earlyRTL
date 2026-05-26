#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/.."

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  RTLSense Demo: Three-Act Play"
echo "  ESLint for chip design -- real synthesis, real timing"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

echo "--- Act 1: The Baseline ---"
echo "Analyzing RISC-V ALU (16-bit, should PASS at 100MHz on SKY130)..."
echo ""
rtlsense check examples/riscv_alu.v --clock 100MHz
echo ""

echo "--- Act 2: The Error ---"
echo "Analyzing modified ALU (64-bit ripple carry + priority encoder)..."
echo "Watch the logic depth explode and timing fail hard."
echo ""
rtlsense check examples/riscv_alu_bad.v --clock 100MHz
echo ""

echo "--- Act 3: The Insight ---"
echo "Diff: exactly what did the change do to timing?"
echo ""
rtlsense diff examples/riscv_alu.v examples/riscv_alu_bad.v --clock 100MHz
echo ""

echo "--- Bonus: Tetris ASIC ---"
echo "Three simultaneous regressions in one commit..."
echo ""
rtlsense diff examples/game_controller_v1.v examples/game_controller_v2.v --clock 100MHz
echo ""

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Demo complete. Try: rtlsense watch ./examples/ --clock 100MHz"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
