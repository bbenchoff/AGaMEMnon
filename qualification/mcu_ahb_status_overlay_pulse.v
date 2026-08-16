// Minimal ordinary-user RTL used to qualify `agamemnon status-overlay`.
//
// This is deliberately not a pre-routed derivative.  It is synthesized and
// routed by the public `build --internal-ports` path, then its scalar
// `status_set` output is composed into the hash-pinned public32 W1C core.
module status_overlay_pulse(output wire status_set);
    wire clk;
    reg started = 1'b0;
    reg delayed = 1'b0;

    MCU_BUS_CLOCK clock_source(.CLK(clk));

    always @(posedge clk) begin
        started <= 1'b1;
        delayed <= started;
    end

    assign status_set = started & ~delayed;
endmodule
