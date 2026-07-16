module ag32_pwm4 (
    input  wire       clock,
    input  wire       reset_n,
    input  wire [7:0] duty0,
    input  wire [7:0] duty1,
    input  wire [7:0] duty2,
    input  wire [7:0] duty3,
    output wire [3:0] pwm
);
    reg [7:0] phase;

    always @(posedge clock) begin
        if (!reset_n)
            phase <= 0;
        else
            phase <= phase + 1'b1;
    end

    assign pwm[0] = phase < duty0;
    assign pwm[1] = phase < duty1;
    assign pwm[2] = phase < duty2;
    assign pwm[3] = phase < duty3;
endmodule
