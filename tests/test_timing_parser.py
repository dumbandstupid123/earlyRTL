"""Tests for the OpenSTA timing report parser."""
import pytest
from rtlsense.timing import _parse_report, _parse_path_block


SAMPLE_PATH_BLOCK = """
Startpoint: reg_a (rising edge-triggered flip-flop clocked by clk)
Endpoint: reg_b (rising edge-triggered flip-flop clocked by clk)
Path Group: clk
Path Type: max

  Delay    Time   Description
---------------------------------------------------------
   0.0000  0.0000 clock clk (rise edge)
   0.1200  0.1200 ^ reg_a/CK (sky130_fd_sc_hd__dfxtp_1)
   0.3500  0.4700 ^ and2/A (sky130_fd_sc_hd__and2_1)
   0.1800  0.6500 ^ and2/X (sky130_fd_sc_hd__and2_1)
   0.2200  0.8700 ^ or2/A (sky130_fd_sc_hd__or2_1)
   0.1900  1.0600 ^ or2/X (sky130_fd_sc_hd__or2_1)
   1.0600           data arrival time

   2.0000  2.0000 clock period
  -0.2000  1.8000 output delay
   1.8000          data required time
---------------------------------------------------------
   1.8000          data required time
  -1.0600          data arrival time
   0.7400          slack (MET)
"""

SAMPLE_VIOLATION_BLOCK = """
Startpoint: carry_reg (rising edge-triggered flip-flop clocked by clk)
Endpoint: result_reg (rising edge-triggered flip-flop clocked by clk)
Path Group: clk
Path Type: max

  Delay    Time   Description
---------------------------------------------------------
   0.0000  0.0000 clock clk (rise edge)
   0.1200  0.1200 ^ carry_reg/CK (sky130_fd_sc_hd__dfxtp_1)
   0.4100  0.5300 ^ add0/X (sky130_fd_sc_hd__fa_1)
   0.4100  0.9400 ^ add1/X (sky130_fd_sc_hd__fa_1)
   0.4100  1.3500 ^ add2/X (sky130_fd_sc_hd__fa_1)
   0.4100  1.7600 ^ add3/X (sky130_fd_sc_hd__fa_1)
   0.4100  2.1700 ^ add4/X (sky130_fd_sc_hd__fa_1)
   2.1700           data arrival time

   2.0000  2.0000 clock period
  -0.2000  1.8000 output delay
   1.8000          data required time
---------------------------------------------------------
   1.8000          data required time
  -2.1700          data arrival time
  -0.3700          slack (VIOLATED)
"""

SAMPLE_REPORT = SAMPLE_PATH_BLOCK + "\n" + SAMPLE_VIOLATION_BLOCK + """
wns -0.3700
tns -0.3700
"""


def test_parse_met_path():
    path = _parse_path_block(SAMPLE_PATH_BLOCK)
    assert path is not None
    assert path.startpoint == "reg_a"
    assert path.endpoint == "reg_b"
    assert path.path_delay == pytest.approx(1.06, abs=0.01)
    assert path.slack == pytest.approx(0.74, abs=0.01)
    assert not path.is_violation


def test_parse_violated_path():
    path = _parse_path_block(SAMPLE_VIOLATION_BLOCK)
    assert path is not None
    assert path.startpoint == "carry_reg"
    assert path.endpoint == "result_reg"
    assert path.slack == pytest.approx(-0.37, abs=0.01)
    assert path.is_violation


def test_parse_full_report_wire_factor():
    paths, wns, tns = _parse_report(SAMPLE_REPORT, wire_factor=1.4, clock_period_ns=2.0)
    assert len(paths) == 2

    # Met path: adjusted delay = 1.06 * 1.4 = 1.484; slack = 1.8 - 1.484 = 0.316
    met = next(p for p in paths if p.startpoint == "reg_a")
    assert met.adjusted_delay == pytest.approx(1.06 * 1.4, abs=0.05)

    # Violated path: adjusted delay = 2.17 * 1.4 = 3.038; slack = 1.8 - 3.038 = -1.238
    violated = next(p for p in paths if p.startpoint == "carry_reg")
    assert violated.slack < 0
    assert violated.is_violation


def test_wns_is_negative_on_violation():
    _, wns, _ = _parse_report(SAMPLE_REPORT, wire_factor=1.0, clock_period_ns=2.0)
    assert wns < 0


def test_no_paths_on_empty_report():
    paths, wns, tns = _parse_report("", wire_factor=1.4, clock_period_ns=2.0)
    assert paths == []
    assert wns == 0.0
    assert tns == 0.0
