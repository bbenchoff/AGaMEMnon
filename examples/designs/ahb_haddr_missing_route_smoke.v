// Hardware-free route smoke for HADDR[1:0] and HADDR[31:28].
// Directly returns each recovered source on its corresponding HRDATA bit.
// This extraction topology is not a legal AHB peripheral; do not load it.
module top;
  wire haddr0, haddr1, haddr28, haddr29, haddr30, haddr31;

  (* keep *) MCU_DIN mcu_haddr0  (.DIN(haddr0));
  (* keep *) MCU_DIN mcu_haddr1  (.DIN(haddr1));
  (* keep *) MCU_DIN mcu_haddr28 (.DIN(haddr28));
  (* keep *) MCU_DIN mcu_haddr29 (.DIN(haddr29));
  (* keep *) MCU_DIN mcu_haddr30 (.DIN(haddr30));
  (* keep *) MCU_DIN mcu_haddr31 (.DIN(haddr31));

  (* keep *) MCU_DOUT mcu_h0  (.DOUT(haddr0));
  (* keep *) MCU_DOUT mcu_h1  (.DOUT(haddr1));
  (* keep *) MCU_DOUT mcu_h28 (.DOUT(haddr28));
  (* keep *) MCU_DOUT mcu_h29 (.DOUT(haddr29));
  (* keep *) MCU_DOUT mcu_h30 (.DOUT(haddr30));
  (* keep *) MCU_DOUT mcu_h31 (.DOUT(haddr31));
endmodule
