#!/bin/bash
# RTLSense setup script: checks tools, downloads PDK, validates install
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PDK_DIR="$SCRIPT_DIR/pdk/sky130"
LIB_FILE="$PDK_DIR/sky130_fd_sc_hd__tt_025C_1v80.lib"
LIB_URL="https://raw.githubusercontent.com/RTimothyEdwards/open_pdks/master/sky130/sky130A/libs.ref/sky130_fd_sc_hd/lib/sky130_fd_sc_hd__tt_025C_1v80.lib"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

ok()   { echo -e "${GREEN}✓${NC} $1"; }
warn() { echo -e "${YELLOW}⚠${NC}  $1"; }
fail() { echo -e "${RED}✗${NC} $1"; }

echo ""
echo "RTLSense Setup"
echo "══════════════"
echo ""

# ── Check Yosys ──────────────────────────────────────────────────────────────
if command -v yosys &>/dev/null; then
    ok "Yosys found: $(yosys --version 2>&1 | head -1)"
else
    fail "Yosys not found."
    echo "  Install with: brew install yosys"
    echo "  Or: apt install yosys"
    MISSING_TOOLS=1
fi

# ── Check OpenSTA ─────────────────────────────────────────────────────────────
if command -v sta &>/dev/null; then
    ok "OpenSTA found: $(sta -version 2>&1 | head -1)"
else
    fail "OpenSTA (sta) not found."
    echo "  Build from: https://github.com/The-OpenROAD-Project/OpenSTA"
    echo "  Quick build:"
    echo "    brew install cmake swig tcl-tk eigen boost googletest"
    echo "    git clone https://github.com/The-OpenROAD-Project/OpenSTA ~/OpenSTA"
    echo "    mkdir ~/OpenSTA/build && cd ~/OpenSTA/build"
    echo "    cmake .. -DTCL_LIBRARY=/opt/homebrew/opt/tcl-tk/lib/libtcl9.0.dylib \\"
    echo "             -DTCL_HEADER=/opt/homebrew/opt/tcl-tk/include/tcl.h"
    echo "    make -j4 && sudo make install"
    MISSING_TOOLS=1
fi

# ── Check Python ──────────────────────────────────────────────────────────────
if python3 -c "import click, rich, watchdog, yaml" 2>/dev/null; then
    ok "Python packages found (click, rich, watchdog, pyyaml)"
else
    warn "Some Python packages missing. Run:"
    echo "  pip install -r requirements.txt"
fi

if [ "${MISSING_TOOLS}" = "1" ]; then
    echo ""
    fail "Missing required tools. Install them and re-run setup.sh."
    exit 1
fi

# ── Download SKY130 liberty file ──────────────────────────────────────────────
echo ""
echo "PDK Setup (SKY130)"
echo "──────────────────"
mkdir -p "$PDK_DIR"

if [ -f "$LIB_FILE" ]; then
    ok "SKY130 liberty file already present."
else
    echo "Downloading SKY130 liberty file (~15MB)..."
    if curl -fsSL "$LIB_URL" -o "$LIB_FILE"; then
        ok "SKY130 liberty file downloaded to $LIB_FILE"
    else
        warn "Primary URL failed, trying mirror..."
        MIRROR_URL="https://raw.githubusercontent.com/google/skywater-pdk-libs-sky130_fd_sc_hd/main/timing/sky130_fd_sc_hd__tt_025C_1v80.lib"
        if curl -fsSL "$MIRROR_URL" -o "$LIB_FILE"; then
            ok "SKY130 liberty file downloaded from mirror."
        else
            fail "Could not download SKY130 liberty file."
            echo "  Download manually from:"
            echo "  https://github.com/google/skywater-pdk-libs-sky130_fd_sc_hd"
            echo "  Place it at: $LIB_FILE"
            exit 1
        fi
    fi
fi

# ── Validate: synthesize a minimal AND gate ────────────────────────────────────
echo ""
echo "Validation"
echo "──────────"

TMPDIR_V=$(mktemp -d)
trap "rm -rf $TMPDIR_V" EXIT

cat > "$TMPDIR_V/test.v" << 'EOF'
module test_and (
    input  wire clk, a, b,
    output reg  y
);
    always @(posedge clk) y <= a & b;
endmodule
EOF

NETLIST="$TMPDIR_V/test_synth.v"
YS_SCRIPT="read_verilog $TMPDIR_V/test.v; hierarchy -top test_and; proc; opt; techmap; abc -liberty $LIB_FILE; stat; write_verilog $NETLIST"

if yosys -p "$YS_SCRIPT" &>/dev/null; then
    ok "Yosys synthesis: validated (AND gate synthesized)"
else
    fail "Yosys synthesis validation failed. Check liberty file path."
    exit 1
fi

TCL_SCRIPT="$TMPDIR_V/test.tcl"
cat > "$TCL_SCRIPT" << EOF
read_liberty $LIB_FILE
read_verilog $NETLIST
link_design test_and
create_clock -period 2.0 [get_ports {clk}]
report_wns
exit
EOF

if sta -no_init -no_splash -exit "$TCL_SCRIPT" &>/dev/null; then
    ok "OpenSTA timing analysis: validated"
else
    fail "OpenSTA validation failed. Check sta binary and liberty file."
    exit 1
fi

# ── Install rtlsense CLI ───────────────────────────────────────────────────────
echo ""
echo "Installing RTLSense"
echo "───────────────────"
cd "$SCRIPT_DIR"
pip install -e . -q
ok "rtlsense CLI installed (run: rtlsense --help)"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Setup complete. Run the demo:"
echo "  bash examples/demo.sh"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
