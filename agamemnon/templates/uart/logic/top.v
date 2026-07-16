(* top *) module top(input wire clk, output wire tx);
    reg [23:0] pause;
    wire launch = pause == 0;
    always @(posedge clk) pause <= pause + 1'b1;
    uart_tx uart(.clk(clk), .start(launch), .data(8'h55), .tx(tx));
endmodule
