// Naive 16-bit RISC-V ALU — unoptimized, timing violations at 300MHz
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

    wire [15:0] sum     = a + b;
    wire [15:0] diff    = a - b;
    wire [15:0] and_out = a & b;
    wire [15:0] or_out  = a | b;
    wire [15:0] xor_out = a ^ b;
    wire [15:0] slt_out = {{15{1'b0}}, diff[15]};

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            result <= 16'h0;
            zero   <= 1'b0;
        end else begin
            case (op)
                ADD: result <= sum;
                SUB: result <= diff;
                AND: result <= and_out;
                OR:  result <= or_out;
                XOR: result <= xor_out;
                SLT: result <= slt_out;
                default: result <= 16'h0;
            endcase
            zero <= (result == 16'h0);
        end
    end

endmodule
