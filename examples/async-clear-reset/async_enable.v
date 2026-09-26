// Independent release holdout: ordinary async reset plus conditional updates.
// The MSB has one rising edge per 8192 input clocks after reset release.
module async_enable(input clock, input reset, output led);
    reg phase;
    reg [11:0] count;
    always @(posedge clock or posedge reset) begin
        if (reset) begin
            phase <= 1'b0;
            count <= 12'd0;
        end else begin
            phase <= ~phase;
            if (phase) count <= count + 12'd1;
        end
    end
    assign led = count[11];
endmodule
