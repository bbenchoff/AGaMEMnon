// Collision-free three-lane UART merger.
//
// UART lines idle high, so their logical AND forwards whichever lane is active
// while the other two remain idle.  The Pico fixture schedules A, then B, then
// C without overlap and the output is ABC.  Overlapping frames collide; this
// intentionally small demo does not claim buffering or arbitration.

(* top *)
module serial_mux(
    input  wire clock, // retained for the standard AG32 top-level interface
    input  wire rx_a,
    input  wire rx_b,
    input  wire rx_c,
    output wire tx
);
    wire a, b, c;

    // Give each physical input one independently placeable, slot-exact sink.
    (* keep *) LUT #(.K(4), .INIT(16'hAAAA)) inbuf_a(.I({3'b000, rx_a}), .Q(a));
    (* keep *) LUT #(.K(4), .INIT(16'hAAAA)) inbuf_b(.I({3'b000, rx_b}), .Q(b));
    (* keep *) LUT #(.K(4), .INIT(16'hAAAA)) inbuf_c(.I({3'b000, rx_c}), .Q(c));

    assign tx = a & b & c;
endmodule
