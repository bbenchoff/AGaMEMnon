// Hardware-free strict smoke for all 64 fabric-master request-payload sinks.
// Two physical outputs carry the same safe-low value from one vendor-observed
// slice. This proves shared idle routing, not independent payload sources.
module top;
  (* keep *) wire request_low_omux0;
  (* keep *) wire request_low_omux2;
  (* keep, BEL="X14Y12_DUAL_SLICE0" *)
  AGRV2K_DUAL_LUT_CONST #(.VALUE(1'b0)) request_source(
    .F0(request_low_omux0), .F2(request_low_omux2));

  (* keep, BEL="X10Y5_MCU_DOUT176" *) MCU_DOUT haddr0(.DOUT(request_low_omux2));
  (* keep, BEL="X10Y5_MCU_DOUT177" *) MCU_DOUT haddr1(.DOUT(request_low_omux0));
  (* keep, BEL="X10Y5_MCU_DOUT178" *) MCU_DOUT haddr2(.DOUT(request_low_omux0));
  (* keep, BEL="X10Y5_MCU_DOUT179" *) MCU_DOUT haddr3(.DOUT(request_low_omux0));
  (* keep, BEL="X10Y5_MCU_DOUT180" *) MCU_DOUT haddr4(.DOUT(request_low_omux2));
  (* keep, BEL="X10Y5_MCU_DOUT181" *) MCU_DOUT haddr5(.DOUT(request_low_omux2));
  (* keep, BEL="X10Y5_MCU_DOUT182" *) MCU_DOUT haddr6(.DOUT(request_low_omux2));
  (* keep, BEL="X10Y5_MCU_DOUT183" *) MCU_DOUT haddr7(.DOUT(request_low_omux2));
  (* keep, BEL="X10Y5_MCU_DOUT184" *) MCU_DOUT haddr8(.DOUT(request_low_omux2));
  (* keep, BEL="X10Y5_MCU_DOUT185" *) MCU_DOUT haddr9(.DOUT(request_low_omux2));
  (* keep, BEL="X10Y5_MCU_DOUT186" *) MCU_DOUT haddr10(.DOUT(request_low_omux2));
  (* keep, BEL="X10Y5_MCU_DOUT187" *) MCU_DOUT haddr11(.DOUT(request_low_omux2));
  (* keep, BEL="X10Y5_MCU_DOUT188" *) MCU_DOUT haddr12(.DOUT(request_low_omux2));
  (* keep, BEL="X10Y5_MCU_DOUT189" *) MCU_DOUT haddr13(.DOUT(request_low_omux2));
  (* keep, BEL="X10Y5_MCU_DOUT190" *) MCU_DOUT haddr14(.DOUT(request_low_omux2));
  (* keep, BEL="X10Y5_MCU_DOUT191" *) MCU_DOUT haddr15(.DOUT(request_low_omux2));
  (* keep, BEL="X10Y5_MCU_DOUT192" *) MCU_DOUT haddr16(.DOUT(request_low_omux0));
  (* keep, BEL="X10Y5_MCU_DOUT193" *) MCU_DOUT haddr17(.DOUT(request_low_omux0));
  (* keep, BEL="X10Y5_MCU_DOUT194" *) MCU_DOUT haddr18(.DOUT(request_low_omux0));
  (* keep, BEL="X10Y5_MCU_DOUT195" *) MCU_DOUT haddr19(.DOUT(request_low_omux2));
  (* keep, BEL="X10Y5_MCU_DOUT196" *) MCU_DOUT haddr20(.DOUT(request_low_omux2));
  (* keep, BEL="X10Y5_MCU_DOUT197" *) MCU_DOUT haddr21(.DOUT(request_low_omux2));
  (* keep, BEL="X10Y5_MCU_DOUT198" *) MCU_DOUT haddr22(.DOUT(request_low_omux2));
  (* keep, BEL="X10Y5_MCU_DOUT199" *) MCU_DOUT haddr23(.DOUT(request_low_omux2));
  (* keep, BEL="X10Y5_MCU_DOUT200" *) MCU_DOUT haddr24(.DOUT(request_low_omux2));
  (* keep, BEL="X10Y5_MCU_DOUT201" *) MCU_DOUT haddr25(.DOUT(request_low_omux2));
  (* keep, BEL="X10Y5_MCU_DOUT202" *) MCU_DOUT haddr26(.DOUT(request_low_omux2));
  (* keep, BEL="X10Y5_MCU_DOUT203" *) MCU_DOUT haddr27(.DOUT(request_low_omux2));
  (* keep, BEL="X10Y5_MCU_DOUT204" *) MCU_DOUT haddr28(.DOUT(request_low_omux2));
  (* keep, BEL="X10Y5_MCU_DOUT205" *) MCU_DOUT haddr29(.DOUT(request_low_omux2));
  (* keep, BEL="X10Y5_MCU_DOUT206" *) MCU_DOUT haddr30(.DOUT(request_low_omux2));
  (* keep, BEL="X10Y5_MCU_DOUT207" *) MCU_DOUT haddr31(.DOUT(request_low_omux0));

  (* keep, BEL="X10Y5_MCU_DOUT208" *) MCU_DOUT hwdata0(.DOUT(request_low_omux0));
  (* keep, BEL="X10Y5_MCU_DOUT209" *) MCU_DOUT hwdata1(.DOUT(request_low_omux0));
  (* keep, BEL="X10Y5_MCU_DOUT210" *) MCU_DOUT hwdata2(.DOUT(request_low_omux2));
  (* keep, BEL="X10Y5_MCU_DOUT211" *) MCU_DOUT hwdata3(.DOUT(request_low_omux2));
  (* keep, BEL="X10Y5_MCU_DOUT212" *) MCU_DOUT hwdata4(.DOUT(request_low_omux2));
  (* keep, BEL="X10Y5_MCU_DOUT213" *) MCU_DOUT hwdata5(.DOUT(request_low_omux2));
  (* keep, BEL="X10Y5_MCU_DOUT214" *) MCU_DOUT hwdata6(.DOUT(request_low_omux2));
  (* keep, BEL="X10Y5_MCU_DOUT215" *) MCU_DOUT hwdata7(.DOUT(request_low_omux2));
  (* keep, BEL="X10Y5_MCU_DOUT216" *) MCU_DOUT hwdata8(.DOUT(request_low_omux2));
  (* keep, BEL="X10Y5_MCU_DOUT217" *) MCU_DOUT hwdata9(.DOUT(request_low_omux2));
  (* keep, BEL="X10Y5_MCU_DOUT218" *) MCU_DOUT hwdata10(.DOUT(request_low_omux2));
  (* keep, BEL="X10Y5_MCU_DOUT219" *) MCU_DOUT hwdata11(.DOUT(request_low_omux2));
  (* keep, BEL="X10Y5_MCU_DOUT220" *) MCU_DOUT hwdata12(.DOUT(request_low_omux2));
  (* keep, BEL="X10Y5_MCU_DOUT221" *) MCU_DOUT hwdata13(.DOUT(request_low_omux2));
  (* keep, BEL="X10Y5_MCU_DOUT222" *) MCU_DOUT hwdata14(.DOUT(request_low_omux0));
  (* keep, BEL="X10Y5_MCU_DOUT223" *) MCU_DOUT hwdata15(.DOUT(request_low_omux0));
  (* keep, BEL="X10Y5_MCU_DOUT224" *) MCU_DOUT hwdata16(.DOUT(request_low_omux2));
  (* keep, BEL="X10Y5_MCU_DOUT225" *) MCU_DOUT hwdata17(.DOUT(request_low_omux2));
  (* keep, BEL="X10Y5_MCU_DOUT226" *) MCU_DOUT hwdata18(.DOUT(request_low_omux2));
  (* keep, BEL="X10Y5_MCU_DOUT227" *) MCU_DOUT hwdata19(.DOUT(request_low_omux2));
  (* keep, BEL="X10Y5_MCU_DOUT228" *) MCU_DOUT hwdata20(.DOUT(request_low_omux2));
  (* keep, BEL="X10Y5_MCU_DOUT229" *) MCU_DOUT hwdata21(.DOUT(request_low_omux2));
  (* keep, BEL="X10Y5_MCU_DOUT230" *) MCU_DOUT hwdata22(.DOUT(request_low_omux2));
  (* keep, BEL="X10Y5_MCU_DOUT231" *) MCU_DOUT hwdata23(.DOUT(request_low_omux2));
  (* keep, BEL="X10Y5_MCU_DOUT232" *) MCU_DOUT hwdata24(.DOUT(request_low_omux2));
  (* keep, BEL="X10Y5_MCU_DOUT233" *) MCU_DOUT hwdata25(.DOUT(request_low_omux2));
  (* keep, BEL="X10Y5_MCU_DOUT234" *) MCU_DOUT hwdata26(.DOUT(request_low_omux2));
  (* keep, BEL="X10Y5_MCU_DOUT235" *) MCU_DOUT hwdata27(.DOUT(request_low_omux2));
  (* keep, BEL="X10Y5_MCU_DOUT236" *) MCU_DOUT hwdata28(.DOUT(request_low_omux0));
  (* keep, BEL="X10Y5_MCU_DOUT237" *) MCU_DOUT hwdata29(.DOUT(request_low_omux0));
  (* keep, BEL="X10Y5_MCU_DOUT238" *) MCU_DOUT hwdata30(.DOUT(request_low_omux0));
  (* keep, BEL="X10Y5_MCU_DOUT239" *) MCU_DOUT hwdata31(.DOUT(request_low_omux0));
endmodule
