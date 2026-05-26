// Tetris game controller — clean pipelined version
// Passes at 100MHz on SKY130 (internal reg-to-reg paths are shallow)
module game_controller (
    input  wire        clk,
    input  wire        rst_n,
    input  wire [9:0]  board_row,
    input  wire [3:0]  piece_row,
    input  wire [3:0]  piece_col_pos,
    input  wire [3:0]  lines_cleared,
    output reg         collision,
    output reg  [15:0] score,
    output reg  [1:0]  fsm_state       // 2-bit one-hot: 00=IDLE 01=FALLING 10=LOCK
);

    // ── Stage 1 register: expand piece into board mask ──────────────────────
    reg [9:0] piece_mask_r;
    always @(posedge clk or negedge rst_n)
        if (!rst_n) piece_mask_r <= 10'h0;
        else        piece_mask_r <= ({6'h0, piece_row} << piece_col_pos);

    // ── Stage 2 register: collision = AND of mask and board ─────────────────
    // Reg-to-reg path: piece_mask_r → collision
    // Logic: just 10-bit AND + OR-reduce = 2 levels
    always @(posedge clk or negedge rst_n)
        if (!rst_n) collision <= 1'b0;
        else        collision <= |(piece_mask_r & board_row);

    // ── Score: lookup table (no multiply, shallow logic) ────────────────────
    // Reg-to-reg: score_delta_r → score
    reg [15:0] score_delta_r;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) score_delta_r <= 16'h0;
        else case (lines_cleared)
            4'd1:    score_delta_r <= 16'd100;
            4'd2:    score_delta_r <= 16'd300;
            4'd3:    score_delta_r <= 16'd500;
            4'd4:    score_delta_r <= 16'd800;
            default: score_delta_r <= 16'd0;
        endcase
    end

    always @(posedge clk or negedge rst_n)
        if (!rst_n) score <= 16'h0;
        else        score <= score + score_delta_r;

    // ── FSM: one-hot encoded (fast decode) ──────────────────────────────────
    localparam IDLE    = 2'b01;
    localparam FALLING = 2'b10;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) fsm_state <= IDLE;
        else case (1'b1)
            fsm_state[0]: fsm_state <= FALLING;           // IDLE → FALLING
            fsm_state[1]: fsm_state <= collision ? IDLE : FALLING; // FALLING
            default:      fsm_state <= IDLE;
        endcase
    end

endmodule
