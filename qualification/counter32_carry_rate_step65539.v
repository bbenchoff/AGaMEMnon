module top(input wire clock, output wire led);
    reg [31:0] count;
    always @(posedge clock) count <= count + 32'd65539;
    (* keep *) wire led_i;
    (* keep *) GENERIC_SLICE #(.K(4), .INIT(16'hAAAA), .FF_USED(1'b0))
        o_buf(.CLK(), .I({3'b000, count[31]}), .F(led_i), .Q());
    assign led = led_i;
endmodule
