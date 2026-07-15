// Hardware boundary probe for the serial-mux receive half.  It uses the exact
// three receivers and pad buffers from the demo, but toggles PIN_16 whenever
// any channel completes a valid frame.
`define AGAMEMNON_SERIAL_MUX_LIBRARY
`include "examples/serial_mux/serial_mux.v"

(* top *) module top(
    input wire clock,
    input wire rx_a,
    input wire rx_b,
    input wire rx_c,
    output wire seen
);
    serial_mux #(.DEBUG_STROBE(3)) probe(
        .clock(clock), .rx_a(rx_a), .rx_b(rx_b), .rx_c(rx_c), .tx(seen));
endmodule
