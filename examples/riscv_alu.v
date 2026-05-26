// 3-stage pipelined RISC-V ALU with carry-select adder
// Critical path per stage: ~6 logic levels (4-bit ripple + 1 mux)
module riscv_alu (
    input  wire        clk,
    input  wire        rst_n,
    input  wire [15:0] a,
    input  wire [15:0] b,
    input  wire [2:0]  op,      // 000=ADD 001=SUB 010=AND 011=OR 100=XOR 101=SLT
    output reg  [15:0] result,
    output reg         zero
);

    localparam ADD = 3'b000;
    localparam SUB = 3'b001;
    localparam AND = 3'b010;
    localparam OR  = 3'b011;
    localparam XOR = 3'b100;
    localparam SLT = 3'b101;

    // Stage 1: register inputs
    reg [15:0] a_q, b_q;
    reg [2:0]  op_q;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            a_q  <= 16'h0; b_q  <= 16'h0; op_q <= 3'b0;
        end else begin
            a_q  <= a; b_q  <= b; op_q <= op;
        end
    end

    // Stage 2: carry-select across bits [7:0] and [15:8] separately
    // Each block: 4-bit ripple carry + 1-mux = ~6 levels instead of 16-level ripple

    // Lower byte carry-select: bits [3:0] ripple, bits [7:4] pre-computed for c=0 and c=1
    wire [4:0] lo4_sum   = {1'b0, a_q[3:0]}  + {1'b0, b_q[3:0]};
    wire [4:0] lo4_diff  = {1'b0, a_q[3:0]}  - {1'b0, b_q[3:0]};
    wire [4:0] hi4_sum0  = {1'b0, a_q[7:4]}  + {1'b0, b_q[7:4]};
    wire [4:0] hi4_sum1  = {1'b0, a_q[7:4]}  + {1'b0, b_q[7:4]}  + 5'b1;
    wire [4:0] hi4_diff0 = {1'b0, a_q[7:4]}  - {1'b0, b_q[7:4]};
    wire [4:0] hi4_diff1 = {1'b0, a_q[7:4]}  - {1'b0, b_q[7:4]}  - 5'b1;
    wire [8:0] lo_sum    = {(lo4_sum[4]  ? hi4_sum1  : hi4_sum0),  lo4_sum[3:0]};
    wire [8:0] lo_diff   = {(lo4_diff[4] ? hi4_diff1 : hi4_diff0), lo4_diff[3:0]};

    // Upper byte carry-select: bits [11:8] ripple, bits [15:12] pre-computed for c=0 and c=1
    wire [4:0] lo4b_sum0  = {1'b0, a_q[11:8]}  + {1'b0, b_q[11:8]};
    wire [4:0] lo4b_sum1  = {1'b0, a_q[11:8]}  + {1'b0, b_q[11:8]}  + 5'b1;
    wire [4:0] lo4b_diff0 = {1'b0, a_q[11:8]}  - {1'b0, b_q[11:8]};
    wire [4:0] lo4b_diff1 = {1'b0, a_q[11:8]}  - {1'b0, b_q[11:8]}  - 5'b1;
    wire [4:0] hi4b_sum0  = {1'b0, a_q[15:12]} + {1'b0, b_q[15:12]};
    wire [4:0] hi4b_sum1  = {1'b0, a_q[15:12]} + {1'b0, b_q[15:12]} + 5'b1;
    wire [4:0] hi4b_diff0 = {1'b0, a_q[15:12]} - {1'b0, b_q[15:12]};
    wire [4:0] hi4b_diff1 = {1'b0, a_q[15:12]} - {1'b0, b_q[15:12]} - 5'b1;

    reg [8:0]  lo_sum_q, lo_diff_q;
    reg [4:0]  lo4b_sum0_q, lo4b_sum1_q, hi4b_sum0_q, hi4b_sum1_q;
    reg [4:0]  lo4b_diff0_q, lo4b_diff1_q, hi4b_diff0_q, hi4b_diff1_q;
    reg [15:0] and_q, or_q, xor_q;
    reg [2:0]  op_qq;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            lo_sum_q     <= 9'h0; lo_diff_q    <= 9'h0;
            lo4b_sum0_q  <= 5'h0; lo4b_sum1_q  <= 5'h0;
            hi4b_sum0_q  <= 5'h0; hi4b_sum1_q  <= 5'h0;
            lo4b_diff0_q <= 5'h0; lo4b_diff1_q <= 5'h0;
            hi4b_diff0_q <= 5'h0; hi4b_diff1_q <= 5'h0;
            and_q <= 16'h0; or_q <= 16'h0; xor_q <= 16'h0;
            op_qq <= 3'b0;
        end else begin
            lo_sum_q     <= lo_sum;  lo_diff_q    <= lo_diff;
            lo4b_sum0_q  <= lo4b_sum0;  lo4b_sum1_q  <= lo4b_sum1;
            hi4b_sum0_q  <= hi4b_sum0;  hi4b_sum1_q  <= hi4b_sum1;
            lo4b_diff0_q <= lo4b_diff0; lo4b_diff1_q <= lo4b_diff1;
            hi4b_diff0_q <= hi4b_diff0; hi4b_diff1_q <= hi4b_diff1;
            and_q <= a_q & b_q; or_q <= a_q | b_q; xor_q <= a_q ^ b_q;
            op_qq <= op_q;
        end
    end

    // Stage 3: mux upper byte using pipelined carry from lower byte (1 mux level)
    wire [4:0] lo4b_sum  = lo_sum_q[8]  ? lo4b_sum1_q  : lo4b_sum0_q;
    wire [4:0] lo4b_diff = lo_diff_q[8] ? lo4b_diff1_q : lo4b_diff0_q;
    wire [4:0] hi4b_sum  = lo4b_sum[4]  ? hi4b_sum1_q  : hi4b_sum0_q;
    wire [4:0] hi4b_diff = lo4b_diff[4] ? hi4b_diff1_q : hi4b_diff0_q;

    wire [15:0] sum  = {hi4b_sum[3:0],  lo4b_sum[3:0],  lo_sum_q[7:0]};
    wire [15:0] diff = {hi4b_diff[3:0], lo4b_diff[3:0], lo_diff_q[7:0]};
    wire [15:0] slt_out = {{15{1'b0}}, diff[15]};

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            result <= 16'h0;
            zero   <= 1'b0;
        end else begin
            case (op_qq)
                ADD: result <= sum;
                SUB: result <= diff;
                AND: result <= and_q;
                OR:  result <= or_q;
                XOR: result <= xor_q;
                SLT: result <= slt_out;
                default: result <= 16'h0;
            endcase
            zero <= (result == 16'h0);
        end
    end

endmodule
