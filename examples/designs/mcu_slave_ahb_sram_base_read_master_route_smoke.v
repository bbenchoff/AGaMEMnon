// Reset-idle whole-wrapper route vehicle for the exact SRAM-base read master.
// The protocol-presenter simulation exercises both bounded word addresses; this
// desk build proves only that the complete lowered boundary composes and emits.
module top;
  (* keep *) wire busy;
  (* keep *) wire done;
  (* keep *) wire response_observation;

  (* keep *) agamemnon_fabric_ahb_read_master_ag32_sram_base instrument(
    .start(1'b0),
    .word_select(1'b0),
    .busy(busy),
    .done(done),
    .response_observation(response_observation)
  );
endmodule
