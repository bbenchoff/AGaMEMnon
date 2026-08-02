// Hardware-free strict smoke for the isolated MCU stop-status corridor.
// This observes a data signal only; it does not qualify stop/gating behavior.
module top;
  wire stop_state;
  (* keep *) MCU_STOP stop_source(.DIN(stop_state));
  (* keep, BEL="X10Y5_MCU2" *)
  MCU stop_observation_sink(.DIN(), .DOUT(stop_state));
endmodule
