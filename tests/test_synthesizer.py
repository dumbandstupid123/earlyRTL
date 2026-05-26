"""Tests for the Yosys output parser (no subprocess needed)."""
import pytest
from rtlsense.synthesizer import _parse_yosys_output, _extract_module_names


SAMPLE_YOSYS_OUTPUT = """
...
=== test_and ===

   Number of wires:                  4
   Number of wire bits:              4
   Number of public wires:           4
   Number of public wire bits:       4
   Number of memories:               0
   Number of memory bits:            0
   Number of processes:              0
   Number of cells:                 12
     sky130_fd_sc_hd__and2_1         3
     sky130_fd_sc_hd__dfxtp_1        1
     sky130_fd_sc_hd__buf_1          8

   Chip area for module '\\test_and': 47.432800

ABC: Delay =  250.00 (=   2 lev)
ABC: Area  =   47.43 (=   12 cells)
Levels = 2
"""


def test_parse_cell_count():
    cell_count, _, _ = _parse_yosys_output(SAMPLE_YOSYS_OUTPUT)
    assert cell_count == 12


def test_parse_cell_area():
    _, cell_area, _ = _parse_yosys_output(SAMPLE_YOSYS_OUTPUT)
    assert cell_area == pytest.approx(47.432800, abs=0.01)


def test_parse_logic_levels():
    _, _, logic_levels = _parse_yosys_output(SAMPLE_YOSYS_OUTPUT)
    assert logic_levels == 2


def test_parse_empty_output():
    cell_count, cell_area, logic_levels = _parse_yosys_output("")
    assert cell_count == 0
    assert cell_area == 0.0
    assert logic_levels == 0


def test_extract_module_names_simple():
    verilog = """
module my_adder (
    input wire a, b,
    output reg y
);
endmodule

module my_mux (input wire sel, a, b, output wire y);
endmodule
"""
    modules = _extract_module_names(verilog)
    assert "my_adder" in modules
    assert "my_mux" in modules
    assert len(modules) == 2


def test_extract_module_names_empty():
    assert _extract_module_names("// just a comment") == []


def test_extract_module_names_parameterized():
    verilog = "module my_fifo #(parameter WIDTH=8) (input clk);"
    modules = _extract_module_names(verilog)
    assert "my_fifo" in modules
