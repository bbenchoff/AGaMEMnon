// Strict route-only smoke. No ADC control is driven and this image is not
// silicon-qualified; the sink is the known MCU GPIO observation endpoint.
module top;
    (* keep *) wire adc_eoc;

    AGRV2K_ADC0_EOC adc_source(.EOC(adc_eoc));
    (* keep, BEL="X10Y5_MCU2" *) MCU observation(.DIN(), .DOUT(adc_eoc));
endmodule
