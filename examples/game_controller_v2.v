// Tetris game controller — broken version with three timing regressions
// Fails at 100MHz because of deep combinational cones in internal paths
module game_controller (
    input  wire        clk,
    input  wire        rst_n,
    input  wire [9:0]  board_row,
    input  wire [3:0]  piece_row,
    input  wire [3:0]  piece_col_pos,
    input  wire [3:0]  lines_cleared,
    output reg         collision,
    output reg  [15:0] score,
    output reg  [1:0]  fsm_state
);

    // ── Regression 1: collision detection is now combinational (no pipeline) ─
    // Removed piece_mask_r register — full cone from input to collision FF.
    // Path: board_row → shift → AND → OR-reduce → collision
    // was 2 levels (reg-to-reg); now it's deeper and input-constrained.
    wire [9:0] piece_mask = ({6'h0, piece_row} << piece_col_pos);
    always @(posedge clk or negedge rst_n)
        if (!rst_n) collision <= 1'b0;
        else        collision <= |(piece_mask & board_row);

    // ── Regression 2: 8-bit ripple-carry multiply in the scoring path ────────
    // score_delta = lines_cleared * 100  (8×8 ripple multiply = ~24 levels)
    // This is a deep reg-to-reg path: score → score through the multiplier.
    // The naive * operator synthesizes to a shift-add tree; with -O0 in abc
    // Yosys leaves it as a ripple multiplier.
    wire [15:0] score_delta = {12'h0, lines_cleared} * 16'd100;

    always @(posedge clk or negedge rst_n)
        if (!rst_n) score <= 16'h0;
        else        score <= score + score_delta;  // adder follows multiplier

    // ── Regression 3: binary FSM encoding (deeper state decode than one-hot) ─
    // In one-hot: fsm_state[1] is a single wire.
    // In binary:  "state == FALLING" needs a 2-input comparator.
    localparam IDLE    = 2'b00;
    localparam FALLING = 2'b01;
    localparam LOCK    = 2'b10;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) fsm_state <= IDLE;
        else case (fsm_state)
            IDLE:    fsm_state <= FALLING;
            FALLING: fsm_state <= collision ? LOCK : FALLING;
            LOCK:    fsm_state <= IDLE;
            default: fsm_state <= IDLE;
        endcase
    end

endmodule
