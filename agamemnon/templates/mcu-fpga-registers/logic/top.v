(* top *) module top(input wire clk);
    reg [3:0] count;
    wire [3:0] read_data;
    always @(posedge clk) count <= count + 1'b1;
    assign read_data = count;
    MCU_DOUT d0(.DOUT(read_data[0]));
    MCU_DOUT d1(.DOUT(read_data[1]));
    MCU_DOUT d2(.DOUT(read_data[2]));
    MCU_DOUT d3(.DOUT(read_data[3]));
endmodule
