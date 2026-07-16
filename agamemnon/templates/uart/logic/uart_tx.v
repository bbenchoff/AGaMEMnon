module uart_tx(input wire clk, input wire start, input wire [7:0] data, output wire tx);
    reg [11:0] divider;
    reg [3:0] bits;
    reg [9:0] frame;
    reg busy;
    assign tx = busy ? frame[0] : 1'b1;
    always @(posedge clk) begin
        if (!busy && start) begin frame <= {1'b1, data, 1'b0}; bits <= 0; divider <= 0; busy <= 1; end
        else if (busy && divider == 216) begin
            divider <= 0;
            if (bits == 9) busy <= 0;
            else begin frame <= {1'b1, frame[9:1]}; bits <= bits + 1'b1; end
        end else if (busy) divider <= divider + 1'b1;
    end
endmodule
