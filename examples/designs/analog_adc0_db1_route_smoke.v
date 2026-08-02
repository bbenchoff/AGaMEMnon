// Strict route-only smoke. No ADC control is driven and this image is not
// silicon-qualified; the sink is the known MCU GPIO observation endpoint.
module top;
    (* keep *) wire adc_db1;

    AGRV2K_ADC0_DB1 adc_source(.DB(adc_db1));
    (* keep, BEL="X10Y5_MCU2" *) MCU observation(.DIN(), .DOUT(adc_db1));
endmodule
