// First legal sequential use of the typed MCU clock/reset sources. The reset
// is synchronous to bus_clock so it maps through ordinary, fully modeled LUT
// data routing; dedicated asynchronous-reset controls remain future work.
module top;
  wire bus_clock;
  wire resetn;
  reg toggle;

  (* keep *) MCU_BUS_CLOCK mcu_bus_clock(.CLK(bus_clock));
  (* keep *) MCU_RESETN mcu_resetn(.RESETN(resetn));

  always @(posedge bus_clock) begin
    if (!resetn)
      toggle <= 1'b0;
    else
      toggle <= ~toggle;
  end

  (* keep *) MCU_DOUT mcu_h0(.DOUT(toggle));
endmodule
