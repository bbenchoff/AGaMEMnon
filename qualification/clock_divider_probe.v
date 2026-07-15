// Measure the configured fabric clock through a divide-by-2048 output.
module top(input wire clock, output wire divided);
    reg [15:0] counter;
    always @(posedge clock)
        counter <= counter + 1'b1;
    assign divided = counter[10];
endmodule
