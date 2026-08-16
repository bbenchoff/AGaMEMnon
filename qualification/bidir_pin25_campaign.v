// Bounded L48 PIN_25 dynamic-output-enable and bidirectional-readback campaign.
//
// PIN_25 is always open-drain style: it is either released or drives zero.
// No image can drive the line high.  The four tops deliberately separate the
// static electrical controls, the dynamic OE corridor, and fabric readback.

module pin25_release(input link, output observed);
  assign observed = ~link;
endmodule

module pin25_drive_low(output link);
  assign link = 1'b0;
endmodule

module pin25_dynamic(input drive_low, inout link);
  assign link = drive_low ? 1'b0 : 1'bz;
  // Preserve a real ingress consumer so the combined IOB is identical to the
  // readback image through the pad boundary; only the observation output is
  // absent.  The uarch requires exactly one reduction-LUT input consumer.
  (* keep *) wire sensed = ~link;
endmodule

module pin25_readback(input drive_low, inout link, output observed);
  assign link = drive_low ? 1'b0 : 1'bz;
  assign observed = ~link;
endmodule
