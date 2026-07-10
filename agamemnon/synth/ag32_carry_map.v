// AG32 carry techmap: lower yosys `$alu` (from alumacc) to a ripple chain of AG32_FA slices.
//
// The AGRV2K slice has a DEDICATED Cin/Cout hardware carry (alta_slice mode="ripple"); the abc -lut path
// otherwise shreds `+` into pure LUT4s with no carry, so a wide add/counter would route its carry through
// the partly-dead OMUX->IMUX crossbar and freeze at dense packing. This map emits one AG32_FA per result
// bit, chained COUT[i]->CIN[i+1], so the carry rides the hardware path (see ag32-dense-carry-mechanism).
//
// Handles unsigned/signed extension and the subtract (BI) form the same way the built-in `$alu` map does.
module \$alu (A, B, CI, BI, X, Y, CO);
    parameter A_SIGNED = 0;
    parameter B_SIGNED = 0;
    parameter A_WIDTH  = 1;
    parameter B_WIDTH  = 1;
    parameter Y_WIDTH  = 1;

    input  [A_WIDTH-1:0] A;
    input  [B_WIDTH-1:0] B;
    input  CI, BI;
    output [Y_WIDTH-1:0] X, Y, CO;

    // width-extend A and B to Y_WIDTH (sign- or zero-extend per *_SIGNED)
    wire [Y_WIDTH-1:0] AA = A_SIGNED ? $signed(A) : $unsigned(A);
    wire [Y_WIDTH-1:0] BE = B_SIGNED ? $signed(B) : $unsigned(B);
    wire [Y_WIDTH-1:0] BB = BI ? ~BE : BE;    // subtract: A + ~B + 1 (CI carries the +1)

    wire [Y_WIDTH:0] carry;
    assign carry[0] = CI;

    genvar i;
    generate
        for (i = 0; i < Y_WIDTH; i = i + 1) begin : fa
            AG32_FA slice (
                .A(AA[i]), .B(BB[i]), .CIN(carry[i]),
                .SUM(Y[i]), .COUT(carry[i+1])
            );
            assign X[i]  = AA[i] ^ BB[i];   // adder "propagate" term ($alu X output)
            assign CO[i] = carry[i+1];
        end
    endgenerate
endmodule
