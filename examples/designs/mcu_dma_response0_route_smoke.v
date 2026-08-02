// Hardware-free strict smoke for DMA clear/terminal-count response channel 0.
// It only observes MCU-driven inputs and cannot request a transfer.
module top;
  wire dma_clear0;
  wire dma_tc0;
  (* keep *) MCU_DMA_CLR0 dma_clear_source(.DIN(dma_clear0));
  (* keep *) MCU_DMA_TC0 dma_tc_source(.DIN(dma_tc0));
  (* keep *) wire retained_probe;
  (* keep, BEL="X1Y4_SLICE2" *)
  LUT #(.K(4), .INIT(16'h0ff0)) dma_response_probe(
    .I({dma_clear0, dma_tc0, 2'b00}), .Q(retained_probe));
endmodule
