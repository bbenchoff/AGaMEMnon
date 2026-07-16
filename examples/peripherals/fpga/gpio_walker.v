module ag32_gpio_walker (
    input  wire       clock,
    input  wire       reset_n,
    input  wire       step,
    output reg  [3:0] gpio
);
    always @(posedge clock) begin
        if (!reset_n)
            gpio <= 4'b0001;
        else if (step)
            gpio <= {gpio[2:0], gpio[3]};
    end
endmodule
