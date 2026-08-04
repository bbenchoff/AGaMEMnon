// Minimal qualified proof that the typed MCU bus-clock source reaches a
// fabric FF. The TFF state is returned on HRDATA[0]. The open backend keeps
// this single-feedback subset on its silicon-qualified direct-D site.
module top;
  wire bus_clock;
  reg toggle;

  (* keep *) MCU_BUS_CLOCK mcu_bus_clock(.CLK(bus_clock));
  always @(posedge bus_clock)
    toggle <= ~toggle;

  (* keep *) MCU_DOUT mcu_h0(.DOUT(toggle));
endmodule
