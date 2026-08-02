// SRAM qualification probe for the typed MCU bus-clock source. A Johnson
// divider changes slowly enough that MCU GPIO reads cannot phase-lock to a
// one-bit toggle. Configuration reset initializes the six FFs to zero; no
// package IO or bus transaction is used.
module top;
  wire bus_clock;
  reg [5:0] divider;

  (* keep *) MCU_BUS_CLOCK mcu_bus_clock(.CLK(bus_clock));

  always @(posedge bus_clock)
    divider <= {divider[4:0], ~divider[5]};

  (* keep *) MCU_DOUT mcu_h0(.DOUT(divider[5]));
endmodule
