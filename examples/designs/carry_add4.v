// Minimal dedicated-carry-chain synthesis and routing regression.
module carry_add4(
    input  wire [3:0] a,
    input  wire [3:0] b,
    output wire [4:0] y
);
    assign y = {1'b0, a} + {1'b0, b};
endmodule
