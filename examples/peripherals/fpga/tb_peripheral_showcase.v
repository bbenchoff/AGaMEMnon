`timescale 1ns/1ps
module tb_peripheral_showcase;
    reg clock = 0;
    reg reset_n = 0;
    wire [3:0] gpio, pwm;
    wire uart_tx, spi_sclk, spi_mosi, spi_cs_n;
    wire i2c_scl_drive_low, i2c_sda_drive_low;
    wire [2:0] done;
    reg saw_uart = 0, saw_spi = 0, saw_i2c = 0, saw_step = 0;

    always #5 clock = ~clock;
    always @(posedge clock) begin
        if (done[0]) saw_uart <= 1;
        if (done[1]) saw_spi <= 1;
        if (done[2]) saw_i2c <= 1;
        if (gpio != 4'b0001) saw_step <= 1;
    end

    peripheral_showcase #(
        .CLK_HZ(1000), .STEP_HZ(100), .UART_BAUD(100), .SPI_HZ(100), .I2C_HZ(25)
    ) dut (
        .clock(clock), .reset_n(reset_n), .spi_miso(spi_mosi), .i2c_sda_in(1'b0),
        .gpio(gpio), .pwm(pwm), .uart_tx(uart_tx), .spi_sclk(spi_sclk),
        .spi_mosi(spi_mosi), .spi_cs_n(spi_cs_n),
        .i2c_scl_drive_low(i2c_scl_drive_low), .i2c_sda_drive_low(i2c_sda_drive_low),
        .done(done));

    initial begin
        repeat (4) @(posedge clock);
        reset_n <= 1;
        repeat (1200) @(posedge clock);
        if (!(saw_uart && saw_spi && saw_i2c && saw_step)) begin
            $display("FAIL uart=%0d spi=%0d i2c=%0d step=%0d", saw_uart, saw_spi, saw_i2c, saw_step);
            $fatal(1);
        end
        if (dut.spi_rx !== 8'hA5) begin
            $display("FAIL SPI loopback rx=%02x", dut.spi_rx);
            $fatal(1);
        end
        if (dut.i2c_ack_error !== 1'b0) begin
            $display("FAIL unexpected I2C NACK");
            $fatal(1);
        end
        $display("PASS peripheral showcase");
        $finish;
    end
endmodule
