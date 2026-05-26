"""Tests for the source mapper."""
import tempfile
import os
import pytest
from rtlsense.mapper import _parse_src_attributes, _grep_signal_in_file


SAMPLE_NETLIST = """
/* src="game_controller.v:47" */
wire collision_detected;
/* src="game_controller.v:12" */
wire [9:0] piece_mask;
/* src="riscv_alu.v:33" */
reg [15:0] result_reg;
"""

SAMPLE_VERILOG = """\
module game_controller (
    input wire clk,
    input wire [9:0] board_row,
    output reg collision
);
    reg [9:0] piece_mask;
    wire collision_detected;

    always @(posedge clk) begin
        piece_mask <= board_row & 10'hFF;
        collision  <= collision_detected;
    end

    assign collision_detected = |(piece_mask & board_row);

endmodule
"""


def test_parse_src_attributes_finds_signals():
    with tempfile.NamedTemporaryFile(mode='w', suffix='.v', delete=False) as f:
        f.write(SAMPLE_NETLIST)
        path = f.name
    try:
        mapping = _parse_src_attributes(path)
        assert "collision_detected" in mapping
        assert mapping["collision_detected"] == ("game_controller.v", 47)
        assert "piece_mask" in mapping
        assert mapping["piece_mask"] == ("game_controller.v", 12)
    finally:
        os.unlink(path)


def test_parse_src_attributes_missing_file():
    mapping = _parse_src_attributes("/nonexistent/path.v")
    assert mapping == {}


def test_grep_finds_assignment():
    with tempfile.NamedTemporaryFile(mode='w', suffix='.v', delete=False) as f:
        f.write(SAMPLE_VERILOG)
        path = f.name
    try:
        result = _grep_signal_in_file("collision_detected", path)
        assert result is not None
        _, line_no = result
        assert line_no > 0
    finally:
        os.unlink(path)


def test_grep_nonexistent_signal():
    with tempfile.NamedTemporaryFile(mode='w', suffix='.v', delete=False) as f:
        f.write(SAMPLE_VERILOG)
        path = f.name
    try:
        result = _grep_signal_in_file("nonexistent_signal_xyz", path)
        assert result is None
    finally:
        os.unlink(path)


def test_grep_missing_file():
    result = _grep_signal_in_file("any_signal", "/nonexistent/file.v")
    assert result is None
