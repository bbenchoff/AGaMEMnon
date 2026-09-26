// Experimental source interface only. This black box supplies no behavioral
// model and does not bypass site, configuration, routing or initialized-read
// admission. Read only through the explicit experimental-config option.
(* blackbox *)
module ALTA_BRAM9K #(
    parameter [9215:0] INIT_VAL = 0,
    parameter [4:0] PORTA_WIDTH = 0, PORTB_WIDTH = 0,
    parameter [1:0] CLKMODE = 0,
    parameter PORTA_CLKIN_EN = 0, PORTA_CLKOUT_EN = 0,
    parameter PORTA_RSTIN_EN = 0, PORTA_RSTOUT_EN = 0,
    parameter PORTB_CLKIN_EN = 0, PORTB_CLKOUT_EN = 0,
    parameter PORTB_RSTIN_EN = 0, PORTB_RSTOUT_EN = 0,
    parameter PORTA_OUTREG = 0, PORTB_OUTREG = 0,
    parameter PORTA_WRITETHRU = 0, PORTB_WRITETHRU = 0,
    parameter PACKEDMODE = 0,
    parameter [1:0] DLYTIME = 0, RSEN_DLY = 0
) (
    input [12:0] AddressA, input [17:0] DataInA, output [17:0] DataOutA,
    input WeA, ReA, input [1:0] ByteEnA,
    input [12:0] AddressB, input [17:0] DataInB, output [17:0] DataOutB,
    input WeB, ReB, input [1:0] ByteEnB,
    input Clk0, Clk1, ClkEn0, ClkEn1,
    input AsyncReset0, AsyncReset1, AddressStallA, AddressStallB
);
endmodule
