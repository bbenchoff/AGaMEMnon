// L48 registered-input qualification: sample a physical pad in a fabric FF
// and drive the registered value back to another physical pad.
module registered_input(
    input  wire clock,
    input  wire pin_in,
    output reg  q
);
    always @(posedge clock)
        q <= pin_in;
endmodule
