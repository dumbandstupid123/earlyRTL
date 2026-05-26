// Act 2: Broken 64-bit ALU with ripple carry and priority encoder
// Should FAIL timing at 500MHz — logic depth 25+ levels
// Bad patterns: ripple carry adder + priority encoder feeding result mux
module riscv_alu (
    input  wire        clk,
    input  wire        rst_n,
    input  wire [63:0] a,
    input  wire [63:0] b,
    input  wire [2:0]  op,
    output reg  [63:0] result,
    output reg         zero,
    output reg  [5:0]  leading_zeros  // adds a priority encoder on the critical path
);

    localparam ADD = 3'b000;
    localparam SUB = 3'b001;
    localparam AND = 3'b010;
    localparam OR  = 3'b011;
    localparam XOR = 3'b100;
    localparam SLT = 3'b101;

    // Explicit ripple-carry adder — forces a 64-level carry chain
    wire [64:0] carry;
    wire [63:0] sum_bits;
    assign carry[0] = 1'b0;
    genvar i;
    generate
        for (i = 0; i < 64; i = i + 1) begin : ripple
            assign sum_bits[i] = a[i] ^ b[i] ^ carry[i];
            assign carry[i+1]  = (a[i] & b[i]) | (a[i] & carry[i]) | (b[i] & carry[i]);
        end
    endgenerate

    wire [63:0] diff    = a - b;
    wire [63:0] and_out = a & b;
    wire [63:0] or_out  = a | b;
    wire [63:0] xor_out = a ^ b;
    wire [63:0] slt_out = {{63{1'b0}}, diff[63]};

    // Priority encoder for leading zeros — deep combinational cone
    reg [5:0] lz;
    always @(*) begin
        lz = 6'd0;
        if      (!sum_bits[63]) lz = 6'd1;
        else if (!sum_bits[62]) lz = 6'd2;
        else if (!sum_bits[61]) lz = 6'd3;
        else if (!sum_bits[60]) lz = 6'd4;
        else if (!sum_bits[59]) lz = 6'd5;
        else if (!sum_bits[58]) lz = 6'd6;
        else if (!sum_bits[57]) lz = 6'd7;
        else if (!sum_bits[56]) lz = 6'd8;
        else if (!sum_bits[55]) lz = 6'd9;
        else if (!sum_bits[54]) lz = 6'd10;
        else if (!sum_bits[53]) lz = 6'd11;
        else if (!sum_bits[52]) lz = 6'd12;
        else if (!sum_bits[51]) lz = 6'd13;
        else if (!sum_bits[50]) lz = 6'd14;
        else if (!sum_bits[49]) lz = 6'd15;
        else if (!sum_bits[48]) lz = 6'd16;
        else if (!sum_bits[47]) lz = 6'd17;
        else if (!sum_bits[46]) lz = 6'd18;
        else if (!sum_bits[45]) lz = 6'd19;
        else if (!sum_bits[44]) lz = 6'd20;
        else if (!sum_bits[43]) lz = 6'd21;
        else if (!sum_bits[42]) lz = 6'd22;
        else if (!sum_bits[41]) lz = 6'd23;
        else if (!sum_bits[40]) lz = 6'd24;
        else if (!sum_bits[39]) lz = 6'd25;
        else if (!sum_bits[38]) lz = 6'd26;
        else if (!sum_bits[37]) lz = 6'd27;
        else if (!sum_bits[36]) lz = 6'd28;
        else if (!sum_bits[35]) lz = 6'd29;
        else if (!sum_bits[34]) lz = 6'd30;
        else if (!sum_bits[33]) lz = 6'd31;
        else                    lz = 6'd32;
    end

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            result        <= 64'h0;
            zero          <= 1'b0;
            leading_zeros <= 6'h0;
        end else begin
            case (op)
                ADD: result <= sum_bits;
                SUB: result <= diff;
                AND: result <= and_out;
                OR:  result <= or_out;
                XOR: result <= xor_out;
                SLT: result <= slt_out;
                default: result <= 64'h0;
            endcase
            zero          <= (result == 64'h0);
            leading_zeros <= lz;
        end
    end

endmodule
