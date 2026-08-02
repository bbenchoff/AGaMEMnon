// Hardware-free strict smoke for the four channel-zero DMA request sinks.
// The recovered vendor oracle used one shared source, so this test deliberately
// proves only a shared safe-low route and not four independently routable nets.
module top;
  (* keep *) wire dma_request0_low;
  (* keep, BEL="X14Y12_SLICE0" *)
  LUT #(.K(4), .INIT(16'h0000)) dma_request0_source(
    .I(4'b0000), .Q(dma_request0_low));

  (* keep *) MCU_DMA_BREQ0 dma_breq0_sink(.DOUT(dma_request0_low));
  (* keep *) MCU_DMA_LBREQ0 dma_lbreq0_sink(.DOUT(dma_request0_low));
  (* keep *) MCU_DMA_SREQ0 dma_sreq0_sink(.DOUT(dma_request0_low));
  (* keep *) MCU_DMA_LSREQ0 dma_lsreq0_sink(.DOUT(dma_request0_low));
endmodule
