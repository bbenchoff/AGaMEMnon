module ag32_timer_tick #(
    parameter integer DIVISOR = 25_000_000
) (
    input  wire clock,
    input  wire reset_n,
    input  wire enable,
    output reg  tick
);
    reg [31:0] count;

    always @(posedge clock) begin
        if (!reset_n) begin
            count <= 0;
            tick <= 0;
        end else begin
            tick <= 0;
            if (!enable)
                count <= 0;
            else if (count == DIVISOR - 1) begin
                count <= 0;
                tick <= 1;
            end else
                count <= count + 1'b1;
        end
    end
endmodule
