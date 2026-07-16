(* top *) module top(input wire clk, output wire [3:0] led);
    reg [25:0] counter;
    always @(posedge clk) counter <= counter + 1'b1;
    assign led = 4'b0001 << counter[25:24];
endmodule
