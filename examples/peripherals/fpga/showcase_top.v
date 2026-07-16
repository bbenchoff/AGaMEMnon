/* Board-output example.  Only the four known-safe LED pins are constrained. */
(* top *) module top(input wire clk, output wire [3:0] led);
    reg [3:0] por_count = 0;
    wire reset_n = &por_count;
    wire [3:0] gpio;
    wire [3:0] unused_pwm;
    wire unused_uart, unused_sclk, unused_mosi, unused_cs;
    wire unused_scl_low, unused_sda_low;
    wire [2:0] unused_done;

    always @(posedge clk)
        if (!reset_n)
            por_count <= por_count + 1'b1;

    peripheral_showcase demo (
        .clock(clk), .reset_n(reset_n), .spi_miso(1'b0), .i2c_sda_in(1'b0),
        .gpio(gpio), .pwm(unused_pwm), .uart_tx(unused_uart),
        .spi_sclk(unused_sclk), .spi_mosi(unused_mosi), .spi_cs_n(unused_cs),
        .i2c_scl_drive_low(unused_scl_low), .i2c_sda_drive_low(unused_sda_low),
        .done(unused_done));
    assign led = gpio;
endmodule
