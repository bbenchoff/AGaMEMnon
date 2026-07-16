/* Structural/elaboration example that instantiates every soft block in this directory. */
module peripheral_showcase #(
    parameter integer CLK_HZ = 25_000_000,
    parameter integer STEP_HZ = 4,
    parameter integer UART_BAUD = 115_200,
    parameter integer SPI_HZ = 1_000_000,
    parameter integer I2C_HZ = 100_000
) (
    input  wire       clock,
    input  wire       reset_n,
    input  wire       spi_miso,
    input  wire       i2c_sda_in,
    output wire [3:0] gpio,
    output wire [3:0] pwm,
    output wire       uart_tx,
    output wire       spi_sclk,
    output wire       spi_mosi,
    output wire       spi_cs_n,
    output wire       i2c_scl_drive_low,
    output wire       i2c_sda_drive_low,
    output wire [2:0] done
);
    wire step;
    reg launched;
    wire launch = reset_n && !launched;
    wire uart_busy, spi_busy, i2c_busy;
    wire uart_done, spi_done, i2c_done;
    wire [7:0] spi_rx;
    wire i2c_ack_error;

    always @(posedge clock) begin
        if (!reset_n)
            launched <= 0;
        else
            launched <= 1;
    end

    ag32_timer_tick #(.DIVISOR(CLK_HZ / STEP_HZ)) step_timer (
        .clock(clock), .reset_n(reset_n), .enable(1'b1), .tick(step));
    ag32_gpio_walker walker (
        .clock(clock), .reset_n(reset_n), .step(step), .gpio(gpio));
    ag32_pwm4 pwm_bank (
        .clock(clock), .reset_n(reset_n),
        .duty0(8'd32), .duty1(8'd96), .duty2(8'd160), .duty3(8'd224), .pwm(pwm));
    ag32_uart_tx #(.CLOCKS_PER_BIT(CLK_HZ / UART_BAUD)) uart (
        .clock(clock), .reset_n(reset_n), .start(launch), .data(8'h55),
        .tx(uart_tx), .busy(uart_busy), .done(uart_done));
    ag32_spi_master #(.CLOCKS_PER_HALF_BIT(CLK_HZ / (2 * SPI_HZ))) spi (
        .clock(clock), .reset_n(reset_n), .start(launch), .tx_data(8'hA5), .miso(spi_miso),
        .sclk(spi_sclk), .mosi(spi_mosi), .cs_n(spi_cs_n), .rx_data(spi_rx),
        .busy(spi_busy), .done(spi_done));
    ag32_i2c_writer #(.CLOCKS_PER_PHASE(CLK_HZ / (4 * I2C_HZ))) i2c (
        .clock(clock), .reset_n(reset_n), .start(launch), .address(7'h50), .data(8'hA5),
        .sda_in(i2c_sda_in), .scl_drive_low(i2c_scl_drive_low),
        .sda_drive_low(i2c_sda_drive_low), .busy(i2c_busy), .done(i2c_done),
        .ack_error(i2c_ack_error));

    assign done = {i2c_done, spi_done, uart_done};
endmodule
